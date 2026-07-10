"""Async Playwright session manager for DOMVault.

Holds a single headed browser/page as module-level state inside the event
loop. All functions are coroutines meant to be awaited from the FastAPI
request handlers in ``server.py``.

Lifecycle:
    await open_url(url)   # lazy-starts playwright + browser on first call
    await status()        # read-only snapshot of current state
    await current_html()  # page.content() — the rendered DOM
    await close()         # closes browser; next open_url() re-creates it
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    async_playwright,
)

from .collectors import Collector

BrowserKind = Literal["chromium", "firefox", "webkit"]
SelectorKind = Literal["css", "xpath"]

# A module-level holder keeps everything on the single asyncio event loop that
# uvicorn runs. We never touch Playwright from another thread.
@dataclass
class _Session:
    pw: object = None              # Playwright instance from async_playwright().start(); stop via .stop()
    browser: Optional[Browser] = None
    context: Optional[BrowserContext] = None
    page: Optional[Page] = None
    kind: BrowserKind = "chromium"
    har_path: Optional[str] = None  # temp HAR file path while recording; None otherwise

    @property
    def open(self) -> bool:
        return self.page is not None and not self.page.is_closed()


_session = _Session()

# Bounded buffer of network + console events for the current context. Reset on
# every new context. Read by the server at save time.
_collector = Collector()


class BrowserError(RuntimeError):
    """User-facing browser error (bad URL, navigation failure, closed browser)."""


async def _ensure_started(
    kind: BrowserKind,
    storage_state: dict | list | str | None = None,
    record_har: bool = False,
    headless: bool = False,
) -> None:
    """Ensure browser/context/page are running, applying ``storage_state`` if given.

    Reuses an already-alive browser/context when possible (e.g. after the user
    closed only the page/window). Only does a full restart when the browser
    process itself is gone. ``headless`` only takes effect when a new browser
    is launched (the web UI passes False, the CLI capture command passes True).
    When ``storage_state`` is provided, a fresh context carrying that state is
    created so login cookies/localStorage are restored. When ``record_har`` is
    True (and a new context is being created), all network traffic for the
    session is recorded to a temp HAR file.
    """
    # Fast path: session healthy and no storage_state requested.
    if (
        storage_state is None
        and _session.page is not None
        and not _session.page.is_closed()
    ):
        return

    # Full start if the browser process is gone (or first run).
    browser_alive = (
        _session.pw is not None
        and _session.browser is not None
        and _session.browser.is_connected()
    )
    if not browser_alive:
        await _hard_stop()
        try:
            pw = await async_playwright().start()
        except PlaywrightError as exc:  # pragma: no cover - environment error
            raise BrowserError(f"Could not start Playwright: {exc}") from exc
        _session.pw = pw
        _session.kind = kind
        try:
            _session.browser = await getattr(pw, kind).launch(headless=headless)
        except PlaywrightError as exc:
            await _hard_stop()
            if "executable doesn't exist" in str(exc) or "playwright install" in str(exc).lower():
                raise BrowserError(
                    "Playwright browser binary not found. Run `playwright install chromium` once."
                ) from exc
            raise BrowserError(f"Could not launch {kind}: {exc}") from exc

    # storage_state can only be applied when creating a context. If a context
    # already exists (and state was requested), close it so a fresh one is made.
    if storage_state is not None and _session.context is not None:
        try:
            await _session.context.close()
        except PlaywrightError:
            pass
        _session.context = None
        _session.page = None

    # Create context if missing, optionally seeded with storage_state / HAR recording.
    if _session.context is None:
        ctx_kwargs: dict[str, Any] = {}
        if storage_state is not None:
            ctx_kwargs["storage_state"] = storage_state
        # A fresh context resets any prior HAR recording state.
        _session.har_path = None
        if record_har:
            fd, tmp = tempfile.mkstemp(suffix=".har", prefix="domvault_")
            os.close(fd)
            _session.har_path = tmp
            ctx_kwargs["record_har_path"] = tmp
        try:
            _session.context = await _session.browser.new_context(**ctx_kwargs)
        except PlaywrightError as exc:
            if _session.har_path and os.path.exists(_session.har_path):
                try: os.remove(_session.har_path)
                except OSError: pass
            _session.har_path = None
            raise BrowserError(f"Could not create browser context: {exc}") from exc
        # Fresh context -> fresh capture. Attach network listeners now, before
        # any navigation, so we don't miss the first requests.
        _collector.reset()
        _collector.attach_context(_session.context)

    # Create page if missing (or closed by the user).
    if _session.page is None or _session.page.is_closed():
        _session.page = await _session.context.new_page()
        _session.page.on("close", _on_page_closed)
        _collector.attach_page(_session.page)


def _on_page_closed() -> None:
    """Called (sync) when the user closes the browser window manually."""
    # Don't tear down synchronously here; mark the page closed so the next
    # request sees a clean state. _ensure_started will rebuild on next open.
    _session.page = None


async def _hard_stop() -> None:
    """Close browser + playwright context unconditionally.

    Closing the context first flushes any in-progress HAR recording to disk.
    ``har_path`` is intentionally NOT cleared here so :func:`close` can still
    read it; it is reset when a new context is created in :func:`_ensure_started`.
    """
    if _session.context is not None:
        try:
            await _session.context.close()
        except PlaywrightError:
            pass
    if _session.browser is not None:
        try:
            await _session.browser.close()
        except PlaywrightError:
            pass
    if _session.pw is not None:
        try:
            await _session.pw.stop()
        except PlaywrightError:
            pass
    _session.browser = None
    _session.context = None
    _session.page = None
    _session.pw = None


async def open_url(
    url: str,
    kind: BrowserKind = "chromium",
    storage_state: dict | list | str | None = None,
    record_har: bool = False,
    headless: bool = False,
    wait_until: str = "domcontentloaded",
    timeout: float = 30000,
) -> dict:
    """Open (or navigate) the browser to ``url``.

    If no browser is running, one is started (headed unless ``headless``).
    When ``storage_state`` is given (a dict from ``context.storage_state()``),
    the context is created with that state so cookies/localStorage are
    restored. When ``record_har`` is True and a new context is created, the
    session's network is recorded to a temp HAR file (finalized on
    :func:`close`). ``wait_until`` and ``timeout`` (milliseconds) are passed to
    ``page.goto``. Returns a status dict.
    """
    await _ensure_started(
        kind, storage_state=storage_state, record_har=record_har, headless=headless
    )
    page = _session.page
    assert page is not None  # _ensure_started guarantees this
    try:
        await page.goto(url, wait_until=wait_until, timeout=timeout)
    except PlaywrightError as exc:
        raise BrowserError(f"Could not open {url}: {exc}") from exc
    return await status()


async def status() -> dict:
    """Return a read-only snapshot of the current session."""
    if not _session.open or _session.page is None:
        return {"open": False, "url": None, "title": None}
    page = _session.page
    try:
        url = page.url
    except PlaywrightError:
        url = None
    try:
        title = await page.title()
    except PlaywrightError:
        title = None
    return {"open": True, "url": url, "title": title}


async def current_html() -> str:
    """Return ``page.content()`` — the current rendered DOM HTML.

    Raises :class:`BrowserError` if no page is open.
    """
    if not _session.open or _session.page is None:
        raise BrowserError("No browser session is open. Open a URL first.")
    try:
        return await _session.page.content()
    except PlaywrightError as exc:
        raise BrowserError(f"Could not read page content: {exc}") from exc


async def current_url() -> str:
    """Return the page's current URL (may differ from the one originally opened)."""
    if not _session.open or _session.page is None:
        raise BrowserError("No browser session is open. Open a URL first.")
    return _session.page.url


