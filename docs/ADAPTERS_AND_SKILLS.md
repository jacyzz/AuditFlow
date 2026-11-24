# 可插拔 Agent 适配器、Skill 注册表与调度 Agent 规范

本文档定义如何让 **任意已有 Agent（Antigravity、Claude Code、Codex、DeepSeek Harness `dsh`、OpenAI 兼容 API、原生 Subagent、自定义 CLI）** 与 **任意自定义 Skill** 无缝接入 AuditFlow，并在任意阶段自由替换。

本文保留原始设计。当前内置适配器写出人工交接包，执行后端提供受限的产物读取，当前入口见 [README](../README.md)。

---

## 1. 可插拔 Agent Adapter 统一接口

所有 Agent 适配器均继承同一抽象基类 `BaseAgentAdapter`（位于 `src/auditflow/adapters/base.py`）：

```python
from abc import ABC, abstractmethod
from pathlib import Path
from pydantic import BaseModel

class AdapterRequest(BaseModel):
    stage: str                      # scout | surface | audit | verify | report
    skill_path: Path                # 选定 Skill 的 SKILL.md 路径
    workspace_dir: Path             # 目标工作区路径（本地或远端路径）
    input_files: dict[str, Path]    # 上游契约文件，如 {"meta": ..., "surface": ...}
    output_file: Path               # 期望落盘的目标契约 JSON 路径
    extra_instructions: str = ""    # 本次运行补充参数（如目标类别、代理配置）
    timeout_sec: int = 900
    env_vars: dict[str, str] = {}

class AdapterResult(BaseModel):
    ok: bool
    adapter_name: str
    model_used: str | None = None
    output_file: Path | None = None
    stdout_log: str = ""
    stderr_log: str = ""
    trajectory_path: Path | None = None
    duration_sec: float = 0.0
    error_message: str | None = None

class BaseAgentAdapter(ABC):
    name: str

    @abstractmethod
    def check_health(self) -> tuple[bool, str]:
        """供 `auditflow doctor` 检测工具/API 是否可用。"""

    @abstractmethod
    def run(self, req: AdapterRequest, backend: "BaseExecutionBackend") -> AdapterResult:
        """通过指定执行后端运行该 Agent，并确保目标 output_file 落盘。"""
```

### 内置适配器清单与接入方式

| Adapter 名称 | 底层执行方式 | 典型适用阶段 | 备注 |
|---|---|---|---|
| `openai-api` | Python `httpx` 直连任意 OpenAI 兼容端点（DeepSeek / Qwen / OpenAI / 本地 Ollama） | `triage`、`meta` 补全、单步分类与评分 | 高并发、低成本；支持 Structured Outputs / JSON Mode |
| `dsh` | 执行 `dsh`（DeepSeek Harness）非交互任务命令，支持挂载自定义模型配置与插件 | `surface-mapper`、`deep-audit` | 自带 append-only 轨迹日志，自动记录 `trajectory_path` 方便复盘 |
| `codex` | 通过后端执行 `codex exec --cd <workspace> ...` | `deep-audit`（复核）、`sandbox-verify` | 工程执行与容器排错能力强；通过 Prompt 约束只输出结构化 JSON 事实 |
| `claude-code` | 通过后端执行 `claude -p "<prompt>" --output-format json` | `deep-audit`、`report` | 适合长上下文源码追踪与高质量技术写作 |
| `native-subagent` | **无外部 CLI 依赖**：返回结构化 Prompt Packet，由当前对话宿主（如 Antigravity / Claude Code）直接通过自身 Subagent 执行 | 任意阶段（尤其 `report`、`triage`、MVP 阶段） | 实现“纯 Agent 驱动”与零额外依赖快速启动 |
| `custom-cli` | 读取配置中的命令模板（如 `my-agent --skill {skill} --in {input} --out {output}`） | 任意阶段 | 零代码接入任何未来出现的新 Agent CLI |

### 注册机制（Plugin Registry）

- 内置适配器自动注册于 `AdapterRegistry`；
- 支持通过 `pyproject.toml` 的 `entry_points["auditflow.adapters"]` 或 `config/pipeline.yaml` 的 `custom_adapters` 动态扩展新适配器；
- 调度层只通过字符串名称（例如 `adapter: dsh`）解析适配器，**切换 Agent 只需改配置文件的一行**。

---

## 2. 可插拔 Execution Backend 统一接口

执行后端负责屏蔽“命令跑在 Windows 本地、SSH 到 Ubuntu2404 还是本机 WSL2”的差异：

```python
class BaseExecutionBackend(ABC):
    name: str  # local | ssh-ubuntu | wsl2

    @abstractmethod
    def run_cmd(self, cmd: str, cwd: str | None = None, env: dict | None = None, timeout: int = 300) -> CmdResult: ...

    @abstractmethod
    def pull_file(self, remote_path: str, local_path: Path) -> None: ...

    @abstractmethod
    def push_file(self, local_path: Path, remote_path: str) -> None: ...

    @abstractmethod
    def check_health(self) -> tuple[bool, str]: ...
```

