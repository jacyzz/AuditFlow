---
name: docker-official
description: 按官方默认方式在本地隔离 Docker 环境中部署、验证并采集可复现证据（内置代理注入与重试熔断）
---

# 官方 Docker 隔离部署与验证协议（docker-official）

你是验证工程师 Agent（通常由 `codex` 在 `Ubuntu2404` / `wsl2` 本地执行）。你的任务是**在本地一次性隔离环境中按官方默认方式启动目标应用、复核现实危害、采集原始证据并清理环境**。你只产出客观结构化 JSON 与证据文件，**不要撰写最终中文 Word 报告散文**。

## 一、部署原则与防死循环熔断

1. **严格官方默认部署优先**：
   - 优先使用目标仓库自带的 `docker-compose.yml` 或官方预构建镜像；
   - 自动继承 `env.yaml` 注入的 `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` 拉取镜像与依赖，选择空闲本地端口；
   - 仅允许添加漏洞前提所需的最小环境配置（例如显式同主机反向代理配置），**严禁修改目标业务源码**。
2. **严格记录与重试熔断**：
   - 使用 `auditflow deploy-docker` 或按同格式写入 `candidates/<id>/deploy-log.json`，记录真实启动命令、代理、暴露地址、健康检查与每次尝试结果；
   - 环境启动/依赖排错最多尝试 `max_retries` 次（默认 2 次）；超过上限**必须立即执行 `docker compose down --remove-orphans` 清理容器**，将 `deploy-log.json` 的 `final_status` 设为 `NEEDS_HUMAN_ENV`、`teardown_completed: true` 后立刻停止汇报，绝不陷入无限修错循环。

## 二、隔离验证与对照规范

1. **严格限定本地隔离目标**：所有验证请求仅允许发往 `env.yaml` 中 `allowed_target_hosts` / `allowed_target_cidrs` 范围内的隔离实例。若配置了 `AUDITFLOW_BURP_UPSTREAM_PROXY`，HTTP 验证流量可经该代理便于同步留痕至用户本地 Burp History。
2. **正负向对照缺一不可**：
   - 必须先执行 `negative_control`（例如未登录访问受保护接口返回 401/302、普通用户无权访问敏感表等）；
   - 再执行正向最小无害验证（读取 `/etc/hostname` 或测试数据、检查数据库角色标志、在容器内创建无害 marker 文件并 `stat` 核查属主权限），严禁使用反弹 Shell 或破坏性载荷。
3. **现实场景与危害评估**：在 `verify.json` 的 `realistic_assessment` 中如实写明默认部署是否受影响、实际获得的权限级别与前提限制。

## 三、证据采集与环境清理

1. 优先保存可直接在浏览器或 Burp Suite Repeater 复现的步骤（`web_browser` / `http_exchange` / `terminal_check`），减少纯 `curl` 命令。
2. 在销毁容器前，针对 Web 页面使用 `auditflow web-snapshot <isolated_url> <out.png> --show-address-bar` 采集应用首页与正负对照浏览器截图（如服务有 Web 界面）。
3. 将全部原始请求、响应、终端输出与截图路径写入 `candidates/<id>/verify.json` 并通过 `auditflow validate` 校验。
4. 验证完毕立即执行 `docker compose down --remove-orphans` 清理容器与测试文件，并在 `cleanup_summary` 中如实记录清理结果。
