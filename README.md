# DOMVault

> A lightweight local Playwright tool for capturing the **current rendered HTML**
> of a web page after manual interaction — for scraping learning, selector
> debugging, and WebRPA flow analysis.

DOMVault runs a small **local web control panel** (`http://127.0.0.1:8000`).
You enter a URL there, a real (headed) Playwright browser opens to it, you
manually log in / click / paginate / filter as you normally would, then click
**Save current HTML** — the backend calls `page.content()` and writes the
current rendered DOM to a timestamped file.

It is **not** a full web-archiving system. In the MVP stage it captures the
current DOM HTML only (no offline images/CSS/JS bundles). See
[ROADMAP.md](./ROADMAP.md) for what is planned.

中文简介：DOMVault 是一个基于 Playwright 的轻量网页状态保存工具，用于爬虫学习、
DOM 快照保存和 WebRPA 调试。它提供一个本地 Web 控制台：输入网址 → 打开真实浏览器 →
手动操作页面 → 点击保存当前渲染后的 HTML。

---

## Quick start

### Prerequisites

- **Python 3.9 or newer**, installed from [python.org](https://www.python.org/downloads/).
  > ⚠️ On Windows, the `python.exe` under `AppData\Local\Microsoft\WindowsApps`
  > is a **Microsoft Store stub**, not a real Python. Install from python.org
  > instead and tick "Add Python to PATH" during setup.

### Install

```bash
# from the DOMVault project root
python -m venv .venv

# activate (Windows PowerShell)
.\.venv\Scripts\Activate.ps1
# or (Windows git-bash / macOS / Linux)
source .venv/Scripts/activate    # Windows git-bash
source .venv/bin/activate        # macOS / Linux

# install DOMVault + dev dependencies
pip install -e ".[dev]"

# download the Playwright browser binary (~130 MB, one-time)
playwright install chromium
```

### Run

```bash
domvault
```

Then open <http://127.0.0.1:8000> in your normal browser. Enter a URL
(e.g. `example.com` — the `https://` is added automatically), click **Open**,
interact with the Playwright browser that pops up, then click
**Save current HTML**.

Options:

```bash
domvault --host 127.0.0.1 --port 8000
domvault --help
```

---

## Usage

1. Start the server: `domvault`
2. Visit <http://127.0.0.1:8000>
3. Type a URL and click **Open** — a headed Chromium window opens to that page.
4. Do whatever you need in that browser: log in, search, filter, paginate.
5. Click **Save snapshot**. The current rendered HTML, a full-page screenshot,
   the storage state (cookies + localStorage), and `metadata.json` are written
   into their own directory `saved_html/<name>/`. The control panel shows a
   screenshot preview plus a download link for each artifact.
6. Navigate somewhere else and click **Save** again — each save gets its own
   timestamped directory, never overwriting a previous one.

To resume a logged-in session: pick a previous `storage_state.json` in the
**Restore login state** field before clicking **Open** — the browser starts
with those cookies/localStorage already set.

### Output

```
saved_html/
└── example.com_20260709_213000/
    ├── page.html              # rendered DOM
    ├── screenshot.png         # full-page screenshot
    ├── storage_state.json     # cookies + localStorage (reloadable)
    ├── frames.json            # index of every frame on the page
    ├── frames/                # one HTML file per iframe (cross-origin too)
    │   └── 001_inner.html
    ├── network.jsonl          # request/response summaries, one JSON per line
    ├── console.log            # console messages + page errors
    └── metadata.json          # url, title, saved_at, file list, counts
```

You can pass an optional snapshot name; otherwise the directory is named
`<domain>_<YYYYMMDD_HHMMSS>`.

### Debugging aids

- **Selector test** — in the **Selector test** card, pick CSS or XPath, enter a
  selector, and click **Test** to see the match count plus a few element
  samples. **Highlight** outlines the matches in the live browser window;
  **Clear** removes the outlines. (Main frame only.)
- **Record HAR** — tick **Record network to HAR this session** before opening a
  URL to capture the whole session's network in HAR format. The file is
  finalized when you click **Close browser** and saved under `saved_html/har/`,
  downloadable from the control panel.

> DOMVault helps you see where target data comes from: rendered DOM, iframe,
> network API, or browser storage.

---

## How it works

```
┌─────────────────────────────────────────────┐
│  DOMVault process (Python, single event loop)│
│                                              │
│  FastAPI  ◀── /api/open, /api/save  ──  your │
│  server        (JSON over HTTP)       normal │
│      │                                browser│
│      ▼                                       │
│  Playwright (async) ──▶ headed Chromium      │
│      │                                       │
│      ▼                                       │
│  page.content() / screenshot / state ──▶ saved_html/<snapshot>/        │
└─────────────────────────────────────────────┘
```

The control panel is an ordinary web page served on `127.0.0.1`. The Playwright
browser it controls is a separate headed Chromium window.

---

## Roadmap

See [ROADMAP.md](./ROADMAP.md) for the full milestone plan
(MVP → V0.2 → V0.3 → V1.0).

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

[MIT](./LICENSE)
