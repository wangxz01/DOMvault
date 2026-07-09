"""Unit tests for saver.py — URL normalization, naming, and file writing.

These tests need only the standard library; they do not launch a browser.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from domvault.saver import (
    InvalidURL,
    build_filename,
    domain_slug,
    normalize_url,
    resolve_unique_path,
    save_html,
)


# --- normalize_url --------------------------------------------------------

class TestNormalizeURL:
    def test_adds_https_scheme(self):
        assert normalize_url("example.com") == "https://example.com"

    def test_keeps_http(self):
        assert normalize_url("http://example.com") == "http://example.com"

    def test_keeps_https(self):
        assert normalize_url("https://example.com/path") == "https://example.com/path"

    def test_strips_whitespace(self):
        assert normalize_url("   example.com   ") == "https://example.com"

    def test_preserves_path_and_query(self):
        assert normalize_url("example.com/search?q=test") == "https://example.com/search?q=test"

    def test_rejects_empty(self):
        with pytest.raises(InvalidURL):
            normalize_url("")
        with pytest.raises(InvalidURL):
            normalize_url("   ")

    def test_rejects_none(self):
        with pytest.raises(InvalidURL):
            normalize_url(None)  # type: ignore[arg-type]

    def test_rejects_non_http_scheme(self):
        with pytest.raises(InvalidURL):
            normalize_url("file:///etc/passwd")
        with pytest.raises(InvalidURL):
            normalize_url("javascript:alert(1)")

    def test_rejects_no_host(self):
        with pytest.raises(InvalidURL):
            normalize_url("https:///path-only")


# --- domain_slug ----------------------------------------------------------

class TestDomainSlug:
    def test_simple_domain(self):
        assert domain_slug("https://example.com/path") == "example.com"

    def test_lowercase(self):
        assert domain_slug("https://Example.COM") == "example.com"

    def test_subdomain(self):
        assert domain_slug("https://www.example.co.uk") == "www.example.co.uk"

    def test_non_default_port(self):
        assert domain_slug("https://example.com:8443") == "example.com-8443"

    def test_default_port_dropped(self):
        assert domain_slug("https://example.com:443") == "example.com"
        assert domain_slug("http://example.com:80") == "example.com"

    def test_strips_userinfo(self):
        assert domain_slug("https://user:pass@example.com") == "example.com"

    def test_unknown_host_fallback(self):
        # No netloc -> urlparse still returns what it can; saver falls back.
        assert domain_slug("about:blank") == "unknown"


# --- build_filename -------------------------------------------------------

class TestBuildFilename:
    def test_basic_shape(self):
        name = build_filename("https://example.com", when=datetime.datetime(2026, 7, 9, 21, 30, 0))
        assert name == "example.com_20260709_213000.html"

    def test_uses_domain_slug(self):
        name = build_filename("https://Example.COM:8443/x", when=datetime.datetime(2026, 1, 1, 0, 0, 0))
        assert name == "example.com-8443_20260101_000000.html"

    def test_extension_is_html(self):
        name = build_filename("https://example.com")
        assert name.endswith(".html")


# --- resolve_unique_path --------------------------------------------------

class TestResolveUniquePath:
    def test_creates_directory(self, tmp_path: Path):
        out = tmp_path / "saved_html"
        path = resolve_unique_path(out, "example.com_20260709_213000.html")
        assert out.exists()
        assert path.parent == out
        assert path.name == "example.com_20260709_213000.html"

    def test_collision_gets_suffix(self, tmp_path: Path):
        first = resolve_unique_path(tmp_path, "x.html")
        first.write_text("a", encoding="utf-8")
        second = resolve_unique_path(tmp_path, "x.html")
        assert second.name == "x_2.html"

    def test_collision_increments(self, tmp_path: Path):
        for expected in ("x.html", "x_2.html", "x_3.html"):
            p = resolve_unique_path(tmp_path, "x.html")
            assert p.name == expected
            p.write_text("a", encoding="utf-8")


# --- save_html ------------------------------------------------------------

class TestSaveHTML:
    def test_writes_file_and_returns_path(self, tmp_path: Path):
        path = save_html("<html></html>", "https://example.com", tmp_path,
                         when=datetime.datetime(2026, 7, 9, 21, 30, 0))
        assert path.exists()
        assert path.name == "example.com_20260709_213000.html"
        assert path.read_text(encoding="utf-8") == "<html></html>"

    def test_creates_output_dir(self, tmp_path: Path):
        out = tmp_path / "nested" / "saved_html"
        path = save_html("<p>hi</p>", "https://example.com", out)
        assert path.exists()
        assert out.exists()

    def test_repeated_saves_dont_overwrite(self, tmp_path: Path):
        when = datetime.datetime(2026, 7, 9, 21, 30, 0)
        p1 = save_html("<a/>", "https://example.com", tmp_path, when=when)
        p2 = save_html("<b/>", "https://example.com", tmp_path, when=when)
        p3 = save_html("<c/>", "https://example.com", tmp_path, when=when)
        names = sorted({p1.name, p2.name, p3.name})
        assert len(names) == 3
        assert all(path.exists() for path in (p1, p2, p3))
        # Original content preserved.
        assert p1.read_text(encoding="utf-8") == "<a/>"

    def test_rejects_none_html(self, tmp_path: Path):
        with pytest.raises(ValueError):
            save_html(None, "https://example.com", tmp_path)  # type: ignore[arg-type]
