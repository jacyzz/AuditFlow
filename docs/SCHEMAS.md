# AuditFlow 数据契约规范（JSON Schemas）

所有可插拔 Skill 与 Agent Adapter 之间**严格通过以下 7 个 JSON 文件通信**。在 `src/auditflow/core/schemas.py` 中应使用 **Pydantic v2** 实现对应强类型模型并导出标准 JSON Schema。

---

## 1. `meta.json`（Stage 1: `repo-scout` 产出）

记录目标仓库元数据、CNVD 提报基础厂商信息及初筛评分。

```json
{
  "schema_version": "1.0",
  "target_id": "github_icewhaletech_casaos",
  "platform": "github",
  "repo_url": "https://github.com/IceWhaleTech/CasaOS",
  "homepage": "https://www.casaos.io",
  "vendor": "IceWhaleTech",
  "product": "CasaOS",
  "description": "面向个人 NAS 与家庭服务器的个人云管理平台",
  "stars": 37700,
  "license": "Apache-2.0",
  "primary_language": "Go",
  "languages": ["Go", "TypeScript"],
  "default_branch": "main",
  "commit_sha": "0d3b2f444ec0193193cf03eef6d43c6e35b0183e",
  "latest_tag": "v0.4.15",
  "last_commit_at": "2026-10-20T08:00:00Z",
  "deploy_modes": ["official-script", "docker-compose"],
  "project_tier": "popular-high-impact",
  "scout_profile": "web-multitenant",
  "worthiness": {
    "score": 82,
    "deployability_score": 75,
    "cnvd_fit_score": 90,
    "saturation_risk": "medium",
    "reason": "活跃度高、含明确 Web 管理面与文件管理接口，但需注意排除已披露历史 CVE"
  },
  "local_repo_path": "/home/wood/audit-pipeline/workspaces/github_icewhaletech_casaos/repo"
}
```

---

## 2. `surface.json`（Stage 2: `surface-mapper` 产出）

压缩仓库上下文，为深度审计 Agent 提供框架、权限边界与高危入口地图。

```json
{
  "schema_version": "1.0",
  "target_id": "github_icewhaletech_casaos",
  "frameworks": ["echo v4.12.0", "systemd"],
  "runtime_privilege": {
    "default_user": "root",
    "evidence_file": "build/sysroot/usr/lib/systemd/system/casaos.service",
    "notes": "systemd 单元未指定 User=，默认以 uid=0 运行"
  },
  "auth_mechanisms": [
    {
      "name": "JWTWithConfig",
      "file": "route/v1.go",
      "lines": [44, 66],
      "bypass_or_skip_conditions": "c.RealIP() == \"::1\" || c.RealIP() == \"127.0.0.1\""
    }
  ],
  "role_model": ["admin"],
  "entrypoints": [
    { "method": "POST", "path": "/v1/file", "handler": "PostCreateFile", "file": "route/v1/file.go", "line": 430 },
    { "method": "PUT", "path": "/v1/file", "handler": "PutFileContent", "file": "route/v1/file.go", "line": 732 }
  ],
  "static_hotspots": [
    { "tool": "semgrep", "rule_id": "go.path-traversal", "file": "route/v1/file.go", "line": 102, "summary": "ioutil.ReadFile 直接接收 query path" }
  ]
}
```

---

## 3. `audit-disposition.json`（Stage 3 + 闸门 2 决策台账）

参考 Zhulong 的决策台账思想，确保任何未复核/重复/低价值线索都不会混入最终报告。

```json
{
  "schema_version": "1.0",
  "target_id": "github_cskefu_cskefu",
  "audited_at": "2026-11-24T12:00:00Z",
  "audit_adapter": "dsh",
  "audit_model": "deepseek-v4",
  "candidates": [
    {
      "candidate_id": "CAND-01",
      "title_hint": "春松客服 v8 存在未认证创建管理员账号漏洞",
      "category": "auth_bypass",
      "cwe": "CWE-306",
      "severity_estimate": "high",
      "confidence": "high",
      "default_deploy_affected": true,
      "is_duplicate_cve": false,
      "triage_recommendation": "RECOMMEND_VERIFY",
      "triage_reason": "默认部署零前置条件即可匿名创建持久化管理员，CNVD 接收价值极高",
      "human_decision": "APPROVED",
      "status": "VERIFY_APPROVED",
      "audit_file": "candidates/CAND-01/audit.json"
    }
  ]
}
```

