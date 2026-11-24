---
name: file-exec
description: 路径穿越、任意文件读写/上传、命令拼接与工具调用边界专项源码审计
---

# 文件操作与命令执行边界专项审计（file-exec）

围绕目标仓库源码与 `surface.json`，追踪所有外部输入进入文件系统 API、进程执行 API 与模板/沙箱工具的完整数据流。

## 一、核心排查清单

1. **任意文件读/写/删/上传与路径穿越**
   - 检查所有文件读取、下载、图片预览、创建、覆盖、分片上传与解压入口（`os.Open`、`ReadFile`、`WriteFile`、`http.ServeFile`、`Path.join`、`send_file` 等）。
   - 核查是否缺失根目录白名单、是否未做 `filepath.Clean` / `realpath` 符号链接解析、是否存在“读路径与写路径来源不对称”（例如读路径来自请求参数、写路径来自文件内容字段）。
   - 检查运行权限（Docker 容器用户、`systemd` 单元是否未设 `User=` 导致以 `root` 运行），明确可读写 `/etc/cron.d/`、`/root/.ssh/`、应用认证库等真实危害。
2. **命令注入、RPC 与 AI Agent 工具执行边界**
   - 检查 `exec.Command("sh", "-c", ...)`、`os.system`、`subprocess(..., shell=True)`、`eval`/`exec` 是否存在未转义参数拼接。
   - 针对 AI Agent / MCP Server / 工作流平台，检查内部 RPC/工具执行器端口是否对外暴露、是否缺失认证、工具参数是否能绕过沙箱读写宿主文件或执行任意脚本。

## 二、反误报自检与输出要求

1. 核对前置认证要求（未认证 / 普通用户 / 仅管理员），如仅管理员可用需明确说明权限边界（例如管理员是否本身就具备容器/命令等价能力）。
2. 每条 `code_evidence` 必须指向真实存在的文件与精确行号，并标注最关键的 `highlight_lines`。
3. 严格输出符合 `docs/SCHEMAS.md` 的 `candidates/<candidate_id>/audit.json` 与 `audit-disposition.json`，确保 `verification_plan` 优先采用无害验证目标（如读 `/etc/hostname`、写隔离容器内临时 marker 文件并验证属主权限）。
