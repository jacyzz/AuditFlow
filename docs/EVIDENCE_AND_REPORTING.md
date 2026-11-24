# 自动化取证截屏与 CNVD 报告双输出规范

本文档详细定义 **4 个确定性证据渲染器（覆盖 Web / API / 非 Web 项目）**、**可选真 Burp 流量导流机制**，以及 **Windows 侧 CNVD `.docx` 与表单字段双输出规范**。

本文保留原始设计。当前网页截图读取本地 HTML，HTTP 与终端渲染读取已保存的记录，当前入口见 [README](../README.md)。

---

## 1. 四类确定性证据渲染器（`src/auditflow/evidence/`）

所有渲染器均为独立可调用的 Python CLI 模块，接收结构化 JSON 参数，输出统一规范的高清 PNG（推荐 2x DPI、宽度 1200～1440px，确保插入 Word 后字迹锐利不发虚）。

### 1.1 `render_code_shot.py`（所有项目通用 — 源码审计截图）

- **输入**：`--file <源码绝对路径>`、`--start <起始行>`、`--end <结束行>`、`--highlight <逗号分隔高亮行>`、`--label <显示用相对路径:行号>`、`--out <output.png>`
- **实现机制**：
  1. 读取指定行区间（若前后需上下文，支持 `--context 3`）；
  2. 使用 `Pygments` 根据文件后缀自动词法高亮；
  3. 套入简洁亮色/暗色 IDE HTML 卡片模板：顶部显示文件路径与行号范围（如 `route/v1/file.go:430-445`），左侧显示真实源码行号，对 `highlight` 行叠加淡红背景与红色左侧/外围高亮框；
  4. 通过 `Playwright` 渲染卡片元素为 2x 高清 PNG。
- **验收标准**：代码行号与源码严格一致，高亮清晰，无截断乱码，支持 Go/Java/Python/JS/TS/SQL/YAML/Pug 等常见语言。

### 1.2 `capture_web_shot.py`（Web UI / 浏览器可直达场景）

- **输入**：`--url <本地隔离URL>`、`--cookies <可选JSON>`、`--headers <可选JSON>`、`--wait-selector <可选CSS选择器>`、`--show-address-bar`、`--out <output.png>`
- **实现机制**：
  1. 使用 `Playwright` 启动隔离 Chromium（`viewport=1440x900`），每次调用使用全新的 `BrowserContext`（保证未登录无痕对照绝对干净）；
  2. 访问目标 URL，等待 `networkidle`（加可配置稳定等待时间，超时降级 `load`）；
  3. 若开启 `--show-address-bar`，使用 Pillow 或顶栏注入在页面顶部合成简洁的浏览器地址栏条，展示当前最终 URL（如发生 302 跳转至 `/login.html` 会直观显示跳转后地址）；
  4. 截取 PNG 并返回最终 HTTP 状态码与最终 URL 至 stdout JSON。

### 1.3 `render_http_shot.py`（HTTP API / 改包类 + 可选真 Burp 导流）

- **全自动默认模式**：
  - **输入**：读取 `verify.json` 中某步记录的真实 `raw_request`、`raw_response`、`highlight_response_patterns`、`title`；
  - **实现机制**：用左右分栏 HTML 模板（左侧 `Request`，右侧 `Response`，类 Burp Suite Repeater 布局）渲染完整原始 HTTP 报文，自动语法高亮 HTTP 头与格式化后的 JSON 响应体，并对 `highlight_response_patterns`（如 `HTTP/1.1 200 OK`、敏感泄露字段、对照组 `401 Unauthorized`）自动加红框高亮，再由 `Playwright` 输出高清 PNG。
- **可选真 Burp Suite 导流模式（`burp_upstream_proxy`）**：
  - 在 `config/env.yaml` 中支持配置 `burp_upstream_proxy: "http://<windows-ip>:8080"`（默认 `null` 关闭）；
  - 开启时，验证阶段所有发往本地隔离实例的 HTTP 验证请求自动经过该上游代理，将真实请求/响应直接打入用户本机开着的 Burp Suite `Proxy -> HTTP History`；
  - 用户可直接从 BP History 截取真实 Burp 界面图替换 `evidence/` 对应文件，无需手工粘包。

### 1.4 `render_term_shot.py`（非 Web 项目：数据库 / RPC / MCP / CLI / 开源库 / 服务端核查）

