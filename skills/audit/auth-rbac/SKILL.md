---
name: auth-rbac
description: 认证绕过、白名单不一致、未初始化接口与垂直/水平越权专项源码审计
---

# 认证与权限控制专项审计（auth-rbac）

围绕目标仓库源码与 `surface.json`，系统排查认证鉴权与访问控制缺陷，输出结构化 `audit-disposition.json` 与单候选 `candidates/<id>/audit.json`。

## 一、核心排查清单

1. **全局鉴权拦截器与白名单一致性**
   - 检查拦截器/Filter/Middleware 的放行逻辑与路由匹配层是否使用不同路径规范化方式（如 `getRequestURI()` vs `getServletPath()`、分号路径参数 `;`、URL 编码 `%XX`、尾斜杠）。
   - 检查“回环/本机免鉴权”逻辑（Skipper）是否错误信任可伪造的请求头（如 `X-Forwarded-For` / `X-Real-IP` / `c.RealIP()`），以及上游网关对 IPv4/IPv6（如 `[::1]` 方括号）的清洗是否完整。
2. **初始化、注册与公开接口暴露**
   - 检查 `/init`、`/setup`、`/register`、`/addAdmin` 等接口是否在系统初始化后仍可匿名反复调用，是否无条件赋予高权限角色或覆盖已有账户。
   - 检查未鉴权公开接口（如 `/api/config/get`、分享链接 Token）是否缺少 key 白名单或权限过滤，导致泄露支付私钥、API Key、内部凭据或未公开资源 ID。
3. **垂直越权与水平越权（RBAC / 多租户边界）**
   - 检查权限注解（如 `@Menu(admin=true)`、`@RequireRole`）是否真的被拦截器消费，是否存在注解写了但代码从未校验的情况。
   - 检查社区版/默认实现的 `checkAuth()`、`hasPermission()` 是否恒返回 `true`。
   - 检查多租户/多用户场景下，读/写/删接口是否校验资源归属（`tenant_id` / `owner_id`）。

## 二、反误报与质量自检（必做）

1. **追踪完整调用链**：每个候选必须给出精确的相对文件路径、`start_line`、`end_line` 与 `highlight_lines`，严禁编造行号或函数名。
2. **核查上游与默认配置**：确认请求是否被网关、全局中间件、Spring Security 链或默认关闭的功能开关阻断；如实填写 `default_deploy_affected` 与 `preconditions`。
3. **历史 CVE / 补丁去重**：结合 git log、注释与已知安全公告，判断是否为已修复问题或补丁不完整的新变体，如实写入 `is_duplicate_cve` 与 `related_cve`。
4. **评估现实价值**：如果目标系统只有单一管理员角色且该功能属于管理员预期能力，必须在 `triage_reason` 中明确指出并降低置信度/优先级。

## 三、输出要求

- 严格按 `docs/SCHEMAS.md` 生成 `candidates/<candidate_id>/audit.json` 与顶层 `audit-disposition.json`。
- `audit.json` 中必须包含可落地的 `verification_plan`（含 `negative_control` 负向对照与 `positive_assertion` 正向断言）以及区分临时缓解与正式修复的 `remediation`。
