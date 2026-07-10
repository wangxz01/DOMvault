"""Shared snapshot capture orchestration.

Used by both the FastAPI control panel (``server.api_save``) and the headless
CLI ``capture`` command, so the web UI and the CLI share one code path for
gathering artifacts and writing a snapshot directory.

Raises :class:`browser.BrowserError` if no session is open (the caller decides
the HTTP/CLI error representation).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from . import browser
from .saver import save_snapshot


async def capture_snapshot(
    out_dir: Path,
    *,
    custom_name: Optional[str] = None,
    want_screenshot: bool = True,
    want_frames: bool = True,
    want_network: bool = True,
    want_console: bool = True,
) -> dict[str, Any]:
    """Gather all artifacts from the current session and write a snapshot.

    HTML/URL/title are required (they raise :class:`browser.BrowserError` if no
    page is open). Screenshot, storage state, frames, network, and console are
    best-effort: a failure in any of them still yields a snapshot with the rest,
    recording ``None`` in metadata. Returns a dict describing the run.
    """
    html = await browser.current_html()
    url = await browser.current_url()
    title = await browser.current_title()

    screenshot_png: Optional[bytes] = None
    if want_screenshot:
        try:
            screenshot_png = await browser.current_screenshot()
        except browser.BrowserError:
            screenshot_png = None

    storage_state: Optional[dict] = None
    try:
        storage_state = await browser.current_storage_state()
    except browser.BrowserError:
        storage_state = None

    frames: Optional[list] = None
    if want_frames:
        try:
            frames = await browser.frame_contents()
        except browser.BrowserError:
            frames = None

    collector = browser.get_collector()
    network_events = list(collector.network) if want_network else None
    console_events = list(collector.console) if want_console else None

    run_dir, metadata = save_snapshot(
        html,
        url=url,
        title=title,
        out_dir=out_dir,
        screenshot_png=screenshot_png,
        storage_state=storage_state,
        frames=frames,
        network_events=network_events,
        console_events=console_events,
        custom_name=custom_name,
    )

    return {
        "run_dir": run_dir.name,
        "path": str(run_dir.resolve()),
        "url": url,
        "title": title,
        "metadata": metadata,
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
    }
