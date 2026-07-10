"""Snapshot saving: URL normalization, directory naming, and artifact writing.

Pure module (no Playwright dependency) so it can be unit-tested in isolation.
The actual ``page.content()`` / screenshot / storage-state calls happen in
``browser.py`` / ``server.py``; this module handles strings and the filesystem.

V0.2 layout — each save produces an independent directory::

    saved_html/
      example.com_20260709_213000/
        page.html
        screenshot.png
        storage_state.json
        metadata.json
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

TOOL = "DOMVault"
VERSION = "1.0.0"


class InvalidURL(ValueError):
    """Raised when a URL cannot be normalized to a valid http(s) URL."""


# --- URL handling --------------------------------------------------------

def normalize_url(raw: str) -> str:
    """Return a usable absolute URL.

    - Strips surrounding whitespace.
    - Prepends ``https://`` if no scheme is present.
    - Accepts only ``http`` and ``https`` schemes.
    - Requires a non-empty host.
    """
    if raw is None:
        raise InvalidURL("URL is required.")
    text = raw.strip()
    if not text:
        raise InvalidURL("URL is required.")

    has_scheme = "://" in text or text.lower().startswith(("http://", "https://"))
    if not has_scheme:
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:", text):
            raise InvalidURL(f"Only http/https URLs are supported: {text!r}")
        candidate = "https://" + text
    else:
        candidate = text

    parsed = urlparse(candidate)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise InvalidURL(f"Only http/https URLs are supported: {text!r}")
    if not parsed.netloc:
        raise InvalidURL(f"Could not determine a host from URL: {text!r}")
    return candidate


def domain_slug(url: str) -> str:
    """Filesystem-safe slug from the URL's host.

    ``https://example.com/path`` -> ``example.com``
    ``https://Example.COM:8443`` -> ``example.com-8443``
    """
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    host_no_port = host.split(":", 1)[0]
    port = parsed.port
    if not host_no_port:
        return "unknown"
    slug = re.sub(r"[^a-z0-9.\-]", "-", host_no_port)
    slug = re.sub(r"-+", "-", slug).strip("-.")
    if not slug:
        slug = "unknown"
    if port is not None and port not in (80, 443):
        slug = f"{slug}-{port}"
    return slug


# --- naming --------------------------------------------------------------

def timestamp(when: Optional[datetime.datetime] = None) -> str:
    """``YYYYMMDD_HHMMSS`` in local time, suitable for directory names."""
    return (when or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")


def sanitize_custom_name(name: str) -> str:
    """Sanitize a user-supplied name into a safe directory name.

    Keeps ``[A-Za-z0-9._-]``; collapses other characters to ``_``; trims
    leading/trailing ``._-``; caps length at 80. Returns ``""`` if empty.
    """
    if not name:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", name.strip())
    cleaned = re.sub(r"[_]+", "_", cleaned).strip("._-")
    return cleaned[:80]


def run_directory_name(
    url: str,
    *,
    custom_name: Optional[str] = None,
    when: Optional[datetime.datetime] = None,
) -> str:
    """Return the directory name for a snapshot.

    With ``custom_name``: the sanitized name. Otherwise ``<domain>_<timestamp>``.
    """
    custom = sanitize_custom_name(custom_name) if custom_name else ""
    if custom:
        return custom
    return f"{domain_slug(url)}_{timestamp(when)}"


def resolve_unique_run_dir(base_out: Path, name: str) -> Path:
    """Return a non-colliding directory path inside ``base_out``.

    If ``base_out/name`` already exists, append ``_2``, ``_3``, ...
    """
    base_out.mkdir(parents=True, exist_ok=True)
    candidate = base_out / name
    counter = 2
    while candidate.exists():
        candidate = base_out / f"{name}_{counter}"
        counter += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


# --- frame / network / console artifact helpers --------------------------

def _frame_slug(name: str, url: str) -> str:
    """Filesystem-safe slug for a frame, preferring its name then its domain."""
    src = (name or "").strip()
    if not src and url:
        src = domain_slug(url)
    if not src:
        src = "frame"
    slug = re.sub(r"[^A-Za-z0-9._-]", "_", src)
    slug = re.sub(r"_+", "_", slug).strip("._-")
    return slug[:40] or "frame"


def write_frames(run_dir: Path, frames: Optional[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Write ``frames.json`` and one HTML file per non-main frame.

    The main frame's HTML is ``page.html`` (written by the caller), so only
    iframe HTML is written under ``frames/``. Returns the frame index list
    stored in ``frames.json``.
    """
    index: list[dict[str, Any]] = []
    frames_dir = run_dir / "frames"
    for fr in frames or []:
        entry = {
            "index": fr.get("index"),
            "name": fr.get("name", "") or "",
            "url": fr.get("url", "") or "",
            "is_main": bool(fr.get("is_main")),
            "html_file": None,
        }
        html = fr.get("html")
        if not entry["is_main"] and html:
            frames_dir.mkdir(parents=True, exist_ok=True)
            fname = f"{entry['index']:03d}_{_frame_slug(entry['name'], entry['url'])}.html"
            (frames_dir / fname).write_text(html, encoding="utf-8")
            entry["html_file"] = f"frames/{fname}"
        index.append(entry)
    (run_dir / "frames.json").write_text(
        json.dumps({"frames": index}, indent=2, default=str), encoding="utf-8"
    )
    return index


