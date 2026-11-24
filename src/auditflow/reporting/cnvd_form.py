from pathlib import Path

from auditflow.core.paths import atomic_write
from auditflow.core.schemas import Audit, CnvdForm, Meta, Verify, save_artifact

VERDICT_LABELS = {
    "DYNAMIC_CONFIRMED": "动态验证已确认",
    "STATIC_ONLY": "源码审查",
    "NOT_REPRODUCED": "未复现",
    "INCONCLUSIVE": "验证结论未定",
    "NEEDS_HUMAN_ENV": "验证环境待人工处理",
}


def make_form(meta: Meta, audit: Audit, verify: Verify | None, attachment: str) -> CnvdForm:
    summary = [VERDICT_LABELS[verify.verdict] if verify else "源码审查"]
    if verify:
        summary.extend(
            f"{step.title}：{step.observed}" for step in sorted(verify.steps, key=lambda s: s.step_no)
            if step.observed
        )
    if audit.preconditions:
        summary.append("前置条件：" + "；".join(audit.preconditions))
    remedies = [f"临时缓解：{text}" for text in audit.remediation.temporary]
    remedies.extend(f"正式修复：{text}" for text in audit.remediation.permanent)
    return CnvdForm(
        vuln_title=audit.title_hint,
        vendor=meta.vendor,
        product=meta.product,
        affected_versions=audit.affected_versions,
        homepage=meta.homepage,
        repo_url=meta.repo_url,
        vuln_category=audit.vuln_type,
        cwe=audit.cwe[0],
        severity=audit.severity,
        vuln_description=audit.technical_summary,
        vuln_impact=audit.impact_summary,
        repro_summary="\n".join(summary),
        remediation_suggestion="\n".join(remedies) or "待补充",
        reference_links=[meta.repo_url],
        attachment_docx=attachment,
    )


def export_form(form: CnvdForm, stem: Path) -> tuple[Path, Path]:
    markdown = stem.parent / f"{stem.name}_cnvd_form.md"
    json_file = stem.parent / f"{stem.name}_cnvd_form.json"
    fields = [
        ("漏洞名称", form.vuln_title),
        ("涉及厂商", form.vendor),
        ("受影响产品", form.product),
        ("受影响版本", form.affected_versions),
        ("官网地址", str(form.homepage) if form.homepage else "未提供"),
        ("项目地址", str(form.repo_url)),
        ("漏洞类型", f"{form.vuln_category}（{form.cwe}）"),
        ("危害等级", form.severity),
        ("漏洞描述", form.vuln_description),
        ("漏洞危害", form.vuln_impact),
        ("验证方式简述", form.repro_summary),
        ("修复建议", form.remediation_suggestion),
        ("参考链接", "\n".join(f"- {link}" for link in form.reference_links)),
        ("附件", form.attachment_docx),
    ]
    text = "# CNVD 提报表单\n\n" + "\n".join(f"## {label}\n\n{value}\n" for label, value in fields)
    atomic_write(markdown, text.encode("utf-8"))
    save_artifact(json_file, form)
    return markdown, json_file
