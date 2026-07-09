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

from dataclasses import dataclass
from typing import Literal, Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Page,
    async_playwright,
)

BrowserKind = Literal["chromium", "firefox", "webkit"]

# A module-level holder keeps everything on the single asyncio event loop that
# uvicorn runs. We never touch Playwright from another thread.
@dataclass
class _Session:
    pw: object = None              # Playwright instance from async_playwright().start(); stop via .stop()
    browser: Optional[Browser] = None
    context: Optional[BrowserContext] = None
    page: Optional[Page] = None
    kind: BrowserKind = "chromium"

    @property
    def open(self) -> bool:
        return self.page is not None and not self.page.is_closed()


_session = _Session()


class BrowserError(RuntimeError):
    """User-facing browser error (bad URL, navigation failure, closed browser)."""


async def _ensure_started(kind: BrowserKind) -> None:
    """Start playwright + a browser + context + page if not already running.

    Reuses an already-alive browser/context when possible (e.g. after the user
    closed only the page/window), and only does a full restart when the browser
    process itself is gone. This avoids leaking Playwright instances.
    """
    if _session.page is not None and not _session.page.is_closed():
        return  # fast path: session already healthy

    # Browser still connected but page was closed -> reuse context, new page.
    if (
        _session.browser is not None
        and _session.browser.is_connected()
        and _session.context is not None
    ):
        try:
            _session.page = await _session.context.new_page()
            _session.page.on("close", _on_page_closed)
            return
        except PlaywrightError:
            # Context went away; fall through to a full restart.
            await _hard_stop()

    # Full (re)start. Tear down any stale state first to avoid leaks.
    await _hard_stop()
    try:
        pw = await async_playwright().start()
    except PlaywrightError as exc:  # pragma: no cover - environment error
        raise BrowserError(f"Could not start Playwright: {exc}") from exc
    _session.pw = pw
    _session.kind = kind
    try:
        launcher = getattr(pw, kind)
        _session.browser = await launcher.launch(headless=False)
    except PlaywrightError as exc:
        # Common: browser binary not installed. Surface a clear message.
        await _hard_stop()
        if "executable doesn't exist" in str(exc) or "playwright install" in str(exc).lower():
            raise BrowserError(
                "Playwright browser binary not found. Run `playwright install chromium` once."
            ) from exc
        raise BrowserError(f"Could not launch {kind}: {exc}") from exc
    _session.context = await _session.browser.new_context()
    # Surface unexpected page-close events via status rather than crashes.
    _session.page = await _session.context.new_page()
    _session.page.on("close", _on_page_closed)


def _on_page_closed() -> None:
    """Called (sync) when the user closes the browser window manually."""
    # Don't tear down synchronously here; mark the page closed so the next
    # request sees a clean state. _ensure_started will rebuild on next open.
    _session.page = None


async def _hard_stop() -> None:
    """Close browser + playwright context unconditionally."""
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


async def open_url(url: str, kind: BrowserKind = "chromium") -> dict:
    """Open (or navigate) the browser to ``url``.

    If no browser is running, one is started headed. Returns a status dict.
    Raises :class:`BrowserError` on navigation failure or missing binary.
    """
    await _ensure_started(kind)
    page = _session.page
    assert page is not None  # _ensure_started guarantees this
    try:
        await page.goto(url, wait_until="domcontentloaded")
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


async def close() -> None:
    """Close the browser and release Playwright. The server keeps running."""
    await _hard_stop()