> `triage_recommendation` 枚举：`RECOMMEND_VERIFY` | `NEEDS_MANUAL_REVIEW` | `LOW_VALUE_SKIP` | `DUPLICATE_CVE` | `FALSE_POSITIVE`。

---

## 4. `audit.json`（单漏洞结构化审计事实）

既是验证 Agent 的输入，也是 `render_code_shot.py` 自动截代码图与 `cnvd-reporter` 撰写报告的核心事实源。

```json
{
  "schema_version": "1.0",
  "candidate_id": "CAND-01",
  "target_id": "github_cskefu_cskefu",
  "title_hint": "春松客服 v8 存在未认证创建管理员账号漏洞",
  "vuln_type": "认证缺失 / 权限管理不当",
  "cwe": ["CWE-306", "CWE-269"],
  "severity": "高",
  "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
  "cvss_score": 9.8,
  "affected_versions": "v8 OSS（已验证提交 8.1.0-76-g6bda5fef）",
  "default_deploy_affected": true,
  "preconditions": ["默认 docker-compose 部署即可，无需登录或用户交互"],
  "related_cve": null,
  "technical_summary": "LoginController#addAdmin 标注 @Menu(access=true) 允许未登录访问，且未检查系统是否已初始化或管理员是否已存在，直接执行 user.setAdmin(true) 并调用 processLogin 下发会话。",
  "impact_summary": "匿名攻击者可持久化创建管理员账号并接管后台管理功能，读写全部用户、角色、模板及客户业务数据。",
  "code_evidence": [
    {
      "step": 1,
      "file": "contact-center/app/src/main/java/com/cskefu/cc/controller/LoginController.java",
      "start_line": 379,
      "end_line": 396,
      "highlight_lines": [380, 388, 392, 394],
      "analysis": "/addAdmin 标注 access=true 且仅做字段查重，随后直接 setAdmin(true) 并下发登录态。"
    },
    {
      "step": 2,
      "file": "contact-center/app/src/main/java/com/cskefu/cc/interceptor/UserInterceptorHandler.java",
      "start_line": 78,
      "end_line": 84,
      "highlight_lines": [81, 83],
      "analysis": "拦截器对 menu.access() 为真的请求直接令 filter=true 放行。"
    }
  ],
  "verification_plan": {
    "target_type": "web_ui",
    "deploy_mode": "docker-compose",
    "preferred_repro_style": ["browser", "burp_repeater"],
    "negative_control": "未登录访问 /admin/template/index 返回 302 跳转至 /login.html",
    "positive_assertion": "未登录 POST /addAdmin 后返回 302 并 Set-Cookie，库内 admin=1 且可访问 /admin/template/index 返回 200"
  },
  "remediation": {
    "temporary": ["在边界网关/Nginx 阻断外部对 /addAdmin 与 /addAdmin.html 的访问", "审计并清理 cs_user 表中不明管理员账号"],
    "permanent": ["在 LoginController#addAdmin 中增加初始化状态与管理员存在性校验，或关闭公开注册改由管理员后台创建"]
  }
}
```

---

## 5. `deploy-log.json`（Stage 4a: 环境部署与熔断日志）

```json
{
  "schema_version": "1.0",
  "candidate_id": "CAND-01",
  "backend": "ssh-ubuntu",
  "deploy_mode": "docker-compose",
  "deploy_commands": ["docker compose up -d"],
  "proxy_used": "http://127.0.0.1:7890",
  "exposed_base_url": "http://127.0.0.1:18035",
  "precondition_overrides": [],
  "attempts": [
    {
      "attempt": 1,
      "status": "success",
      "duration_sec": 42,
      "healthcheck": "GET /login.html -> 200",
      "error_summary": null
    }
  ],
  "final_status": "READY",
  "teardown_completed": true
}
```

