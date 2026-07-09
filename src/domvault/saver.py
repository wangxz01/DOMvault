"""HTML saving logic: URL normalization, filename generation, and file writing.

This module is pure (no Playwright dependency) so it can be unit-tested in
isolation. The actual ``page.content()`` call happens in ``browser.py`` /
``server.py``; this module only handles the string and the filesystem.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from urllib.parse import urlparse


class InvalidURL(ValueError):
    """Raised when a URL cannot be normalized to a valid http(s) URL."""


def normalize_url(raw: str) -> str:
    """Return a usable absolute URL.

    - Strips surrounding whitespace.
    - Prepends ``https://`` if no scheme is present.
    - Accepts only ``http`` and ``https`` schemes.
    - Requires a non-empty host.

    Raises :class:`InvalidURL` otherwise.
    """
    if raw is None:
        raise InvalidURL("URL is required.")
    text = raw.strip()
    if not text:
        raise InvalidURL("URL is required.")

    has_scheme = "://" in text or text.lower().startswith(("http://", "https://"))
    if not has_scheme:
        # Reject anything that looks like a local path or scheme.
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:", text):
            # e.g. "file://..." or "javascript:..." without an explicit http(s)
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

    # urlparse already lower-cases the scheme; candidate is valid as-is.
    return candidate


def domain_slug(url: str) -> str:
    """Return a filesystem-safe slug derived from the URL's host.

    ``https://example.com/path`` -> ``example.com``
    ``https://Example.COM:8443`` -> ``example.com-8443``
    ``https://www.example.co.uk`` -> ``www.example.co.uk``

    Falls back to ``unknown`` if no host can be determined.
    """
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    # Strip userinfo if present (user:pass@host).
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    # Split port from host. urlparse keeps the port in netloc.
    host_no_port = host.split(":", 1)[0]
    port = parsed.port  # int or None
    if not host_no_port:
        return "unknown"
    # Replace any character that is hostile to filesystems / shells.
    slug = re.sub(r"[^a-z0-9.\-]", "-", host_no_port)
    slug = re.sub(r"-+", "-", slug).strip("-.")
    if not slug:
        slug = "unknown"
    if port is not None and port not in (80, 443):
        slug = f"{slug}-{port}"
    return slug


def timestamp() -> str:
    """Return a local-time timestamp suitable for filenames: ``YYYYMMDD_HHMMSS``."""
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def build_filename(url: str, when: datetime.datetime | None = None) -> str:
    """Return ``<domain>_<YYYYMMDD_HHMMSS>.html`` for the given URL."""
    ts = (when or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"{domain_slug(url)}_{ts}.html"


def resolve_unique_path(directory: Path, filename: str) -> Path:
    """Return a non-colliding path inside ``directory``.

    If ``directory/<filename>`` already exists, append ``_2``, ``_3``, ...
    before the extension until a free name is found.
    """
    directory.mkdir(parents=True, exist_ok=True)
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    candidate = directory / filename
    counter = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def save_html(
    html: str,
    url: str,
    out_dir: Path,
    *,
    when: datetime.datetime | None = None,
) -> Path:
    """Write ``html`` to ``out_dir/<domain>_<timestamp>.html`` and return the path.

    The output directory is created if it does not exist. Collisions on the
    same second are de-duplicated via ``_2``, ``_3`` suffixes.
    """
    if html is None:
        raise ValueError("Cannot save empty HTML: page content was None.")
    filename = build_filename(url, when=when)
    path = resolve_unique_path(out_dir, filename)
    path.write_text(html, encoding="utf-8")
    return path