- `ssh-ubuntu`：通过 OpenSSH `ssh` / `scp` 连接 `env.yaml` 中配置的 Host（如 `Ubuntu2404`），支持多路复用与超时控制。
- `wsl2`：通过 `wsl -d <distro> -- bash -lc ...` 在 WSL2 原生 ext4 目录内执行命令与 Docker。
- `local`：直接在本机子进程运行（常用于 Windows 侧的 `cnvd-reporter`、`triage`、API 脚本）。

---

## 3. 可插拔 Skill 规范

每个 Skill 是 `skills/<stage>/<skill-name>/` 下的独立目录，包含：

```text
skills/<stage>/<skill-name>/
├── skill.yaml          # 机器可读清单（声明所属阶段、输入/输出契约、兼容类型、默认脚本）
├── SKILL.md            # 给 Agent 阅读的标准化操作手册（目标、约束、禁止项、输出要求）
└── scripts/            # 可选：确定性辅助脚本（如 API 抓取、规则扫描、格式渲染）
```

### `skill.yaml` 规范示例

```yaml
name: scout/ai-agent
stage: scout
version: "1.0.0"
description: "在 GitHub/Gitee/GitCode 按 AI Agent / MCP / RAG 特征发现与初筛高价值开源目标"
target_categories: ["ai-agent", "mcp-server", "rag-platform"]
inputs:
  - config/env.yaml
outputs:
  - meta.json
recommended_adapter: openai-api
deterministic_entrypoint: scripts/scout_ai_agent.py
```

### 内置 Skill 族清单（全部支持同阶段热切换）

1. **`skills/dispatcher/`**
   - `master-dispatcher`：供 Windows 侧 Antigravity / Claude Code 加载的总控 Skill，定义完整的跨阶段调度、闸门暂停交互与异常处理协议。
2. **`skills/scout/`**
   - `ai-agent`：AI Agent / MCP Server / RAG 工作台类筛选策略
   - `web-multitenant`：多租户后台 / 客服 / BI / 知识库类筛选策略
   - `infra-lib`：高传播底层组件 / 数据库 / 网关 / 开源库类筛选策略
   - `from-list`：导入用户手工提供的仓库清单（URL / Markdown / Excel）
3. **`skills/triage/`**
   - `project-worthiness`：闸门 1 预判——结合热度与“被扫烂风险”、活跃度、部署难易度、历史台账去重打分
   - `vuln-worthiness`：闸门 2 预判——评估默认部署可达性、权限边界价值、CNVD 收录匹配度与历史 CVE 去重
4. **`skills/audit/`**
   - `surface-mapper`：技术栈、进程权限、路由与鉴权边界测绘 + Semgrep 等轻量静态初筛
   - `auth-rbac`：认证绕过、白名单与路由规范化不一致、未初始化接口、垂直/水平越权专项审计
   - `file-exec`：路径穿越、任意文件读写/上传、命令与工具调用边界专项审计
   - `query-parser`：SQL/模板/表达式注入、解析器与边界处理专项审计
5. **`skills/verify/`**
   - `docker-official`：官方 `docker-compose` / 镜像隔离部署（含代理端口注入、部署日志记录、严格重试熔断）
   - `cli-harness`：面向数据库、RPC、CLI、开源库的最小隔离验证工程与终端取证
   - `vm-plan-only`：面向强 `systemd` / 宿主机依赖项目的官方隔离 VM 方案生成与半自动取证
6. **`skills/report/`**
   - `cnvd-docx-writer`：读取 `meta.json` + `audit.json` + `verify.json` + `evidence/*.png`，按去人机感规范生成 CNVD `.docx` 与表单字段文件

---

## 4. Dispatcher Agent 交互与闸门协议

当你在主 Agent（如 Antigravity）中通过对话启动流水线时，Dispatcher 严格遵守以下行为协议：

1. **配置优先**：先读取 `config/pipeline.yaml` 与 `config/env.yaml`，确认本轮选用的 Skill 组合与 Agent 绑定，向用户简述本轮执行计划。
2. **闸门 1 必停（可由 `--auto-approve-gate1` 关闭）**：展示按 `worthiness.score` 排序的目标 Markdown 表格（含平台、Star、部署方式、饱和度风险、推荐理由），等待用户回复勾选编号后才执行克隆与审计。
3. **闸门 2 必停**：展示 `audit-disposition.json` 汇总表（含候选 ID、标题、默认部署是否受影响、重复 CVE 检查、置信度、推荐结论），等待用户勾选后才触发验证 Agent 起隔离环境。
4. **熔断直报**：一旦 `deploy-log.json` 返回 `NEEDS_HUMAN_ENV`，立即展示失败原因与最后日志，询问用户“手动修复环境后继续 / 跳过验证仅输出静态草稿 / 放弃该候选”。
5. **契约守门**：任何 Agent 产出的 JSON 必须经过 `auditflow validate` 校验通过后才允许进入下一阶段，杜绝下游因格式残缺崩溃。
