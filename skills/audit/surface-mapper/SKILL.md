---
name: surface-mapper
description: 快速测绘开源仓库技术栈、运行权限、路由表、鉴权中间件与高危静态热点，产出 surface.json
---

# 项目安全面测绘（surface-mapper）

在进入深度源码审计之前，先对 `workspaces/<target>/repo/` 做一次结构化安全测绘，输出 `surface.json`，避免深度审计盲扫大仓库。

## 测绘步骤

1. **框架与部署权限识别**：
   - 检查 `go.mod`、`pom.xml`、`package.json`、`pyproject.toml`、`Dockerfile`、`docker-compose.yml`、`*.service`（systemd）。
   - 记录实际运行用户（例如容器是否未设 `USER`、systemd 是否未设 `User=` 导致以 `root` 运行）。
2. **认证与授权边界提取**：
   - 定位全局拦截器、Middleware、Filter、Spring Security `SecurityFilterChain`、JWT 校验器、Skipper 白名单与权限注解定义。
   - 明确系统角色模型（是否仅有单一 admin，还是具备多租户/普通成员/匿名访客层级）。
3. **入口清单与静态热点**：
   - 列出高敏感入口：初始化/注册、用户/角色管理、系统配置读写、文件上传/下载/读写、模板/表达式/SQL 执行、外部 URL 抓取、内部 RPC。
   - 若执行环境装有 `semgrep` 或其他本地静态规则扫描器，可运行后合并命中项至 `static_hotspots`。
4. 严格输出符合 `docs/SCHEMAS.md` 的 `surface.json`（所有文件路径必须为仓库相对路径且行号真实存在）。
