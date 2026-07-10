# Example 1 — Capture a page

Goal: open a page, interact with it, and save the current rendered state.

## Interactive (web control panel)

```bash
domvault serve            # or just: domvault
```

1. Open <http://127.0.0.1:8000> in your normal browser.
2. Type a URL (e.g. `example.com`) and click **Open**. A real Chromium window
   opens to it.
3. Do what you need in that window: log in, search, filter, paginate.
4. (optional) Type a snapshot name, then click **Save snapshot**.
5. The panel shows the saved directory, a screenshot preview, and a download
   link for each artifact.

Result:

```
saved_html/example.com_20260710_120000/
├── page.html
├── screenshot.png
├── storage_state.json
├── frames.json
├── network.jsonl
├── console.log
└── metadata.json
```

## One-shot (CLI, no UI)

```bash
domvault capture example.com --name home
```

Prints the snapshot path to stdout:

```
Saved snapshot: /home/me/saved_html/home
...
/home/me/saved_html/home
```

So you can script it:

```bash
DIR=$(domvault capture example.com --name home)
echo "HTML at $DIR/page.html"
```
