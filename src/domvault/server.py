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

import datetime
import shutil
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from . import browser
from .capture import capture_snapshot
from .saver import InvalidURL, normalize_url

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


app = FastAPI(title="DOMVault", version="1.0.0")


# --- request/response models ---------------------------------------------

class OpenRequest(BaseModel):
    url: str
    browser: Optional[str] = "chromium"
    # Optional Playwright storage state (as produced by context.storage_state())
    # to restore cookies/localStorage into the new context.
    storage_state: Optional[Any] = Field(default=None)
    # If True, record the whole session's network to a HAR file (finalized on close).
    record_har: bool = False


class SaveRequest(BaseModel):
    # Optional custom directory name for the snapshot.
    filename: Optional[str] = None


class SelectorRequest(BaseModel):
    selector: str
    kind: str = "css"  # "css" | "xpath"
    limit: int = 10


class HighlightRequest(BaseModel):
    selector: str
    kind: str = "css"
    color: Optional[str] = "#ff5252"


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
        result = await browser.open_url(  # type: ignore[arg-type]
            url, kind=kind, storage_state=storage_state, record_har=payload.record_har
        )
    except browser.BrowserError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return JSONResponse(result)


@app.post("/api/save")
async def api_save(payload: Optional[SaveRequest] = None) -> JSONResponse:
    payload = payload or SaveRequest()
    try:
        result = await capture_snapshot(get_output_dir(), custom_name=payload.filename)
    except browser.BrowserError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    run_name = result["run_dir"]
    files = result["files"]
    downloads = {
        "html": f"/api/download/{run_name}/page.html",
        "metadata": f"/api/download/{run_name}/metadata.json",
    }
    if files["screenshot"]:
        downloads["screenshot"] = f"/api/download/{run_name}/screenshot.png"
    if files["storage_state"]:
        downloads["storage_state"] = f"/api/download/{run_name}/storage_state.json"
    for key in ("frames", "network", "console"):
        if files[key]:
            downloads[key] = f"/api/download/{run_name}/{files[key]}"
    result["downloads"] = downloads
    result["ok"] = True
    return JSONResponse(result)


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
    """Close the browser. If a HAR was being recorded, finalize and store it."""
    har_tmp = await browser.close()  # str temp path, or None
    har_info: Optional[dict] = None
    if har_tmp:
        src = Path(har_tmp)
        try:
            if src.exists() and src.stat().st_size > 0:
                har_dir = get_output_dir() / "har"
                har_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = har_dir / f"session_{ts}.har"
                shutil.move(str(src), str(dest))
                har_info = {
                    "filename": dest.name,
                    "path": str(dest.resolve()),
                    "download_url": f"/api/har/{dest.name}",
                }
            else:
                src.unlink(missing_ok=True)
        except OSError:
            # Best-effort cleanup; never fail the close because of the HAR.
            try:
                if src.exists():
                    src.unlink(missing_ok=True)
            except OSError:
                pass
    return JSONResponse({"ok": True, "har": har_info})


# --- selector testing + highlighting -------------------------------------

@app.post("/api/test-selector")
async def api_test_selector(payload: SelectorRequest) -> JSONResponse:
    kind = (payload.kind or "css").lower()
    if kind not in ("css", "xpath"):
        raise HTTPException(status_code=400, detail="kind must be 'css' or 'xpath'.")
    if not payload.selector:
        raise HTTPException(status_code=400, detail="selector is required.")
    try:
        result = await browser.test_selector(payload.selector, kind=kind, limit=payload.limit)  # type: ignore[arg-type]
    except browser.BrowserError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return JSONResponse(result)


@app.post("/api/highlight")
async def api_highlight(payload: HighlightRequest) -> JSONResponse:
    kind = (payload.kind or "css").lower()
    if kind not in ("css", "xpath"):
        raise HTTPException(status_code=400, detail="kind must be 'css' or 'xpath'.")
    try:
        result = await browser.highlight(payload.selector, kind=kind, color=payload.color or "#ff5252")  # type: ignore[arg-type]
    except browser.BrowserError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return JSONResponse(result)


@app.post("/api/clear-highlight")
async def api_clear_highlight() -> JSONResponse:
    try:
        await browser.clear_highlight()
    except browser.BrowserError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return JSONResponse({"ok": True})


# --- HAR download --------------------------------------------------------

@app.get("/api/har/{filename}")
async def api_har(filename: str) -> FileResponse:
    """Download a finalized session HAR file from the output dir's har/ folder."""
    if _bad_segment(filename) or not filename.lower().endswith(".har"):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    target = (get_output_dir() / "har" / filename).resolve()
    base = (get_output_dir() / "har").resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="HAR file not found.")
    return FileResponse(str(target), media_type="application/json", filename=filename)
