"""FastAPI control panel for DOMVault.

Endpoints (V0.2):
    GET  /                            control panel HTML
    POST /api/open                    {"url": "...", "storage_state"?: {...}}
    POST /api/save                    save current page as a snapshot directory
    GET  /api/status                  current session state
    GET  /api/download/{run}/{file}   download a file from a snapshot directory
    GET  /api/snapshots               list saved snapshot directories
    POST /api/close                   close the browser (server keeps running)

The output directory defaults to ``./saved_html`` and is configurable via
``set_output_dir``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from . import browser
from .saver import InvalidURL, normalize_url, save_snapshot

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"

# Output directory for snapshots. Defaults to ./saved_html under CWD.
_output_dir: Path = Path("saved_html")


def set_output_dir(path: Path) -> None:
    """Override the directory where snapshots are written."""
    global _output_dir
    _output_dir = Path(path)


def get_output_dir() -> Path:
    return _output_dir


app = FastAPI(title="DOMVault", version="0.2.0")


# --- request/response models ---------------------------------------------

class OpenRequest(BaseModel):
    url: str
    browser: Optional[str] = "chromium"
    # Optional Playwright storage state (as produced by context.storage_state())
    # to restore cookies/localStorage into the new context.
    storage_state: Optional[Any] = Field(default=None)


class SaveRequest(BaseModel):
    # Optional custom directory name for the snapshot.
    filename: Optional[str] = None


# --- helpers -------------------------------------------------------------

def _bad_segment(seg: str) -> bool:
    """True if a path segment is unsafe (traversal / empty / absolute)."""
    if not seg or seg in (".", ".."):
        return True
    if "/" in seg or "\\" in seg:
        return True
    return False


# --- routes --------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve the control panel."""
    return HTMLResponse(_INDEX_HTML.read_text(encoding="utf-8"))


@app.post("/api/open")
async def api_open(payload: OpenRequest) -> JSONResponse:
    try:
        url = normalize_url(payload.url)
    except InvalidURL as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    kind = (payload.browser or "chromium").lower()
    if kind not in ("chromium", "firefox", "webkit"):
        raise HTTPException(status_code=400, detail=f"Unsupported browser: {payload.browser}")
    storage_state = payload.storage_state
    if storage_state is not None and not isinstance(storage_state, (dict, list)):
        raise HTTPException(
            status_code=400,
            detail="storage_state must be an object (from a storage_state.json).",
        )
    try:
        result = await browser.open_url(url, kind=kind, storage_state=storage_state)  # type: ignore[arg-type]
    except browser.BrowserError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return JSONResponse(result)


@app.post("/api/save")
async def api_save(payload: Optional[SaveRequest] = None) -> JSONResponse:
    payload = payload or SaveRequest()
    # HTML + URL + title are required.
    try:
        html = await browser.current_html()
        url = await browser.current_url()
        title = await browser.current_title()
    except browser.BrowserError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # Screenshot and storage state are best-effort: if they fail we still save
    # the HTML, recording null in metadata.
    screenshot_png: Optional[bytes] = None
    try:
        screenshot_png = await browser.current_screenshot()
    except browser.BrowserError:
        screenshot_png = None
    storage_state: Optional[dict] = None
    try:
        storage_state = await browser.current_storage_state()
    except browser.BrowserError:
        storage_state = None
    # Frames (main + iframes) for separate iframe HTML capture.
    frames: Optional[list] = None
    try:
        frames = await browser.frame_contents()
    except browser.BrowserError:
        frames = None
    # Point-in-time snapshot of network + console events for the run so far.
    collector = browser.get_collector()
    network_events = list(collector.network)
    console_events = list(collector.console)

    try:
        run_dir, metadata = save_snapshot(
            html,
            url=url,
            title=title,
            out_dir=get_output_dir(),
            screenshot_png=screenshot_png,
            storage_state=storage_state,
            frames=frames,
            network_events=network_events,
            console_events=console_events,
            custom_name=payload.filename,
        )
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    run_name = run_dir.name
    downloads = {
        "html": f"/api/download/{run_name}/page.html",
        "metadata": f"/api/download/{run_name}/metadata.json",
    }
    if screenshot_png is not None:
        downloads["screenshot"] = f"/api/download/{run_name}/screenshot.png"
    if storage_state is not None:
        downloads["storage_state"] = f"/api/download/{run_name}/storage_state.json"
    if metadata.get("frames_file"):
        downloads["frames"] = f"/api/download/{run_name}/{metadata['frames_file']}"
    if metadata.get("network_file"):
        downloads["network"] = f"/api/download/{run_name}/{metadata['network_file']}"
    if metadata.get("console_file"):
        downloads["console"] = f"/api/download/{run_name}/{metadata['console_file']}"

    return JSONResponse({
        "ok": True,
        "run_dir": run_name,
        "path": str(run_dir.resolve()),
        "url": url,
        "title": title,
        "files": {
            "html": "page.html",
            "screenshot": "screenshot.png" if screenshot_png is not None else None,
            "storage_state": "storage_state.json" if storage_state is not None else None,
            "frames": metadata.get("frames_file"),
            "network": metadata.get("network_file"),
            "console": metadata.get("console_file"),
        },
        "counts": {
            "frames": metadata.get("frame_count", 0),
            "network": metadata.get("network_event_count", 0),
            "console": metadata.get("console_event_count", 0),
        },
        "frames": metadata.get("frames", []),
        "downloads": downloads,
        "metadata": metadata,
    })


@app.get("/api/status")
async def api_status() -> JSONResponse:
    return JSONResponse(await browser.status())


@app.get("/api/frames")
async def api_frames() -> JSONResponse:
    """List all frames (main + iframes) currently in the page."""
    try:
        frames = await browser.list_frames()
    except browser.BrowserError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return JSONResponse({"frames": frames})


@app.get("/api/snapshots")
async def api_snapshots() -> JSONResponse:
    """List snapshot directories in the output folder, newest first."""
    base = get_output_dir()
    if not base.is_dir():
        return JSONResponse({"snapshots": []})
    entries = []
    for child in base.iterdir():
        if not child.is_dir():
            continue
        meta_path = child / "metadata.json"
        meta = None
        if meta_path.is_file():
            try:
                import json
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                meta = None
        entries.append({
            "name": child.name,
            "mtime": int(child.stat().st_mtime),
            "metadata": meta,
        })
    entries.sort(key=lambda e: e["mtime"], reverse=True)
    return JSONResponse({"snapshots": entries})


@app.get("/api/download/{run_name}/{file_path:path}")
async def api_download(run_name: str, file_path: str) -> FileResponse:
    """Download a single file from a snapshot directory.

    ``file_path`` may be nested (e.g. ``frames/001_widget.html``). Strict
    per-segment validation + resolve-within-base guards against traversal.
    """
    if _bad_segment(run_name):
        raise HTTPException(status_code=400, detail="Invalid path.")
    segments = [seg for seg in file_path.replace("\\", "/").split("/") if seg != ""]
    if not segments or any(_bad_segment(seg) for seg in segments):
        raise HTTPException(status_code=400, detail="Invalid path.")
    base = get_output_dir().resolve()
    target = base.joinpath(run_name, *segments).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path.")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    media = {
        ".html": "text/html",
        ".png": "image/png",
        ".json": "application/json",
        ".har": "application/json",
        ".jsonl": "application/jsonl",
    }.get(target.suffix.lower(), "application/octet-stream")
    return FileResponse(str(target), media_type=media, filename=target.name)


@app.post("/api/close")
async def api_close() -> JSONResponse:
    await browser.close()
    return JSONResponse({"ok": True})
