---
name: query-parser
description: SQL/表达式/模板注入与解析器边界专项源码审计
---

# 查询构造、注入与解析器边界审计（query-parser）

围绕目标仓库源码与 `surface.json`，重点排查外部可控输入拼接进数据库查询、模板引擎、表达式求值或特权内部会话的路径。

## 核心排查清单

1. **SQL 拼接与内部特权执行**：
   - 排查 `fmt.Sprintf`、字符串 `+` 拼接、MyBatis `${}`、原生 `raw()` / `text()` 查询以及解析器语法规则中未转义字面量进入 SQL 的路径。
   - 特别关注内部管理语法或后台任务是否通过特权内部会话（如空用户内部会话、跳过权限表校验的 executor）执行用户输入拼接语句。
2. **模板注入 / 表达式注入 / 反序列化**：
   - 排查 SpEL、OGNL、MVEL、Jinja2、Pug、Go `text/template` 与反序列化入口是否接收不可信用户输入。
3. **反误报自检与输出**：
   - 核查上游是否存在参数化绑定、严格白名单枚举或仅限已具备完全等同权限的超级管理员调用。
   - 按 `docs/SCHEMAS.md` 输出精确行号的 `candidates/<id>/audit.json` 与 `audit-disposition.json`，并在 `verification_plan` 中使用无害验证对照（如只读低权限账号 vs 受保护表隔离测试）。
