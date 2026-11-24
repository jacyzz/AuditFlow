# AuditFlow 分阶段实施计划与验收标准

本文档面向开发者 / Coding Agent（如 Codex），明确工程目录、技术栈、三个里程碑的交付物与自动化测试验收标准。

---

## 1. 技术栈约束

- **语言与版本**：Python 3.11+，使用 `pyproject.toml`（Hatchling 或 Setuptools）打包，提供全局 CLI 入口 `auditflow`。
- **核心依赖**：
  - 数据契约与配置：`pydantic>=2.7`、`pyyaml>=6.0`
  - CLI 与交互表格：`typer>=0.12`、`rich>=13.7`
  - 网络与 API：`httpx>=0.27`
  - 代码高亮与截图：`pygments>=2.18`、`playwright>=1.45`、`pillow>=10.0`
  - Word 报告与台账：`python-docx>=1.1`、`openpyxl>=3.1`（可选 Excel 追加）
  - 数据库：Python 内置 `sqlite3`
- **测试工具**：`pytest`、`pytest-asyncio`（如有异步），所有核心模块必须具备无需外网与真实容器即可通过的单元测试。

---

## 2. 完整目标目录结构

```text
auditflow/
├── README.md
├── SECURITY.md
├── pyproject.toml
├── config/
│   ├── pipeline.example.yaml
│   └── env.example.yaml
├── docs/
│   ├── ARCHITECTURE.md
│   ├── SCHEMAS.md
│   ├── ADAPTERS_AND_SKILLS.md
│   ├── EVIDENCE_AND_REPORTING.md
│   └── IMPLEMENTATION_PLAN.md
├── src/auditflow/
│   ├── __init__.py
│   ├── cli.py                        # Typer CLI: doctor / validate / scout / audit / verify / evidence / report / status
│   ├── core/
│   │   ├── config.py                 # 加载与校验 pipeline.yaml & env.yaml
│   │   ├── schemas.py                # 7 个核心 Pydantic v2 模型 + JSON Schema 导出
│   │   ├── state.py                  # SQLite tracker 状态机（targets & candidates 表）
│   │   └── skill_registry.py         # 扫描加载 skills/<stage>/<name>/skill.yaml + SKILL.md
│   ├── backends/
│   │   ├── base.py                   # BaseExecutionBackend
│   │   ├── local.py                  # 本机子进程执行器
│   │   ├── ssh_ubuntu.py             # OpenSSH ssh/scp 远程执行器
│   │   └── wsl2.py                   # WSL2 本地执行器
│   ├── adapters/
│   │   ├── base.py                   # BaseAgentAdapter, AdapterRequest, AdapterResult
│   │   ├── registry.py               # AdapterRegistry + 动态扩展支持
│   │   ├── openai_api.py             # 直连 OpenAI 兼容 API（DeepSeek/Qwen/OpenAI 等）
│   │   ├── dsh.py                    # DeepSeek Harness (`dsh`) CLI 适配器
│   │   ├── codex.py                  # Codex CLI (`codex exec`) 适配器
│   │   ├── claude_code.py            # Claude Code CLI (`claude -p`) 适配器
│   │   ├── native_subagent.py        # 宿主 Agent 原生 Subagent 委派包适配器
│   │   └── custom_cli.py             # 模板化任意自定义 CLI 适配器
│   ├── dispatcher/
│   │   ├── engine.py                 # 调度主引擎：路由 -> 后端执行 -> Schema 校验 -> 状态推进
│   │   └── gates.py                  # 闸门 1/2 交互渲染、审批记录与熔断状态处理
│   ├── scout/
│   │   ├── platforms.py              # GitHub / Gitee / GitCode API 统一客户端 + 从清单导入
│   │   └── dedup.py                  # 对照 SQLite/历史 Excel 去重 + 浅克隆管理
│   ├── evidence/
│   │   ├── code_shot.py              # render_code_shot（Pygments + Playwright）
│   │   ├── web_shot.py               # capture_web_shot（Playwright 双上下文对照）
│   │   ├── http_shot.py              # render_http_shot（左右分栏 HTTP 报文高亮图）
│   │   ├── term_shot.py              # render_term_shot（终端输出高亮图）
│   │   └── templates/                # HTML/CSS 渲染模板（code / http / term）
│   └── reporting/
│       ├── docx_builder.py           # python-docx CNVD 报告生成（支持图文混排与占位符）
│       ├── cnvd_form.py              # CNVD 网页提报表单 .md / .json 导出
│       └── excel_sync.py             # 可选安全备份并追加汇总 Excel
├── skills/
│   ├── dispatcher/master-dispatcher/
│   ├── scout/{ai-agent,web-multitenant,infra-lib,from-list}/
│   ├── triage/{project-worthiness,vuln-worthiness}/
│   ├── audit/{surface-mapper,auth-rbac,file-exec,query-parser}/
│   ├── verify/{docker-official,cli-harness,vm-plan-only}/
│   └── report/cnvd-docx-writer/
└── tests/
    ├── fixtures/                     # 样例 meta.json / audit.json / verify.json / 样例源码
    ├── test_schemas.py
    ├── test_registry_and_adapters.py
    ├── test_dispatcher_state_machine.py
    ├── test_evidence_renderers.py
    └── test_reporting_docx_and_cnvd.py
```

