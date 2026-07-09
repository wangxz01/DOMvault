"""FastAPI control panel for DOMVault.

Endpoints (MVP):
    GET  /                       control panel HTML
    POST /api/open               {"url": "..."} -> open/navigate the browser
    POST /api/save               save current page HTML to saved_html/
    GET  /api/status             current session state
    GET  /api/download/<name>    download a saved HTML file
    POST /api/close              close the browser (server keeps running)

The saved HTML directory defaults to ``./saved_html`` relative to the current
working directory when the server started; it is configurable via
``set_output_dir``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import browser
from .saver import InvalidURL, normalize_url, save_html

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"

# Output directory for saved HTML. Defaults to ./saved_html under CWD.
_output_dir: Path = Path("saved_html")


def set_output_dir(path: Path) -> None:
    """Override the directory where saved HTML files are written."""
    global _output_dir
    _output_dir = Path(path)


def get_output_dir() -> Path:
    return _output_dir


app = FastAPI(title="DOMVault", version="0.1.0")


# --- request/response models ---------------------------------------------

class OpenRequest(BaseModel):
    url: str
    browser: Optional[str] = "chromium"


class SaveRequest(BaseModel):
    # Reserved for V0.2 (custom filename). Ignored in MVP.
    filename: Optional[str] = None


# --- routes --------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    """Serve the control panel."""
    html = _INDEX_HTML.read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.post("/api/open")
async def api_open(payload: OpenRequest) -> JSONResponse:
    try:
        url = normalize_url(payload.url)
    except InvalidURL as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    kind = (payload.browser or "chromium").lower()
    if kind not in ("chromium", "firefox", "webkit"):
        raise HTTPException(status_code=400, detail=f"Unsupported browser: {payload.browser}")
    try:
        result = await browser.open_url(url, kind=kind)  # type: ignore[arg-type]
    except browser.BrowserError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return JSONResponse(result)


@app.post("/api/save")
async def api_save(payload: Optional[SaveRequest] = None) -> JSONResponse:
    try:
        html = await browser.current_html()
        url = await browser.current_url()
    except browser.BrowserError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    try:
        path = save_html(html, url, get_output_dir())
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    filename = path.name
    return JSONResponse({
        "ok": True,
        "path": str(path.resolve()),
        "filename": filename,
        "url": url,
        "download_url": f"/api/download/{filename}",
    })


@app.get("/api/status")
async def api_status() -> JSONResponse:
    return JSONResponse(await browser.status())


@app.get("/api/download/{filename}")
async def api_download(filename: str) -> FileResponse:
    # Prevent path traversal: only allow bare filenames inside the output dir.
    if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename.")
    target = (get_output_dir() / filename).resolve()
    base = get_output_dir().resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(str(target), media_type="text/html", filename=filename)


@app.post("/api/close")
async def api_close() -> JSONResponse:
    await browser.close()
    return JSONResponse({"ok": True})