- **输入**：`--command <执行命令>`、`--stdout-file <真实输出文件>`、`--highlight <高亮关键词列表>`、`--title <终端窗口标题>`、`--out <output.png>`
- **实现机制**：
  1. 解析 ANSI 颜色转义序列（如有）并转义 HTML 特殊字符；
  2. 套入高对比度终端窗口 HTML 模板（显示工作目录/提示符、完整执行命令、真实输出与退出码），对关键证据行（如 `root:root 644`、`admin=1`、`ERROR 1142 Access denied`、时间盲注耗时对比）加红色高亮框；
  3. 通过 `Playwright` 输出高清 PNG。

### 1.5 目标类型与证据组合映射表

| 目标类型 | `evidence/` 自动产出的标准截图组合 |
|---|---|
| **Web UI 系统** | `00_app_home.png`（Web 首页）+ `01_code_*.png`（源码图）+ `02_web_*.png`（浏览器正负对照图） |
| **HTTP API / 网关** | `00_app_home.png`（如有 UI）+ `01_code_*.png` + `02_http_*.png`（报文对照图，可选 BP 导流）+ `03_term_*.png`（服务端 `stat`/日志核查） |
| **数据库 / RPC / CLI / 开源库** | `01_code_*.png`（漏洞源码图 + 最小复现代码图）+ `02_term_*.png`（正负对照终端输出图） |
| **桌面 GUI / 强宿主机内核类** | `01_code_*.png`（自动）+ `.docx` 内保留红色 `【此处人工补图：...】` 占位（仅对必须手点的 GUI 步骤优雅降级） |

---

## 2. Windows 侧 CNVD 报告双输出规范（`src/auditflow/reporting/`）

### 2.1 文档写作风格红线（内置于 `skills/report/cnvd-docx-writer/SKILL.md`）

为彻底消除“AI 复核腔/人机味”，报告生成阶段必须强制遵循以下文风规范：

1. **禁止元叙述**：严禁出现“原始验证记录显示”“在所复核的实现中”“现有记录覆盖”“根据上游审计报告”“本次复核发现”等旁白腔调；直接以安全研究员第一视角陈述代码逻辑、缺陷成因与验证步骤。
2. **结构简洁直给**：严格按 CNVD 习惯结构展开：
   - 标题（`<产品名> <核心缺陷与危害>`）
   - 项目简介 + 项目首页截图
   - `官网地址` / `项目地址` / `Star数` / `部署方式`
   - `漏洞描述` / `漏洞等级` / `漏洞危害`
   - `代码审计`（按调用链编号：`1. 文件 path:start-end` → 一针见血机制说明 → 精简代码框 → 对应高清代码截图）
   - `漏洞验证`（优先采用**浏览器直接操作**或 **Burp Suite Repeater 原始请求包**，尽量减少 `curl`；明确写出负向对照与正向验证结果，并紧跟对应截图）
   - `修复建议`（临时缓解 + 正式代码级修复）
3. **不臆测不夸大**：所有行号、接口路径、返回状态码、受影响版本严格来自 `meta.json` / `audit.json` / `verify.json`；默认部署是否受影响、前提条件必须如实写明。

### 2.2 Word `.docx` 排版规范（`docx_builder.py`）

- 字体：中文 `微软雅黑`，英文/数字 `Calibri`，代码块 `Consolas 9.5pt`；
- 标题：文档主标题 `18pt 加粗`，一级节标题（`代码审计`、`漏洞验证`、`修复建议`）`15pt 加粗`，子项标题 `12pt 加粗`；
- 代码/HTTP 请求框：单格浅灰底色（`#F5F6F8`）+ 细边框（`#D9DEE3`）表格，防折行错乱；
- 图片嵌入：自动按页面可用宽度（约 `6.2 inches`）等比缩放嵌入 `evidence/*.png`；若某步骤标记为人工补图，自动插入红色粗体 `【此处插入截图：<描述>】` 占位段。

### 2.3 CNVD 网页提报表单导出（`cnvd_form_exporter.py`）

同步输出两份文件，方便直接复制填报 CNVD 官网与留档：
1. `<漏洞标题>_cnvd表单.md`：按 CNVD 提报页栏位顺序逐项列出：漏洞名称、涉及厂商、受影响产品、受影响版本、官网/仓库、漏洞类型（含 CWE）、危害等级、漏洞描述（精炼表单版）、漏洞危害、验证方式简述、修复建议、参考链接；
2. `<漏洞标题>_cnvd表单.json`：结构化存档，供台账工具读取。

### 2.4 台账同步（`tracker_sync.py`）

支持将新生成的报告元数据写入本地 SQLite，并支持以**只追加不破坏原有格式**的方式同步至指定的汇总 Excel 文件（可配置开启/关闭，默认自动备份原 Excel 后再追加）。
