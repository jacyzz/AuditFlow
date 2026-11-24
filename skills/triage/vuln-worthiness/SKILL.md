---
name: vuln-worthiness
description: 闸门 2 漏洞价值预判 Skill：复核默认部署可达性、权限边界价值与历史 CVE 去重，输出筛选建议
---

# 漏洞候选价值评判（triage/vuln-worthiness）

读取 `audit-disposition.json` 与各个 `candidates/<id>/audit.json`，对每条候选给出客观 `triage_recommendation` 与 `triage_reason`，帮助负责人在 Gate 2 快速勾选值得投入隔离验证的高价值项。

## 评判标准

1. **`RECOMMEND_VERIFY`（优先进入隔离验证）**：默认部署可达（或具备常见真实部署前提），具备清晰跨信任边界收益（匿名访问敏感管理面、低权限垂直/水平越权、任意文件读写/命令执行、未授权密钥泄露），且未与历史已修复 CVE 重复。
2. **`NEEDS_MANUAL_REVIEW`**：前提条件较特殊（例如依赖特定反向代理或非默认配置），需负责人权衡投入产出后再决定是否搭环境。
3. **`LOW_VALUE_SKIP` / `DUPLICATE_CVE` / `FALSE_POSITIVE`**：仅单一管理员预期功能（无真实提权边界）、已被历史补丁完整修复或调用链不可达的候选。
4. 严禁修改 `candidate_id` 列表或擅自写入 `human_decision: APPROVED`（审批只能由负责人通过 Gate 2 录入）。
