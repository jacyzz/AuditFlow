# AuditFlow v2.0 Studio 架构与交互设计

本方案在 AuditFlow v1.0 的契约底座、真实多 Agent 适配器、Docker 熔断隔离与四类确定性取证渲染器之上，吸收 `Dimo`、`dsh-ai-team`（文渊阁）、`AutoCVE`、`magpie` 与 `open-multi-agent` 的最佳实践，升级为**独立开源多 Agent 安全审计与 CNVD 披露工作台**。

---

## 1. 核心升级点

1. **三栏对话式工作台（Chat-First Workbench）**
   - 借鉴 `文渊阁` 与 `Dimo`：不再要求用户手动复制粘贴命令行，主界面直接提供类似 Agent 的自然语言对话框。
   - 后端内置轻量 **ReAct Tool-Calling Coordinator** + **SSE 流式推送**，会话持久化至 SQLite；支持 `@Agent` 点名临时接管、`/skill` 调用，并在 Gate 1 / Gate 2 节点于对话流中直接渲染**内联审批卡片**，点一下即继续推进。
2. **Agent 能力档案与原生配置探测（Dimo / Magpie 路线）**
   - 自动扫描本机及远端（Ubuntu/WSL2）已安装的 Agent（`Codex`、`Claude Code`、`DeepSeek Harness (dsh)`、`Antigravity CLI`、`Gemini CLI`、`OpenCode`、OpenAI 兼容 API），**只读展示其原生配置与安装路径，绝不篡改用户原生配置**。
   - 为每个 Agent 建立**能力画像（Capability Profile）**（`deep_reasoning`、`docker_verify`、`bulk_triage`、`cn_writing`、`tool_use`、成本档位、默认运行主机）。
   - **异构互审机制**：系统内置 5 大安全审计岗位（侦察 / 主审 / 异构复核 / 验证工程师 / 报告主笔），支持一键“按能力自动最优分配”，并自动让复核岗位避开主审模型以降低单模型盲区。
3. **可视化编排画布（Workflow Studio）**
   - 以现代可视化节点连线画布替代传统表单，直观呈现 8 阶段流水线、Gate 1/2 门禁节点与异构互审标识；点击任意节点在右侧 Inspector 调整绑定 Agent（含能力匹配分）、Skill 多选、执行主机与熔断参数。
4. **Skill Studio（在线预览 / 编辑 / 新建 / 复制 / 导入）**
   - 完整支持浏览内置与自定义 Skill、在线 Markdown 渲染预览、双栏源码编辑（`skill.yaml` + `SKILL.md`）、向导新建 Skill、导入本地 `.md`；自定义 Skill 落盘于 `skills_custom/` 覆盖层（优先级 `custom > builtin`），内置 Skill 始终安全可一键恢复。
5. **现代前后端分离 + 单命令启动**
   - 后端：`FastAPI` + `uvicorn` + `SSE`；
   - 前端：`React` + `TypeScript` + `Tailwind CSS` + `Vite` + `Lucide Icons`（亮/暗双主题）；
   - 发布形态：前端构建产物 `dist/` 内置打包进 `src/auditflow/ui/dist/`，终端用户依然只需一条 `auditflow ui` 即可零配置启动完整现代控制台。
