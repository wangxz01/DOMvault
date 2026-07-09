"""Entry point: ``python -m domvault`` or the ``domvault`` console script.

Starts the FastAPI control panel via uvicorn. The Playwright browser is opened
on demand when the user submits a URL from the control panel.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="domvault",
        description=(
            "DOMVault - a lightweight local Playwright tool for capturing the "
            "current rendered HTML of a web page. Starts a local web control "
            "panel at http://127.0.0.1:8000 by default."
        ),
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Bind address for the control panel (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port", type=int, default=8000,
        help="Port for the control panel (default: 8000).",
    )
    parser.add_argument(
        "--out", "-o", type=Path, default=Path("saved_html"),
        help="Directory where captured HTML files are written (default: ./saved_html).",
    )
    parser.add_argument(
        "--browser", default="chromium",
        choices=["chromium", "firefox", "webkit"],
        help="Browser engine to use (default: chromium). Note: the matching "
             "Playwright binary must be installed, e.g. `playwright install chromium`.",
    )
    parser.add_argument(
        "--version", action="version", version=f"domvault {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    # Import here so that --help / --version work even if optional deps are
    # mis-installed, and so the import cost is paid only when actually running.
    import uvicorn

    from .server import app, set_output_dir

    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    set_output_dir(out_dir)

    print(f"DOMVault {__version__}", file=sys.stderr)
    print(f"  control panel:  http://{args.host}:{args.port}", file=sys.stderr)
    print(f"  saved HTML to:  {out_dir}", file=sys.stderr)
    print(f"  browser engine: {args.browser}", file=sys.stderr)
    print("  Press Ctrl+C to stop.", file=sys.stderr)

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