async def current_title() -> str:
    """Return the page's current title."""
    if not _session.open or _session.page is None:
        raise BrowserError("No browser session is open. Open a URL first.")
    try:
        return await _session.page.title()
    except PlaywrightError as exc:
        raise BrowserError(f"Could not read page title: {exc}") from exc


async def current_screenshot() -> bytes:
    """Return a full-page PNG screenshot of the current page."""
    if not _session.open or _session.page is None:
        raise BrowserError("No browser session is open. Open a URL first.")
    try:
        return await _session.page.screenshot(full_page=True)
    except PlaywrightError as exc:
        raise BrowserError(f"Could not capture screenshot: {exc}") from exc


async def current_storage_state() -> dict:
    """Return the context storage state (cookies + localStorage/sessionStorage)."""
    if _session.context is None:
        raise BrowserError("No browser session is open. Open a URL first.")
    try:
        return await _session.context.storage_state()
    except PlaywrightError as exc:
        raise BrowserError(f"Could not read storage state: {exc}") from exc


def get_collector() -> Collector:
    """Return the shared network/console collector for the current context."""
    return _collector


async def list_frames() -> list[dict]:
    """Return metadata for every frame on the current page (main + iframes)."""
    if not _session.open or _session.page is None:
        raise BrowserError("No browser session is open. Open a URL first.")
    page = _session.page
    out = []
    for idx, fr in enumerate(page.frames):
        out.append({
            "index": idx,
            "name": fr.name,
            "url": fr.url,
            "is_main": fr == page.main_frame,
        })
    return out