def write_network_jsonl(run_dir: Path, events: Optional[list[dict[str, Any]]]) -> int:
    """Write ``network.jsonl`` (one JSON object per line). Returns count written."""
    lines: list[str] = []
    for ev in events or []:
        try:
            lines.append(json.dumps(ev, default=str))
        except (TypeError, ValueError):
            continue
    (run_dir / "network.jsonl").write_text(
        ("\n".join(lines) + "\n") if lines else "", encoding="utf-8"
    )
    return len(lines)


def write_console_log(run_dir: Path, events: Optional[list[dict[str, Any]]]) -> int:
    """Write ``console.log`` as human-readable ``[ts] [LEVEL] text`` lines."""
    lines: list[str] = []
    for ev in events or []:
        ts = ev.get("ts", "")
        level = str(ev.get("level", "log")).upper()
        text = ev.get("text", "")
        lines.append(f"[{ts}] [{level}] {text}")
    (run_dir / "console.log").write_text(
        ("\n".join(lines) + "\n") if lines else "", encoding="utf-8"
    )
    return len(lines)


# --- metadata ------------------------------------------------------------

def build_metadata(
    *,
    url: str,
    title: Optional[str],
    run_name: str,
    when: Optional[datetime.datetime] = None,
    has_screenshot: bool = False,
    has_storage_state: bool = False,
    frame_count: int = 0,
    network_count: int = 0,
    console_count: int = 0,
) -> dict[str, Any]:
    """Build the ``metadata.json`` content for a snapshot."""
    return {
        "tool": TOOL,
        "version": VERSION,
        "url": url,
        "title": title,
        "saved_at": (when or datetime.datetime.now()).isoformat(timespec="seconds"),
        "run_dir": run_name,
        "html_file": "page.html",
        "screenshot_file": "screenshot.png" if has_screenshot else None,
        "storage_state_file": "storage_state.json" if has_storage_state else None,
        "frames_file": "frames.json" if frame_count else None,
        "frame_count": frame_count,
        "network_file": "network.jsonl" if network_count else None,
        "network_event_count": network_count,
        "console_file": "console.log" if console_count else None,
        "console_event_count": console_count,
    }


# --- snapshot writing ----------------------------------------------------

def save_snapshot(
    html: str,
    *,
    url: str,
    title: Optional[str],
    out_dir: Path,
    screenshot_png: Optional[bytes] = None,
    storage_state: Optional[dict[str, Any]] = None,
    frames: Optional[list[dict[str, Any]]] = None,
    network_events: Optional[list[dict[str, Any]]] = None,
    console_events: Optional[list[dict[str, Any]]] = None,
    custom_name: Optional[str] = None,
    when: Optional[datetime.datetime] = None,
) -> tuple[Path, dict[str, Any]]:
    """Write a snapshot directory with page.html (+ optional artifacts).

    Always writes ``page.html``, ``metadata.json``. Optionally writes
    ``screenshot.png``, ``storage_state.json``, ``frames.json`` (+ per-iframe
    HTML under ``frames/``), ``network.jsonl``, and ``console.log``.
    Returns ``(run_dir_path, metadata_dict)``.

    Collisions on the resolved directory name are de-duplicated via ``_2``,
    ``_3`` suffixes.
    """
    if html is None:
        raise ValueError("Cannot save snapshot: page HTML was None.")

    when = when or datetime.datetime.now()
    name = run_directory_name(url, custom_name=custom_name, when=when)
    run_dir = resolve_unique_run_dir(out_dir, name)

    (run_dir / "page.html").write_text(html, encoding="utf-8")
    if screenshot_png is not None:
        (run_dir / "screenshot.png").write_bytes(screenshot_png)
    if storage_state is not None:
        (run_dir / "storage_state.json").write_text(
            json.dumps(storage_state, indent=2, default=str), encoding="utf-8"
        )
    frame_index = write_frames(run_dir, frames) if frames else []
    net_count = write_network_jsonl(run_dir, network_events) if network_events else 0
    cons_count = write_console_log(run_dir, console_events) if console_events else 0

    metadata = build_metadata(
        url=url,
        title=title,
        run_name=run_dir.name,
        when=when,
        has_screenshot=screenshot_png is not None,
        has_storage_state=storage_state is not None,
        frame_count=len(frame_index),
        network_count=net_count,
        console_count=cons_count,
    )
    metadata["frames"] = frame_index  # inline the frame index for convenience
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, default=str), encoding="utf-8"
    )
    return run_dir, metadata
