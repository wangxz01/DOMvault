"""Entry point: ``python -m domvault`` or the ``domvault`` console script.

Commands:
    domvault                       start the web control panel (same as `serve`)
    domvault serve [OPTIONS]       start the web control panel
    domvault capture <url> [...]   headless one-shot snapshot capture

``serve`` opens a local web UI at http://127.0.0.1:8000 where you open a URL,
interact with a real browser, and capture snapshots on demand.
``capture`` runs without a UI: it opens the URL headless, waits, captures a
snapshot directory, and exits — convenient for scripting.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
from pathlib import Path

from . import __version__


def _common_help_epilog() -> str:
    return ""


def _build_serve_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="domvault serve",
        description=(
            "Start the DOMVault web control panel. The Playwright browser is "
            "opened on demand when you submit a URL from the panel."
        ),
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000).")
    parser.add_argument(
        "--out", "-o", type=Path, default=Path("saved_html"),
        help="Directory for snapshots (default: ./saved_html).",
    )
    parser.add_argument(
        "--browser", default="chromium", choices=["chromium", "firefox", "webkit"],
        help="Browser engine (default: chromium). Requires `playwright install <engine>`.",
    )
    return parser


def _build_capture_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="domvault capture",
        description=(
            "Headless one-shot capture: open a URL, wait for it to load, write a "
            "snapshot directory (DOM, screenshot, storage state, frames, network, "
            "console), then exit. No web UI."
        ),
    )
    parser.add_argument("url", help="URL to capture (https:// is added if no scheme).")
    parser.add_argument(
        "--out", "-o", type=Path, default=Path("saved_html"),
        help="Directory for snapshots (default: ./saved_html).",
    )
    parser.add_argument("--name", default=None, help="Custom snapshot directory name.")
    parser.add_argument(
        "--browser", "-b", default="chromium", choices=["chromium", "firefox", "webkit"],
        help="Browser engine (default: chromium).",
    )
    parser.add_argument(
        "--wait", default="load", choices=["load", "domcontentloaded", "networkidle"],
        help="page.goto wait condition (default: load). networkidle can hang on SPAs.",
    )
    parser.add_argument(
        "--timeout", type=float, default=30000.0,
        help="Navigation timeout in ms (default: 30000).",
    )
    parser.add_argument(
        "--storage-state", "-s", type=Path, default=None,
        help="Load a storage_state.json to restore cookies/localStorage.",
    )
    parser.add_argument("--no-screenshot", action="store_true", help="Skip the full-page screenshot.")
    parser.add_argument("--no-frames", action="store_true", help="Skip per-frame/iframe HTML capture.")
    return parser


def _find_free_port(host: str, start: int, attempts: int = 100) -> int:
    """Return the first bindable port at/after ``start``; raises if none found.

    Probes by binding a socket to ``host``:port`` and closing it immediately.
    Note: there's an inherent TOCTOU race between this check and uvicorn's
    bind, but it's fine for a local single-user tool.
    """
    last_err: Exception | None = None
    for off in range(attempts):
        port = start + off
        if port > 65535:
            break
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                # NB: do NOT set SO_REUSEADDR here — on Windows it allows
                # double-binding and would falsely report a busy port as free.
                s.bind((host, port))
                return port
        except OSError as exc:
            last_err = exc
            continue
    raise SystemExit(
        f"找不到空闲端口（已尝试 {host}:{start}~{start + attempts - 1}）：{last_err}"
    )


def _run_serve(argv: list[str]) -> int:
    args = _build_serve_parser().parse_args(argv)
    import uvicorn
    from .server import app, set_output_dir

    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    set_output_dir(out_dir)

    port = _find_free_port(args.host, args.port)
    url = f"http://{args.host}:{port}"
    redirected = port != args.port

    print(f"DOMVault {__version__} — 控制台", file=sys.stderr)
    if redirected:
        print(f"  端口 {args.port} 被占用，已改用 {port}。", file=sys.stderr)
    print("=" * 54, file=sys.stderr)
    print(f"   在浏览器打开：  {url}", file=sys.stderr)
    print("=" * 54, file=sys.stderr)
    print(f"  快照保存到： {out_dir}", file=sys.stderr)
    print(f"  浏览器内核： {args.browser}", file=sys.stderr)
    print("  按 Ctrl+C 退出。", file=sys.stderr)

    uvicorn.run(app, host=args.host, port=port, log_level="warning")
    return 0


async def _capture_async(args: argparse.Namespace) -> dict:
    from . import browser
    from .capture import capture_snapshot
    from .saver import InvalidURL, normalize_url

    try:
        url = normalize_url(args.url)
    except InvalidURL as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)

    storage_state = None
    if args.storage_state:
        try:
            storage_state = json.loads(args.storage_state.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"error: could not read storage_state: {exc}", file=sys.stderr)
            raise SystemExit(2)

    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        await browser.open_url(
            url,
            kind=args.browser,
            storage_state=storage_state,
            headless=True,
            wait_until=args.wait,
            timeout=args.timeout,
        )
        result = await capture_snapshot(
            out_dir,
            custom_name=args.name,
            want_screenshot=not args.no_screenshot,
            want_frames=not args.no_frames,
        )
    except browser.BrowserError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    finally:
        await browser.close()
    return result


def _run_capture(argv: list[str]) -> int:
    args = _build_capture_parser().parse_args(argv)
    result = asyncio.run(_capture_async(args))

    files = result["files"]
    counts = result["counts"]
    present = [k for k in ("html", "screenshot", "storage_state", "frames", "network", "console") if files.get(k)]
    print(f"Saved snapshot: {result['path']}", file=sys.stderr)
    print(f"  url:    {result['url']}", file=sys.stderr)
    print(f"  title:  {result['title'] or '(no title)'}", file=sys.stderr)
    print(f"  files:  {', '.join(present)}", file=sys.stderr)
    print(f"  counts: {counts['frames']} frames, {counts['network']} network events, {counts['console']} console msgs", file=sys.stderr)
    print(result["path"])  # stdout: just the path, for scripting
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Global flags.
    if not argv or argv[0] in ("-h", "--help"):
        _print_top_level_help()
        return 0
    if argv[0] in ("--version", "-V"):
        print(f"domvault {__version__}")
        return 0

    # Subcommand dispatch. `serve` is the default when no subcommand is given,
    # so `domvault --port 9000` still starts the server (backward compatible).
    if argv[0] == "capture":
        return _run_capture(argv[1:])
    if argv[0] == "serve":
        return _run_serve(argv[1:])
    return _run_serve(argv)


def _print_top_level_help() -> None:
    print(
        f"""DOMVault {__version__} - lightweight Playwright DOM capture tool

usage:
  domvault                       start the web control panel (default)
  domvault serve [--host H --port P --out DIR --browser ENGINE]
  domvault capture <url> [--name N --wait load --out DIR ...]
  domvault --version

Run `domvault serve --help` or `domvault capture --help` for per-command options.
"""
    )


if __name__ == "__main__":
    raise SystemExit(main())