async def frame_contents() -> list[dict]:
    """Return the rendered HTML of every frame (main + iframes).

    Cross-origin frames are accessible because Playwright drives the browser.
    A frame whose HTML cannot be read (e.g. detached) yields ``html: None``.
    """
    if not _session.open or _session.page is None:
        raise BrowserError("No browser session is open. Open a URL first.")
    page = _session.page
    out = []
    for idx, fr in enumerate(page.frames):
        html: str | None = None
        try:
            html = await fr.content()
        except PlaywrightError:
            html = None
        out.append({
            "index": idx,
            "name": fr.name,
            "url": fr.url,
            "is_main": fr == page.main_frame,
            "html": html,
        })
    return out


async def close() -> Optional[str]:
    """Close the browser and release Playwright. The server keeps running.

    Returns the temp HAR file path if a HAR was being recorded (the file has
    been finalized by the context close), else None. The caller owns moving/
    deleting that file.
    """
    har = _session.har_path
    await _hard_stop()
    return har


# --- selector testing + highlighting (main frame) ------------------------

_HIGHLIGHT_JS = """
({sel, kind, color}) => {
  const CLEAR = () => document.querySelectorAll('.__domvault_hl__').forEach(e => {
    e.classList.remove('__domvault_hl__');
    e.style.outline = ''; e.style.outlineOffset = '';
  });
  CLEAR();
  let arr = [];
  try {
    if (kind === 'xpath') {
      const r = document.evaluate(sel, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
      for (let i = 0; i < r.snapshotLength; i++) {
        const n = r.snapshotItem(i);
        if (n && n.nodeType === 1) arr.push(n);
      }
    } else {
      arr = Array.from(document.querySelectorAll(sel));
    }
  } catch (e) {
    return {error: String(e), count: 0};
  }
  arr.forEach(e => {
    e.classList.add('__domvault_hl__');
    e.style.outline = '3px solid ' + color;
    e.style.outlineOffset = '1px';
  });
  return {count: arr.length};
}
"""

_CLEAR_HIGHLIGHT_JS = """
() => {
  document.querySelectorAll('.__domvault_hl__').forEach(e => {
    e.classList.remove('__domvault_hl__');
    e.style.outline = ''; e.style.outlineOffset = '';
  });
}
"""


async def test_selector(
    selector: str,
    kind: SelectorKind = "css",
    limit: int = 10,
) -> dict[str, Any]:
    """Return match count + up to ``limit`` element samples for a selector.

    Operates on the main frame. Each sample has tag/id/cls/text. Raises
    :class:`BrowserError` for an invalid selector or no open session.
    """
    if not _session.open or _session.page is None:
        raise BrowserError("No browser session is open. Open a URL first.")
    page = _session.page
    target = f"xpath={selector}" if kind == "xpath" else selector
    try:
        loc = page.locator(target)
        count = await loc.count()
    except PlaywrightError as exc:
        raise BrowserError(f"Invalid selector: {exc}") from exc
    samples: list[dict[str, Any]] = []
    for i in range(min(count, max(0, limit))):
        try:
            info = await loc.nth(i).evaluate(
                "el => ({tag: el.tagName.toLowerCase(), id: el.id || null, "
                "cls: el.className && el.className.toString ? el.className.toString() : null, "
                "text: (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').slice(0, 160)})"
            )
            samples.append(info)
        except PlaywrightError:
            samples.append({"tag": None, "text": None})
    return {"kind": kind, "selector": selector, "count": count, "samples": samples}


async def highlight(
    selector: str,
    kind: SelectorKind = "css",
    color: str = "#ff5252",
) -> dict[str, Any]:
    """Outline matched elements in the live browser (main frame).

    Returns ``{"count": N}`` or ``{"error": "...", "count": 0}`` for a bad
    selector. Previous highlights are cleared first.
    """
    if not _session.open or _session.page is None:
        raise BrowserError("No browser session is open. Open a URL first.")
    try:
        return await _session.page.evaluate(
            _HIGHLIGHT_JS, {"sel": selector, "kind": kind, "color": color}
        )
    except PlaywrightError as exc:
        raise BrowserError(f"Highlight failed: {exc}") from exc


async def clear_highlight() -> None:
    """Remove all DOMVault highlight outlines from the main frame."""
    if not _session.open or _session.page is None:
        raise BrowserError("No browser session is open. Open a URL first.")
    try:
        await _session.page.evaluate(_CLEAR_HIGHLIGHT_JS)
    except PlaywrightError as exc:
        raise BrowserError(f"Clear highlight failed: {exc}") from exc
