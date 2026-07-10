# Roadmap

DOMVault is developed in small, closable milestones. The MVP only solves one
core problem:

```
Enter a URL → Playwright opens a real browser → user manually interacts
→ click a button to save the current rendered HTML.
```

Later milestones add the surrounding context (screenshots, metadata, storage
state, network analysis, selector debugging) without turning the tool into a
full web-archive system.

## Project goal

> DOMVault aims to provide a lightweight local workflow for capturing the
> actual rendered state of web pages with Playwright. Its primary goal is to
> help web scraping learners and WebRPA developers save, inspect, and debug
> dynamic page states after manual browser interaction.

中文：

> DOMVault 的目标是提供一个轻量级本地工作流，用 Playwright 捕获网页的真实渲染状态，
> 帮助爬虫学习者和 WebRPA 开发者在手动操作网页后保存、检查和调试动态页面状态。

## What DOMVault is **not**

DOMVault captures the current rendered DOM HTML. In the MVP stage it does **not**
aim to create a fully offline, high-fidelity web archive. It is not a replacement
for SingleFile, ArchiveBox, or Browsertrix.

DOMVault 在 MVP 阶段主要保存当前渲染后的 DOM HTML，不追求完整离线网页归档。

## MVP

- [x] Provide a local web control panel
- [x] Open a URL with a real Playwright browser
- [x] Allow users to manually interact with the page
- [x] Capture the current rendered DOM as HTML
- [x] Save HTML files with timestamp-based names
- [x] Provide a download link after saving
- [x] Handle basic navigation and saving errors

### MVP acceptance criteria

> The user can open the local control panel, enter any web URL, Playwright opens
> that page, the user manually operates the page in the browser, then clicks
> "Save current HTML" and the program writes the current rendered HTML to a
> local file.

### MVP performance targets

| Metric | Target | Note |
| --- | --- | --- |
| Startup stability | Server starts, browser opens normally | Not fast, but must not crash often |
| URL open success | Common sites open normally | No CAPTCHA / strong anti-bot for now |
| HTML save speed | Ordinary pages in 1–3s | Very large DOM may take longer |
| File integrity | Contains the current DOM structure | Images/CSS/JS need not be offline-usable |
| Repeat saves | Same page can be saved in different states | Filenames must not collide |
| Error recovery | A failed save must not crash the server | Show an error message |
| Cross-platform | Windows / macOS / Linux basically run | Playwright supports all three |

## V0.2 — useful for scraping learners

- [x] Save page screenshots
- [x] Save page metadata (URL, title, timestamp)
- [x] Save each snapshot into an independent directory
- [x] Save and load Playwright `storage_state.json`
- [x] Support custom filenames

Planned snapshot structure:

```
saved_html/
  example.com_20260709_213000/
    page.html
    screenshot.png
    metadata.json
    storage_state.json
```

## V0.3 — WebRPA debugging

- [x] List all frames in the current page
- [x] Save iframe HTML separately
- [x] Record HAR files for network analysis
- [x] Provide basic CSS selector testing
- [x] Provide basic XPath testing
- [x] Highlight matched elements in the browser
- [x] Save console logs
- [x] Save request/response summaries

> DOMVault should help users understand where the target data comes from:
> rendered DOM, iframe, network API, or browser storage.

## V1.0 — releasable tool

- [ ] Provide a stable local workflow for web scraping learners and WebRPA debugging
- [ ] Support rendered DOM capture, screenshots, metadata, and storage state
- [ ] Include clear documentation and examples
- [ ] Package the tool for convenient local installation

## Explicitly out of scope

| Feature | Why not (for now) |
| --- | --- |
| Full offline web archive | Resource download, path rewriting, CSS/JS/image handling |
| WARC saving | Specialized archiving domain, high complexity |
| Distributed crawling | Out of scope for a local tool |
| Scheduled capture | That is ArchiveBox territory, not MVP |
| Visual flow orchestration | Would turn this into a large WebRPA platform |
| Automatic CAPTCHA solving | Unsuitable and raises compliance concerns |
| Large-scale concurrent crawling | Not the tool's core value |
| Cloud deployment | A local tool fits the learning/debugging scenario best |

## Recommended development order

```
1. Enter a URL and open the browser        (MVP)
2. Save the current HTML                   (MVP)
3. Auto-create save dir and filenames      (MVP)
4. Save screenshot and metadata            (V0.2)
5. Save / load login state                 (V0.2)
6. Support iframes                         (V0.3)
7. Add selector / XPath debugging          (V0.3)
8. Add HAR and network analysis            (V0.3)
```

Getting steps 1–3 right already makes the project genuinely useful.
