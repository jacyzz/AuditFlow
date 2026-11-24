---
name: project-worthiness
description: 闸门 1 项目价值预判 Skill：综合热门度、重复风险、部署难易度与 CNVD 适配度打分排序
---

# 项目价值评判（triage/project-worthiness）

读取 `meta.json` 对候选开源项目进行多维度打分，更新 `meta.json` 的 `worthiness` 字段，供 Gate 1 表格排序展示。

## 评判维度（0–100 分）

1. **`cnvd_fit_score`（CNVD 适配度）**：是否具备明确自托管服务端形态、真实企业/个人部署场景与清晰厂商/维护者信息；纯教学 Demo、归档停更仓库扣分。
2. **`deployability_score`（可部署/可验证性）**：是否自带官方 `docker-compose.yml`、官方预构建镜像或清晰单机启动命令（高分）；强依赖多台云服务或复杂商业闭源中间件（低分）。
3. **`saturation_risk`（红海重复风险：`low` / `medium` / `high`）**：超高 Star 且近期已有大量公开 CVE 的项目标为 `high`（出洞率低但单洞价值大，需在 `reason` 中提醒聚焦新提交/新特性或补丁绕过）；中等热门活跃项目通常为 `low`/`medium`。
4. 综合得出 `score` 与简洁中文 `reason`，输出合规 `meta.json`。
