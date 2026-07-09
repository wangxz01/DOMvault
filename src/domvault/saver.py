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
VERSION = "0.2.0"


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


# --- metadata ------------------------------------------------------------

def build_metadata(
    *,
    url: str,
    title: Optional[str],
    run_name: str,
    when: Optional[datetime.datetime] = None,
    has_screenshot: bool = False,
    has_storage_state: bool = False,
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
    custom_name: Optional[str] = None,
    when: Optional[datetime.datetime] = None,
) -> tuple[Path, dict[str, Any]]:
    """Write a snapshot directory with page.html (+ optional artifacts).

    Always writes ``page.html`` and ``metadata.json``. Writes
    ``screenshot.png`` and ``storage_state.json`` only when the corresponding
    argument is provided. Returns ``(run_dir_path, metadata_dict)``.

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

    metadata = build_metadata(
        url=url,
        title=title,
        run_name=run_dir.name,
        when=when,
        has_screenshot=screenshot_png is not None,
        has_storage_state=storage_state is not None,
    )
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, default=str), encoding="utf-8"
    )
    return run_dir, metadata
