# DOMVault

> 基于 Playwright 的轻量本地工具：用真实浏览器打开网页，手动操作后，一键保存当前渲染状态。用于爬虫学习、DOM 快照和 WebRPA 调试。

DOMVault 提供一个本地 Web 控制台：输入网址 → 打开有界面的浏览器 → 你像平时一样登录 / 点击 / 翻页 / 筛选 → 点击「保存快照」，当前渲染后的 HTML、整页截图、登录态、frame/iframe、网络与控制台日志会一起写入一个独立目录。

它**不是**网页归档系统，只保存当前渲染后的 DOM 状态（不打包离线图片/CSS/JS）。

---

## 安装

需要 **Python 3.9+**（从 [python.org](https://www.python.org/downloads/) 安装，安装时勾选 “Add Python to PATH”）。

```bash
# 在项目根目录
python -m venv .venv

# 激活虚拟环境
.venv\Scripts\activate          # Windows PowerShell / CMD
source .venv/Scripts/activate   # Windows git-bash
source .venv/bin/activate       # macOS / Linux

# 安装 DOMVault + 下载浏览器内核（首次约 130 MB）
pip install -e ".[dev]"
playwright install chromium
```

> 以后每次使用前先激活 `.venv` 即可。

---

## 启动

```bash
domvault            # 启动网页控制台（默认命令）
```

启动后终端会打印可访问的本地网址（如 `http://127.0.0.1:8000`）；如果端口被占用，会自动找一个空闲端口并打印实际地址。在浏览器里打开它即可。

**无界面一次性抓取**（适合脚本）：

```bash
domvault capture example.com --name home
# 抓取后把快照目录路径打印到 stdout，方便管道使用
```

常用参数：`--out/-o`、`--name`、`--browser/-b`、`--wait load|domcontentloaded|networkidle`、`--timeout`、`--storage-state 文件`、`--no-screenshot`、`--no-frames`。

---

## 功能

- **打开网页**：真实有界面的 Playwright 浏览器，手动登录 / 翻页 / 筛选后再保存。
- **DOM 快照**：保存当前渲染后的 `page.html`。
- **整页截图**：`screenshot.png`。
- **登录态存/读**：保存 `storage_state.json`（cookies + localStorage），下次打开时可恢复登录态，免去重复登录。
- **自定义快照名**：每次保存一个独立目录，名称可自定义，默认 `<域名>_<时间戳>`。
- **iframe 抓取**：列出页面上所有 frame，跨域 iframe 的 HTML 也能单独保存。
- **网络日志**：`network.jsonl` 记录请求/响应摘要；可选用 HAR 格式录制整段会话。
- **控制台日志**：`console.log` 记录 console 消息和页面报错。
- **选择器调试**：在控制台里测试 CSS / XPath 选择器，查看匹配数量和元素样本，并一键在浏览器里高亮匹配项。

---

## 输出结构

每次保存生成一个独立目录：

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

---

## 开发

```bash
pip install -e ".[dev]"
pytest
```

## 许可证

[MIT](./LICENSE)
