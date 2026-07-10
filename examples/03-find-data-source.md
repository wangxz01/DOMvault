# Example 3 — Find where the data comes from

Goal: when scraping, figure out whether the data you want is in the rendered
DOM, an iframe, a network API, or browser storage. DOMVault gives you all four
in one snapshot.

## Capture with everything

```bash
domvault serve
```

1. Open the target URL, reproduce the state where the data is visible
   (search / filter / paginate to it).
2. Click **Save snapshot**.

## 1. Is it in the rendered DOM?

Open `page.html` and search for a known value, or use the **Selector test**
card in the panel to try CSS / XPath selectors live:

- `CSS: table.results td.name` → see the match count + sample text.
- Click **Highlight** to outline the matches in the browser window.

If the count is what you expect, a selector in `page.html` is enough — no need
to reverse-engineer the API.

## 2. Is it in an iframe?

Check `frames.json`:

```bash
cat saved_html/<snapshot>/frames.json
```

Each non-main frame also has its own HTML under `frames/001_<name>.html`.
Search there if the data lives inside an embedded widget (common in admin
panels and dashboards).

## 3. Is it fetched from an API?

Scan `network.jsonl` for XHR/fetch responses. Each line is one event:

```bash
# show only fetch/xhr responses with a 200
grep '"kind": "response"' saved_html/<snapshot>/network.jsonl \
    | grep -E '"resource_type": "(fetch|xhr)"' \
    | grep '"status": 200'
```

Sort the matching URLs by eye; the one returning the list you see on screen is
your data endpoint. Then reproduce it directly with `requests`/`httpx` plus the
cookies from `storage_state.json`.

For an offline, DevTools-friendly record of the whole session, tick
**Record network to HAR** before opening the URL; the `.har` file is finalized
when you close the browser and can be loaded into Chrome DevTools' Network
panel or any HAR viewer.

## 4. Console hints

`console.log` records page errors and messages — useful when a page renders
blank or an API errors out. A `401`/`403` in `network.jsonl` plus a token in
`storage_state.json` usually means an auth/cookie problem.
