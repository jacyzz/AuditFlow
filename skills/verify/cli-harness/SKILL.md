---
name: cli-harness
description: 面向数据库、RPC、CLI 与开源库类非 Web 项目的最小隔离验证与终端取证协议
---

# 非 Web 项目最小隔离验证协议（cli-harness）

适用于数据库（如 TiDB）、RPC/MCP 服务、CLI 工具与底层开源库。

## 验证流程

1. **最小隔离启动或 Harness**：
   - 数据库/RPC/CLI 服务：在本地隔离容器或一次性目录中按官方默认命令启动并记录到 `deploy-log.json`（超过 `max_retries` 立即清理并熔断 `NEEDS_HUMAN_ENV`）。
   - 底层开源库 / SDK：新建独立临时目录编写 20～40 行最小复现单测，仅调用目标库公开 API。
2. **正负向对照与终端取证**：
   - 先运行负向对照（例如低权限用户访问隔离数据被拒、正常输入被拦截），再运行正向触发验证，将真实命令、`stdout`、`exit_code` 与需要标红的 `highlight_patterns` 写入 `verify.json` 的 `terminal_check` 步骤（后续由 `render_term_shot` 自动生成高清终端图）。
3. **强制清理**：测试完成后删除临时库/文件并停止后台服务，在 `cleanup_summary` 如实记录。