---

## 3. 分阶段开发里程碑

### Milestone 1：核心底座 + 自动出图 + CNVD 双输出（最高 ROI，优先打通）
1. 实现 `core/config.py`、`core/schemas.py`（7 个 Pydantic 模型 + 校验 CLI `auditflow validate`）、`core/state.py`（SQLite 状态机）与 `core/skill_registry.py`。
2. 实现 `backends/`（`local`、`ssh_ubuntu`、`wsl2`）与 `adapters/` 全部抽象及核心适配（`openai_api`、`dsh`、`codex`、`claude_code`、`native_subagent`、`custom_cli`）+ `auditflow doctor` 环境体检命令。
3. 实现 4 个确定性证据渲染器（`code_shot`、`web_shot`、`http_shot`、`term_shot`）及 HTML/CSS 模板（当系统未安装 Playwright 浏览器时提供清晰的安装提示，单元测试支持 mock 渲染或真实渲染可选开关）。
4. 实现 `reporting/docx_builder.py`、`reporting/cnvd_form.py` 与 `reporting/excel_sync.py`。
5. **验收标准**：给定 `tests/fixtures/` 中的样例 `meta.json` + `audit.json` + `verify.json` + 样例源码，运行 `auditflow report` 能一键生成带代码高亮图、HTTP 对比图、终端图的标准 `.docx` 报告以及 `_cnvd_form.md/.json`，且全部单测通过。

### Milestone 2：调度引擎 + 多平台项目发现 + 全套内置 Skills
1. 实现 `dispatcher/engine.py` 与 `dispatcher/gates.py`（完整状态流转、契约校验、Gate 1/2 审批与 `NEEDS_HUMAN_ENV` 熔断）。
2. 实现 `scout/platforms.py`（GitHub / Gitee / GitCode REST API 查询 + 自定义清单导入）与 `scout/dedup.py`（SQLite + 历史 Excel 去重）。
3. 编写 `skills/` 目录下全套内置 Skill 的 `skill.yaml` 与高质量 `SKILL.md`（包含 `dispatcher/master-dispatcher`、4 个 `scout` 子 Skill、2 个 `triage` 评判 Skill、4 个 `audit` 子 Skill、3 个 `verify` 子 Skill、1 个 `report` Skill）。
4. **验收标准**：
   - 使用 mock adapter 跑通从 `scout` -> `Gate 1` -> `surface` -> `audit` -> `Gate 2` -> `verify` -> `report` 的完整状态机端到端测试；
   - 测试验证切换 `pipeline.yaml` 中任一阶段的 `adapter` 或 `skill` 无需修改核心代码即可生效。

### Milestone 3：Docker 隔离验证辅助工具 + 代理/Burp 导流集成 + 文档完善
1. 实现 `verify` 阶段辅助工具脚本：自动读取 `env.yaml` 中的 Docker 代理端口与空闲端口池、写入 `deploy-log.json`、执行有限重试熔断与强制 `docker compose down` 清理；支持可选 `burp_upstream_proxy` 流量导流。
2. 补齐跨机产物拉取命令（`auditflow sync-pull <target> <candidate>` 从 `ssh-ubuntu` 拉取 JSON 与 `evidence/*.png` 到 Windows 本地）。
3. 补齐 CLI 帮助信息、端到端使用示例文档与 CI（GitHub Actions 运行 `pytest` + `ruff`）。

---

## 4. 安全与工程质量红线（开发必守）

- **严禁生成通用攻击武器或面向外部公网目标的自动化利用脚本**：验证与取证模块仅操作本地与隔离实验环境（默认按 `allowed_target_hosts` + `allowed_target_cidrs` 放行 `localhost`、回环、Docker 网桥及 RFC1918 私网段，拒绝向公网主机发包）。
- **严禁硬编码密钥/Token**：所有 API Key、GitHub/Gitee/GitCode Token、SSH 主机名一律从环境变量或未纳入 git 的 `config/env.yaml` 读取，`.gitignore` 必须忽略 `config/env.yaml`、`config/pipeline.yaml` 与 `workspaces/`。
- **代码风格**：类型注解完整、模块职责单一、异常信息清晰可读；提供清晰的 `README.md` 与中文/英文注释便于开源发布。
