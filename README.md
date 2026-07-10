# DOMVault

> 一个基于 Playwright 的轻量本地工具，用于在**手动操作网页之后**捕获**当前渲染的 HTML** ——
> 适合爬虫学习、选择器调试和 WebRPA 流程分析。

DOMVault 会启动一个**本地 Web 控制台**（`http://127.0.0.1:8000`）。你在控制台里输入网址，
一个真实的（有界面的）Playwright 浏览器会打开它；你像平时一样手动登录 / 点击 / 翻页 / 筛选，
然后点击 **保存当前 HTML** —— 后端调用 `page.content()`，把当前渲染后的 DOM 写入一个带时间戳的目录。

它**不是**一个完整的网页归档系统。当前只捕获渲染后的 DOM HTML（不打包离线的图片/CSS/JS）。
计划中的功能见 [ROADMAP.md](./ROADMAP.md)。

---

## 快速开始

### 前置条件

- **Python 3.9 及以上**，从 [python.org](https://www.python.org/downloads/) 安装。
  > ⚠️ Windows 上，`AppData\Local\Microsoft\WindowsApps` 下的 `python.exe`
  > 是 **Microsoft Store 的占位程序**，不是真正的 Python。请从 python.org 安装，
  > 并在安装时勾选 "Add Python to PATH"。
- 浏览器内核：安装后需要执行一次 `playwright install chromium` 下载内核（约 130 MB）。

### 安装

DOMVault 是一个普通的 Python 包。你可以用 **venv** 或 **conda**，二选一。

**方式 A：用 conda（推荐，本文档示例环境）**

```bash
conda create -y -n domvault python=3.11
conda activate domvault
pip install -e ".[dev]"
playwright install chromium
```

以后每次使用前先 `conda activate domvault` 即可。

**方式 B：用 venv**

```bash
# 在 DOMVault 项目根目录
python -m venv .venv

# 激活（Windows PowerShell）
.\.venv\Scripts\Activate.ps1
# 或（Windows git-bash / macOS / Linux）
source .venv/Scripts/activate    # Windows git-bash
source .venv/bin/activate        # macOS / Linux

pip install -e ".[dev]"
playwright install chromium
```

### 运行

```bash
domvault
```

然后在你的常用浏览器里打开 <http://127.0.0.1:8000>。输入网址
（例如 `example.com` —— `https://` 会自动补上），点击 **Open**，在弹出的 Playwright
浏览器里操作页面，然后点击 **Save snapshot**。

选项：

```bash
domvault                              # 启动网页控制台（默认命令）
domvault serve --host 127.0.0.1 --port 8000
domvault --version
domvault --help
```

### 一次性抓取（无界面）

用于脚本化场景，无头抓取一个快照并输出其路径：

```bash
domvault capture example.com --name home
# -> 写入 saved_html/home/... ，并把目录路径打印到 stdout
```

常用参数：`--out/-o`、`--name`、`--browser/-b`、`--wait load|domcontentloaded|networkidle`、
`--timeout`、`--storage-state 文件`、`--no-screenshot`、`--no-frames`。

完整的端到端示例见 [examples/](./examples) 目录（基本抓取、恢复登录态、定位数据来源）。

---

## 使用流程

1. 启动服务：`domvault`
2. 浏览器打开 <http://127.0.0.1:8000>
3. 输入网址，点击 **Open** —— 会弹出一个有界面的 Chromium 窗口打开该网页。
4. 在这个浏览器里做你需要的操作：登录、搜索、筛选、翻页。
5. 点击 **Save snapshot**。当前渲染后的 HTML、整页截图、storage state（cookies + localStorage）
   以及 `metadata.json` 会写入一个独立目录 `saved_html/<名字>/`。控制台会显示截图预览，
   以及每个文件的下载链接。
6. 跳到别的页面再点一次 **Save** —— 每次保存都生成独立的时间戳目录，不会覆盖之前的。

要恢复登录态：点击 **Open** 之前，在 **Restore login state** 一栏选择之前的
`storage_state.json` —— 浏览器会带着这些 cookies/localStorage 启动，省去再次登录。

### 输出结构

```
saved_html/
└── example.com_20260709_213000/
    ├── page.html              # 渲染后的 DOM
    ├── screenshot.png         # 整页截图
    ├── storage_state.json     # cookies + localStorage（可重新加载）
    ├── frames.json            # 页面上所有 frame 的索引
    ├── frames/                # 每个 iframe 单独一个 HTML（含跨域 iframe）
    │   └── 001_inner.html
    ├── network.jsonl          # 请求/响应摘要，每行一个 JSON
    ├── console.log            # console 消息 + 页面报错
    └── metadata.json          # url、title、saved_at、文件列表、计数
```

可以指定快照名；不指定则目录名为 `<域名>_<YYYYMMDD_HHMMSS>`。

### 调试辅助

- **选择器测试** —— 在 **Selector test** 卡片里选择 CSS 或 XPath，输入选择器，
  点击 **Test** 查看匹配数量和几个元素样本。点击 **Highlight** 会在浏览器窗口里给匹配项加描边；
  **Clear** 清除描边。（仅作用于主框架。）
- **录制 HAR** —— 打开网址前勾选 **Record network to HAR this session**，把整个会话的网络
  以 HAR 格式录制下来。点击 **Close browser** 时文件落盘到 `saved_html/har/`，
  可在控制台下载。

> DOMVault 帮你看清目标数据到底来自哪里：渲染后的 DOM、iframe、网络接口，还是浏览器存储。

---

## 工作原理

```
┌─────────────────────────────────────────────┐
│  DOMVault 进程（Python，单事件循环）          │
│                                              │
│  FastAPI  ◀── /api/open, /api/save  ──  你的 │
│  服务        （JSON over HTTP）       常用    │
│      │                                浏览器 │
│      ▼                                       │
│  Playwright (async) ──▶ 有界面 Chromium      │
│      │                                       │
│      ▼                                       │
│  page.content() / 截图 / state ──▶ saved_html/<快照>/ │
└─────────────────────────────────────────────┘
```

控制台是一个运行在 `127.0.0.1` 的普通网页；它控制的 Playwright 浏览器是另一个独立的有界面 Chromium 窗口。

---

## 路线图

完整里程碑计划见 [ROADMAP.md](./ROADMAP.md)
（MVP → V0.2 → V0.3 → V1.0）。

## 更新日志

见 [CHANGELOG.md](./CHANGELOG.md)。

## 开发

```bash
pip install -e ".[dev]"
pytest
```

## 许可证

[MIT](./LICENSE)
