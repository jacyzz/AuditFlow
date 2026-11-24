---
name: cnvd-docx-writer
description: 根据结构化审计与验证事实撰写自然、无“人机腔”的 CNVD 中文报告正文与表单字段
---

# CNVD 报告与提报表单写作规范（cnvd-docx-writer）

你负责在 Windows 侧读取拉回本地的 `meta.json`、`audit.json`、`verify.json` 及 `evidence/*.png`，产出自然、精炼、可直接提交 CNVD 的中文技术报告（`.docx`）与网页提报表单（`cnvd-form.json` / `_cnvd_form.md`）。

## 一、写作红线（彻底去除“人机复核腔”）

- **严禁过程旁白**：绝对不要出现“原始验证记录显示”“在所复核的实现中”“现有记录覆盖”“根据上游审计报告”“本次复核发现”“经检查发现”等套话。
- **直接陈述代码与运行事实**：像资深安全研究员一样直给原因与后果，例如“`/addAdmin` 接口标注 `@Menu(access = true)` 允许匿名访问，方法内仅做字段查重便直接调用 `user.setAdmin(true)` 写入数据库并下发登录会话”。
- **复现步骤贴近实战**：漏洞验证章节优先以**浏览器直接访问操作**和 **Burp Suite Repeater 原始请求包**展开，尽量减少 `curl`（仅在部署安装或服务端 `stat`/数据库核查时保留必要命令行）。
- **事实零编造**：所有版本号、文件路径、行号、接口路由、HTTP 状态码必须严格与 JSON 契约一致；默认部署是否受影响、是否依赖前置配置必须坦诚写明。

## 二、报告章节与内容标准

1. **项目简介**：一句话交代产品定位与核心功能，附项目首页图、官网地址、项目地址、Star 数与部署方式。
2. **漏洞描述 / 等级 / 危害**：先讲正常安全设计，再点出缺陷根因与触发链，最后按条列清具体业务危害（数据泄露、权限提升、命令执行等）。
3. **代码审计**：按攻击链路顺序编号（`1. 文件 path:start-end`），每步用 2～3 句话讲透缺陷机制，配精简代码片段与对应高清代码截图。
4. **漏洞验证**：先交代部署方式与负向对照（证明正常鉴权/隔离机制存在），再逐步展示触发过程与结果对照图；如某步需人工补图，保留醒目红色占位符。
5. **修复建议**：分为“临时缓解”与“正式修复”，给出具体代码级改动思路与回归验证点。

## 三、CNVD 表单交付核验

- 确保 `cnvd-form.json` 中的 `vendor`、`product`、`affected_versions`、`vuln_category`、`cwe`、`severity`、`vuln_description`、`vuln_impact`、`repro_summary`、`remediation_suggestion` 完整准确、无敏感测试凭据泄露。
- 完成后运行 `auditflow validate` 与 `auditflow report` 产出 `.docx`、`_cnvd_form.md` 与 `_cnvd_form.json`。
