"""Unit tests for saver.py — URL normalization, naming, and snapshot writing.

Standard library only; no browser is launched.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from domvault.saver import (
    InvalidURL,
    build_metadata,
    domain_slug,
    normalize_url,
    resolve_unique_run_dir,
    run_directory_name,
    sanitize_custom_name,
    save_snapshot,
    timestamp,
    write_console_log,
    write_frames,
    write_network_jsonl,
)


# --- normalize_url -------------------------------------------------------

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


# --- domain_slug ---------------------------------------------------------

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
        assert domain_slug("about:blank") == "unknown"


# --- timestamp + sanitize_custom_name ------------------------------------

class TestTimestamp:
    def test_format(self):
        assert timestamp(datetime.datetime(2026, 7, 9, 21, 30, 0)) == "20260709_213000"


class TestSanitizeCustomName:
    def test_passthrough_safe(self):
        assert sanitize_custom_name("my-snapshot.1") == "my-snapshot.1"

    def test_replaces_unsafe(self):
        assert sanitize_custom_name("hello world/foo") == "hello_world_foo"

    def test_collapses_underscores(self):
        assert sanitize_custom_name("a   b???c") == "a_b_c"

    def test_trims_leading_trailing(self):
        assert sanitize_custom_name("...name___") == "name"

    def test_empty_or_whitespace(self):
        assert sanitize_custom_name("") == ""
        assert sanitize_custom_name("   ") == ""

    def test_caps_length(self):
        assert len(sanitize_custom_name("x" * 200)) == 80


# --- run_directory_name --------------------------------------------------

class TestRunDirectoryName:
    def test_default_uses_domain_and_timestamp(self):
        name = run_directory_name(
            "https://example.com",
            when=datetime.datetime(2026, 7, 9, 21, 30, 0),
        )
        assert name == "example.com_20260709_213000"

    def test_custom_name_used_when_provided(self):
        name = run_directory_name(
            "https://example.com",
            custom_name="login-state",
            when=datetime.datetime(2026, 7, 9, 21, 30, 0),
        )
        assert name == "login-state"

    def test_custom_name_sanitized(self):
        name = run_directory_name(
            "https://example.com",
            custom_name="My Snapshot!!",
        )
        assert name == "My_Snapshot"

    def test_empty_custom_falls_back_to_default(self):
        name = run_directory_name(
            "https://example.com",
            custom_name="   ",
            when=datetime.datetime(2026, 7, 9, 21, 30, 0),
        )
        assert name == "example.com_20260709_213000"


# --- resolve_unique_run_dir ----------------------------------------------

class TestResolveUniqueRunDir:
    def test_creates_base_and_dir(self, tmp_path: Path):
        base = tmp_path / "saved_html"
        d = resolve_unique_run_dir(base, "example.com_20260709_213000")
        assert base.exists()
        assert d.is_dir()
        assert d.name == "example.com_20260709_213000"

    def test_collision_gets_suffix(self, tmp_path: Path):
        first = resolve_unique_run_dir(tmp_path, "x")
        second = resolve_unique_run_dir(tmp_path, "x")
        assert first.name == "x"
        assert second.name == "x_2"

    def test_collision_increments(self, tmp_path: Path):
        names = [resolve_unique_run_dir(tmp_path, "x").name for _ in range(4)]
        assert names == ["x", "x_2", "x_3", "x_4"]


# --- build_metadata ------------------------------------------------------

class TestBuildMetadata:
    def test_minimal_no_artifacts(self):
        m = build_metadata(
            url="https://example.com",
            title="Example",
            run_name="example.com_20260709_213000",
            when=datetime.datetime(2026, 7, 9, 21, 30, 0),
        )
        assert m["html_file"] == "page.html"
        assert m["screenshot_file"] is None
        assert m["storage_state_file"] is None
        assert m["url"] == "https://example.com"
        assert m["title"] == "Example"
        assert m["saved_at"] == "2026-07-09T21:30:00"
        assert m["tool"] == "DOMVault"

    def test_with_artifacts(self):
        m = build_metadata(
            url="u", title="t", run_name="r",
            has_screenshot=True, has_storage_state=True,
        )
        assert m["screenshot_file"] == "screenshot.png"
        assert m["storage_state_file"] == "storage_state.json"


# --- save_snapshot -------------------------------------------------------

class TestSaveSnapshot:
    def test_writes_page_and_metadata_only(self, tmp_path: Path):
        run_dir, meta = save_snapshot(
            "<html></html>",
            url="https://example.com",
            title="Example",
            out_dir=tmp_path,
            when=datetime.datetime(2026, 7, 9, 21, 30, 0),
        )
        assert run_dir.name == "example.com_20260709_213000"
        assert (run_dir / "page.html").read_text(encoding="utf-8") == "<html></html>"
        assert (run_dir / "metadata.json").is_file()
        assert not (run_dir / "screenshot.png").exists()
        assert not (run_dir / "storage_state.json").exists()
        assert meta["html_file"] == "page.html"
        assert meta["screenshot_file"] is None

    def test_writes_all_artifacts(self, tmp_path: Path):
        run_dir, _ = save_snapshot(
            "<html></html>",
            url="https://example.com",
            title="Example",
            out_dir=tmp_path,
            screenshot_png=b"\x89PNG\r\n\x1a\n",
            storage_state={"cookies": [], "origins": []},
            when=datetime.datetime(2026, 7, 9, 21, 30, 0),
        )
        assert (run_dir / "page.html").is_file()
        assert (run_dir / "screenshot.png").read_bytes() == b"\x89PNG\r\n\x1a\n"
        state = json.loads((run_dir / "storage_state.json").read_text(encoding="utf-8"))
        assert state == {"cookies": [], "origins": []}

    def test_metadata_json_is_valid(self, tmp_path: Path):
        run_dir, _ = save_snapshot(
            "<html></html>",
            url="https://example.com/x?q=1",
            title="T",
            out_dir=tmp_path,
            when=datetime.datetime(2026, 7, 9, 21, 30, 0),
        )
        m = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
        assert m["url"] == "https://example.com/x?q=1"
        assert m["run_dir"] == run_dir.name

    def test_custom_name_used_for_dir(self, tmp_path: Path):
        run_dir, _ = save_snapshot(
            "<html></html>",
            url="https://example.com",
            title="Example",
            out_dir=tmp_path,
            custom_name="my-login",
        )
        assert run_dir.name == "my-login"

    def test_repeated_saves_dont_overwrite(self, tmp_path: Path):
        when = datetime.datetime(2026, 7, 9, 21, 30, 0)
        d1, _ = save_snapshot("<a/>", url="https://example.com", title="t", out_dir=tmp_path, when=when)
        d2, _ = save_snapshot("<b/>", url="https://example.com", title="t", out_dir=tmp_path, when=when)
        d3, _ = save_snapshot("<c/>", url="https://example.com", title="t", out_dir=tmp_path, when=when)
        names = sorted({d1.name, d2.name, d3.name})
        assert len(names) == 3
        assert (d1 / "page.html").read_text(encoding="utf-8") == "<a/>"

    def test_rejects_none_html(self, tmp_path: Path):
        with pytest.raises(ValueError):
            save_snapshot(
                None,  # type: ignore[arg-type]
                url="https://example.com", title="t", out_dir=tmp_path,
            )


# --- write_frames --------------------------------------------------------

class TestWriteFrames:
    def test_writes_frames_json_and_iframes(self, tmp_path: Path):
        frames = [
            {"index": 0, "name": "", "url": "https://example.com", "is_main": True, "html": "<main/>"},
            {"index": 1, "name": "ad", "url": "https://ads.example.com/x", "is_main": False, "html": "<iframe-ad/>"},
            {"index": 2, "name": "", "url": "https://other.example.org", "is_main": False, "html": "<other/>"},
        ]
        index = write_frames(tmp_path, frames)
        # frames.json lists all frames
        data = json.loads((tmp_path / "frames.json").read_text(encoding="utf-8"))
        assert len(data["frames"]) == 3
        # main frame has no separate html file
        assert index[0]["html_file"] is None
        assert index[0]["is_main"] is True
        # non-main frames written under frames/
        assert index[1]["html_file"] == "frames/001_ad.html"
        assert index[2]["html_file"].startswith("frames/002_")
        assert (tmp_path / "frames" / "001_ad.html").read_text(encoding="utf-8") == "<iframe-ad/>"

    def test_main_frame_html_not_written(self, tmp_path: Path):
        write_frames(tmp_path, [{"index": 0, "name": "", "url": "u", "is_main": True, "html": "<x/>"}])
        assert not (tmp_path / "frames").is_dir()  # no iframe files at all

    def test_empty_frames(self, tmp_path: Path):
        index = write_frames(tmp_path, [])
        assert index == []
        assert json.loads((tmp_path / "frames.json").read_text(encoding="utf-8")) == {"frames": []}


# --- write_network_jsonl -------------------------------------------------

class TestWriteNetworkJsonl:
    def test_writes_one_json_per_line(self, tmp_path: Path):
        events = [
            {"kind": "request", "url": "https://a", "method": "GET"},
            {"kind": "response", "url": "https://a", "status": 200},
        ]
        count = write_network_jsonl(tmp_path, events)
        assert count == 2
        lines = (tmp_path / "network.jsonl").read_text(encoding="utf-8").strip().split("\n")
        assert json.loads(lines[0])["kind"] == "request"
        assert json.loads(lines[1])["status"] == 200

    def test_skips_non_serializable(self, tmp_path: Path):
        count = write_network_jsonl(tmp_path, [{"ok": 1}, {"bad": object()}])  # object() not serializable by default? it is -> "{}"
        # default=str makes object() serializable, so both pass through
        assert count == 2

    def test_none_events(self, tmp_path: Path):
        assert write_network_jsonl(tmp_path, None) == 0
        assert (tmp_path / "network.jsonl").read_text(encoding="utf-8") == ""


# --- write_console_log ---------------------------------------------------

class TestWriteConsoleLog:
    def test_format(self, tmp_path: Path):
        events = [{"ts": "2026-07-10T00:00:00.000", "level": "error", "text": "boom"}]
        write_console_log(tmp_path, events)
        line = (tmp_path / "console.log").read_text(encoding="utf-8").strip()
        assert line == "[2026-07-10T00:00:00.000] [ERROR] boom"

    def test_none_events(self, tmp_path: Path):
        assert write_console_log(tmp_path, None) == 0


# --- save_snapshot with V0.3 artifacts -----------------------------------

class TestSaveSnapshotV03:
    def test_writes_frames_network_console(self, tmp_path: Path):
        run_dir, meta = save_snapshot(
            "<html><body><h1>main</h1></body></html>",
            url="https://example.com",
            title="Example",
            out_dir=tmp_path,
            frames=[
                {"index": 0, "name": "", "url": "https://example.com", "is_main": True, "html": "<html><body><h1>main</h1></body></html>"},
                {"index": 1, "name": "widget", "url": "https://widget.example.com", "is_main": False, "html": "<p>iframe content</p>"},
            ],
            network_events=[{"kind": "request", "url": "https://example.com", "method": "GET"}],
            console_events=[{"ts": "2026-07-10T00:00:00", "level": "log", "text": "hi"}],
            when=datetime.datetime(2026, 7, 9, 21, 30, 0),
        )
        assert (run_dir / "frames.json").is_file()
        assert (run_dir / "frames" / "001_widget.html").is_file()
        assert (run_dir / "network.jsonl").is_file()
        assert (run_dir / "console.log").is_file()
        assert meta["frame_count"] == 2
        assert meta["network_event_count"] == 1
        assert meta["console_event_count"] == 1
        assert meta["frames_file"] == "frames.json"
        assert meta["network_file"] == "network.jsonl"
        assert meta["console_file"] == "console.log"

    def test_no_frames_no_artifacts(self, tmp_path: Path):
        run_dir, meta = save_snapshot(
            "<html></html>", url="https://example.com", title="t", out_dir=tmp_path,
            when=datetime.datetime(2026, 7, 9, 21, 30, 0),
        )
        assert not (run_dir / "frames.json").exists()
        assert not (run_dir / "network.jsonl").exists()
        assert not (run_dir / "console.log").exists()
        assert meta["frame_count"] == 0
        assert meta["network_event_count"] == 0
        assert meta["frames_file"] is None