> `final_status` 枚举：`READY` | `NEEDS_HUMAN_ENV` | `ABORTED`。

---

## 6. `verify.json`（Stage 4b/4c: 验证结论、原始证据与截图索引）

```json
{
  "schema_version": "1.0",
  "candidate_id": "CAND-01",
  "verified_by_adapter": "codex",
  "verified_at": "2026-11-24T13:10:00Z",
  "verdict": "DYNAMIC_CONFIRMED",
  "realistic_assessment": {
    "default_deploy_exploitable": true,
    "effective_privilege": "platform_admin",
    "realistic_notes": "默认 docker-compose 部署即可复现，无需额外配置；创建账号为持久化 admin=1"
  },
  "steps": [
    {
      "step_no": 1,
      "title": "未登录访问管理端（负向对照）",
      "kind": "web_browser",
      "url": "http://127.0.0.1:18035/admin/template/index",
      "expected": "HTTP 302 跳转 /login.html",
      "observed": "HTTP 302 -> http://127.0.0.1:18035/login.html",
      "screenshot": "evidence/02_neg_control_redirect.png"
    },
    {
      "step_no": 2,
      "title": "未认证提交注册创建管理员",
      "kind": "http_exchange",
      "raw_request": "POST /addAdmin HTTP/1.1\nHost: 127.0.0.1:18035\nContent-Type: application/x-www-form-urlencoded\n\nusername=labadmin_test&mobile=13900000001&email=labadmin@example.com&password=LabPass1234",
      "raw_response": "HTTP/1.1 302\nLocation: http://127.0.0.1:18035/...\nSet-Cookie: authorization=...",
      "highlight_response_patterns": ["HTTP/1.1 302", "Set-Cookie: authorization="],
      "screenshot": "evidence/03_http_add_admin.png"
    },
    {
      "step_no": 3,
      "title": "核查数据库管理员标志与后台页面访问",
      "kind": "terminal_check",
      "command": "docker compose exec -T mysql mysql -uroot -p123456 -N -e \"select USERNAME,admin,superadmin from cosinee.cs_user where USERNAME='labadmin_test';\"",
      "stdout": "labadmin_test\t1\t0",
      "highlight_patterns": ["labadmin_test\t1"],
      "screenshot": "evidence/04_db_admin_flag.png"
    }
  ],
  "evidence_manifest": {
    "app_home": "evidence/00_app_home.png",
    "code_shots": [
      { "step": 1, "path": "evidence/01_code_step1_LoginController.png" },
      { "step": 2, "path": "evidence/01_code_step2_UserInterceptorHandler.png" }
    ],
    "verify_shots": [
      { "step_no": 1, "path": "evidence/02_neg_control_redirect.png" },
      { "step_no": 2, "path": "evidence/03_http_add_admin.png" },
      { "step_no": 3, "path": "evidence/04_db_admin_flag.png" }
    ],
    "manual_placeholders_needed": []
  },
  "cleanup_summary": "测试账号已删除，测试容器已执行 docker compose down 销毁。"
}
```

---

## 7. `cnvd-form.json`（Stage 5: CNVD 网页提报表单结构化输出）

供 `cnvd-reporter` 同步导出为 `_cnvd_form.md`（按 CNVD 官网提报页栏位顺序排版，直接复制粘贴）并写入汇总台账：

```json
{
  "schema_version": "1.0",
  "vuln_title": "春松客服 v8 存在未认证创建管理员账号漏洞",
  "vendor": "北京华夏春松科技有限公司",
  "product": "春松客服（CSKeFu）v8 OSS",
  "affected_versions": "v8 OSS（8.1.0-76-g6bda5fef）",
  "homepage": "https://www.cskefu.com",
  "repo_url": "https://github.com/cskefu/cskefu",
  "vuln_category": "应用程序漏洞 / 权限绕过",
  "cwe": "CWE-306",
  "severity": "高",
  "vuln_description": "...",
  "vuln_impact": "...",
  "repro_summary": "...",
  "remediation_suggestion": "...",
  "reference_links": ["https://github.com/cskefu/cskefu"],
  "attachment_docx": "春松客服 v8 存在未认证创建管理员账号漏洞.docx"
}
```
