# Changelog

All notable changes to DOMVault. Versions follow a simplified
`MAJOR.MINOR.PATCH` scheme; pre-1.0 milestones mirror the roadmap.

## [1.0.0] — 2026-07-10

First releasable tool. Adds a scriptable headless CLI alongside the web panel.

- **CLI `capture` command**: `domvault capture <url>` opens a URL headless,
  waits, writes a full snapshot directory, and exits. Options: `--out`,
  `--name`, `--browser`, `--wait`, `--timeout`, `--storage-state`,
  `--no-screenshot`, `--no-frames`. Prints the snapshot path to stdout for
  scripting.
- **CLI `serve` command**: explicit alias for starting the web control panel.
  Bare `domvault` still starts the server (backward compatible).
- Refactored the capture path into `capture.py:capture_snapshot()`, now shared
  by the web panel's `/api/save` and the CLI `capture` command.
- Threaded `headless`, `wait_until`, and `timeout` through the Playwright
  session manager.
- Added `examples/` walkthroughs, `CHANGELOG.md`, `.gitattributes` (LF
  normalization).

## [0.3.0] — 2026-07-10

WebRPA debugging — see where the target data comes from.

- Per-frame capture: `frames.json` + one HTML file per iframe under `frames/`
  (cross-origin iframes included).
- Network capture: `network.jsonl` (request/response summaries, one JSON per
  line) recorded throughout the session.
- Console capture: `console.log` with console messages and page errors.
- Live `GET /api/frames` lists every frame on the current page.
- CSS / XPath selector testing via `POST /api/test-selector` (match count +
  element samples) and `GET /api/frames`.
- Element highlighting in the live browser via `POST /api/highlight` and
  `/api/clear-highlight`.
- Opt-in session HAR recording (`record_har` on `/api/open`), finalized on
  `/api/close` to `saved_html/har/`.
- New `collectors.py` module for the bounded network/console event buffer.

## [0.2.0] — 2026-07-09

Make the tool genuinely useful for scraping learners.

- Each save now produces an independent directory: `page.html`,
  `screenshot.png`, `storage_state.json`, `metadata.json`.
- Full-page screenshots.
- `metadata.json` with URL, title, timestamp, file list.
- Save **and** reload Playwright `storage_state.json` (resume a logged-in
  session from the control panel).
- Custom snapshot names.
- `GET /api/snapshots` lists saved runs; `GET /api/download/{run}/{file}`
  serves nested artifact files with path-traversal guards.

## [0.1.0] — 2026-07-09

Initial MVP.

- Local web control panel (FastAPI) at `http://127.0.0.1:8000`.
- Open a URL in a real (headed) Playwright browser.
- Manually interact (login, click, paginate), then "Save current HTML".
- Auto-named files under `saved_html/`; download link in the panel.
- Basic error handling for bad URLs and missing browser binaries.
