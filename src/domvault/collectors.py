"""Network + console event collectors for DOMVault.

A :class:`Collector` is attached to a Playwright ``BrowserContext`` (for
request/response events) and to each ``Page`` (for console/pageerror events).
Events accumulate in bounded lists; the server reads them at save time to
write ``network.jsonl`` and ``console.log``.

Every handler is wrapped so a single malformed Playwright event can never
break event dispatch.
"""

from __future__ import annotations

import datetime
from typing import Any

_MAX_EVENTS = 20000


class Collector:
    """Bounded in-memory buffer of network and console events."""

    def __init__(self, max_events: int = _MAX_EVENTS) -> None:
        self.network: list[dict[str, Any]] = []
        self.console: list[dict[str, Any]] = []
        self._max = max_events

    def reset(self) -> None:
        self.network.clear()
        self.console.clear()

    def counts(self) -> dict[str, int]:
        return {"network": len(self.network), "console": len(self.console)}

    # --- attachment -----------------------------------------------------

    def attach_context(self, context: Any) -> None:
        context.on("request", self._on_request)
        context.on("response", self._on_response)

    def attach_page(self, page: Any) -> None:
        page.on("console", self._on_console)
        page.on("pageerror", self._on_pageerror)

    # --- internals ------------------------------------------------------

    def _push(self, target: list[dict[str, Any]], item: dict[str, Any]) -> None:
        if len(target) >= self._max:
            target.pop(0)  # ring-buffer style: drop oldest when full
        target.append(item)

    @staticmethod
    def _now() -> str:
        return datetime.datetime.now().isoformat(timespec="milliseconds")

    def _on_request(self, req: Any) -> None:
        try:
            self._push(self.network, {
                "kind": "request",
                "ts": self._now(),
                "method": req.method,
                "url": req.url,
                "resource_type": req.resource_type,
            })
        except Exception:
            pass

    def _on_response(self, resp: Any) -> None:
        try:
            req = resp.request
            self._push(self.network, {
                "kind": "response",
                "ts": self._now(),
                "method": req.method,
                "url": resp.url,
                "status": resp.status,
                "status_text": resp.status_text,
                "resource_type": req.resource_type,
            })
        except Exception:
            pass

    def _on_console(self, msg: Any) -> None:
        try:
            self._push(self.console, {
                "ts": self._now(),
                "level": msg.type,
                "text": msg.text,
            })
        except Exception:
            pass

    def _on_pageerror(self, err: Any) -> None:
        try:
            self._push(self.console, {
                "ts": self._now(),
                "level": "error",
                "text": str(err),
            })
        except Exception:
            pass


def format_console_line(event: dict[str, Any]) -> str:
    """Render one console event as a human-readable log line."""
    ts = event.get("ts", "")
    level = (event.get("level") or "log").upper()
    text = event.get("text", "")
    return f"[{ts}] [{level}] {text}"
