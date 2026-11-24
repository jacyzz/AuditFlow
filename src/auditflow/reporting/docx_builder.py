from io import BytesIO
from pathlib import Path

from docx import Document
from docx.document import Document as WordDocument
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image

from auditflow.core.paths import atomic_write, contained_path
from auditflow.core.schemas import Audit, DeployLog, HttpStep, Meta, TermStep, Verify
from auditflow.evidence.code_shot import code_excerpt
from auditflow.evidence.term_shot import strip_terminal_formatting
from auditflow.reporting.cnvd_form import VERDICT_LABELS


def _style(document: WordDocument) -> None:
    for name, size in (("Normal", 11), ("Title", 18), ("Heading 1", 15), ("Heading 2", 12)):
        style = document.styles[name]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.bold = name != "Normal"
        fonts = style.element.get_or_add_rPr().rFonts
        fonts.set(qn("w:eastAsia"), "微软雅黑")
    document.sections[0].left_margin = Inches(1.05)
    document.sections[0].right_margin = Inches(1.05)


def _box(document: WordDocument, text: str) -> None:
    if not text:
        return
    table = document.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    props = cell._tc.get_or_add_tcPr()
    shade = OxmlElement("w:shd")
    shade.set(qn("w:fill"), "F5F6F8")
    props.append(shade)
    borders = OxmlElement("w:tcBorders")
    for side in ("top", "left", "bottom", "right"):
        border = OxmlElement(f"w:{side}")
        border.set(qn("w:val"), "single")
        border.set(qn("w:sz"), "4")
        border.set(qn("w:color"), "D9DEE3")
        borders.append(border)
    props.append(borders)
    xml_text = "".join(
        char if char in "\t\n\r" or ord(char) >= 32 else f"\\x{ord(char):02x}"
        for char in text
    )
    run = cell.paragraphs[0].add_run(xml_text)
    run.font.name = "Consolas"
    run.font.size = Pt(9.5)


def _picture(document: WordDocument, root: Path, relative: str | None, label: str) -> None:
    if relative:
        path = contained_path(root, relative)
        if path.is_file():
            with Image.open(path, formats=["PNG"]) as image:
                width, height = image.size
                image.verify()
            width_inches = min(6.2, 7.2 * width / height)
            document.add_picture(str(path), width=Inches(width_inches))
            return
    run = document.add_paragraph().add_run(f"【此处插入截图：{label}】")
    run.bold = True
    run.font.color.rgb = RGBColor.from_string("AD2639")


def build_docx(
    meta: Meta,
    audit: Audit,
    verify: Verify | None,
    evidence_root: Path,
    out: Path,
    *,
    repo_root: Path | None = None,
    deploy_log: DeployLog | None = None,
) -> Path:
    document = Document()
    _style(document)
    document.add_heading(audit.title_hint, level=0)
    document.add_heading("项目简介", level=1)
    document.add_paragraph(meta.description or f"{meta.vendor} · {meta.product}")
    manifest = verify.evidence_manifest if verify else None
    _picture(document, evidence_root, manifest.app_home if manifest else None, "项目首页")
    document.add_paragraph(f"官网地址：{meta.homepage or '未提供'}")
    document.add_paragraph(f"项目地址：{meta.repo_url}")
    document.add_paragraph(f"Star 数：{meta.stars if meta.stars is not None else '未提供'}")
    deployment = deploy_log.deploy_mode if deploy_log else "、".join(meta.deploy_modes)
    document.add_paragraph(f"部署方式：{deployment or '未提供'}")
    document.add_heading("漏洞描述", level=1)
    document.add_paragraph(audit.technical_summary)
    document.add_paragraph(f"受影响版本：{audit.affected_versions}")
    document.add_paragraph(f"漏洞等级：{audit.severity}")
    document.add_paragraph(f"漏洞危害：{audit.impact_summary}")
    if audit.default_deploy_affected is not None:
        document.add_paragraph(f"默认部署受影响：{'是' if audit.default_deploy_affected else '否'}")
    for condition in audit.preconditions:
        document.add_paragraph(condition, style="List Bullet")

    document.add_heading("代码审计", level=1)
    code_shots = {s.step: s.path for s in manifest.code_shots} if manifest else {}
    for item in sorted(audit.code_evidence, key=lambda shot: shot.step):
        location = f"{item.file}:{item.start_line}–{item.end_line}"
        document.add_heading(f"{item.step}. {location}", level=2)
        document.add_paragraph(item.analysis)
        if repo_root is not None:
            source = contained_path(repo_root, item.file)
            if source.is_file():
                _, lines = code_excerpt(source, item.start_line, item.end_line)
                _box(document, "\n".join(lines))
        _picture(document, evidence_root, code_shots.get(item.step), location)

    document.add_heading("漏洞验证", level=1)
    document.add_paragraph(VERDICT_LABELS[verify.verdict] if verify else "源码审查")
    if verify:
        if verify.realistic_assessment.realistic_notes:
            document.add_paragraph(verify.realistic_assessment.realistic_notes)
        verify_shots = {shot.step_no: shot.path for shot in manifest.verify_shots}
        for step in sorted(verify.steps, key=lambda step: step.step_no):
            document.add_heading(f"{step.step_no}. {step.title}", level=2)
            if step.expected:
                document.add_paragraph(f"预期：{step.expected}")
            if step.observed:
                document.add_paragraph(f"结果：{step.observed}")
            if isinstance(step, HttpStep):
                _box(document, f"{step.raw_request}\n\n{step.raw_response}")
            if isinstance(step, TermStep):
                footer = f"\n退出码：{step.exit_code}" if step.exit_code is not None else ""
                _box(document, strip_terminal_formatting(f"{step.command}\n{step.stdout}{footer}"))
            _picture(document, evidence_root, step.screenshot or verify_shots.get(step.step_no),
                     step.title)
        for placeholder in manifest.manual_placeholders_needed:
            _picture(document, evidence_root, None, placeholder)
        if verify.cleanup_summary:
            document.add_paragraph(f"环境清理：{verify.cleanup_summary}")

    document.add_heading("修复建议", level=1)
    for label, items in (("临时缓解", audit.remediation.temporary),
                         ("正式修复", audit.remediation.permanent)):
        if items:
            document.add_heading(label, level=2)
        for item in items:
            document.add_paragraph(item, style="List Bullet")
    buffer = BytesIO()
    document.save(buffer)
    atomic_write(out, buffer.getvalue())
    return out
