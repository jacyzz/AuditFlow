from pathlib import Path

from auditflow.core.config import DockerSettings
from auditflow.core.paths import artifact_id, contained_path
from auditflow.core.schemas import (
    Audit,
    CnvdForm,
    DeployLog,
    HttpStep,
    Meta,
    TermStep,
    Verify,
    WebStep,
    read_contract,
)
from auditflow.evidence.code_shot import render_code_shot
from auditflow.evidence.common import BrowserUnavailable
from auditflow.evidence.http_shot import render_http_shot
from auditflow.evidence.term_shot import render_term_shot
from auditflow.evidence.web_shot import capture_web_shot
from auditflow.reporting.cnvd_form import export_form, make_form
from auditflow.reporting.docx_builder import build_docx
from auditflow.reporting.excel_sync import append_report


def load_report_inputs(
    workspace: Path, candidate: str | None,
) -> tuple[Meta, Audit, Verify | None, DeployLog | None, Path]:
    candidate_root = (
        contained_path(workspace, f"candidates/{artifact_id(candidate)}") if candidate else workspace
    )
    meta = read_contract(contained_path(workspace, "meta.json"), Meta)
    audit = read_contract(contained_path(candidate_root, "audit.json"), Audit)
    verify_path = contained_path(candidate_root, "verify.json")
    verify = read_contract(verify_path, Verify) if verify_path.is_file() else None
    deploy_path = contained_path(candidate_root, "deploy-log.json")
    deploy = read_contract(deploy_path, DeployLog) if deploy_path.is_file() else None
    if audit.target_id != meta.target_id or candidate and audit.candidate_id != candidate:
        raise ValueError("report artifact identifiers do not match")
    if any(item is not None and item.candidate_id != audit.candidate_id for item in (verify, deploy)):
        raise ValueError("report artifact candidate identifiers do not match")
    if verify:
        code_steps = {item.step for item in audit.code_evidence}
        if any(item.step not in code_steps for item in verify.evidence_manifest.code_shots):
            raise ValueError("evidence references an unknown source excerpt")
    return meta, audit, verify, deploy, candidate_root


def render_saved_evidence(
    audit: Audit,
    verify: Verify,
    repo: Path,
    root: Path,
    *,
    fallback: bool = True,
    renderers: tuple[str, ...] = ("code", "http", "term"),
    docker_settings: DockerSettings | None = None,
) -> None:
    manifest = verify.evidence_manifest
    code_paths = {item.step: item.path for item in manifest.code_shots}
    for item in audit.code_evidence if "code" in renderers else ():
        path = code_paths.get(item.step)
        if not path:
            continue
        out = contained_path(root, path)
        source = contained_path(repo, item.file)
        if not out.exists() and source.is_file():
            render_code_shot(
                source,
                item.start_line,
                item.end_line,
                out,
                highlight=item.highlight_lines,
                label=f"{item.file}:{item.start_line}–{item.end_line}",
                allow_fallback=fallback,
            )
    shot_paths = {item.step_no: item.path for item in manifest.verify_shots}
    for step in verify.steps:
        path = step.screenshot or shot_paths.get(step.step_no)
        if not path:
            continue
        out = contained_path(root, path)
        if out.exists():
            continue
        if isinstance(step, HttpStep) and "http" in renderers:
            render_http_shot(
                step.raw_request,
                step.raw_response,
                out,
                title=step.title,
                highlight=step.highlight_response_patterns,
                allow_fallback=fallback,
            )
        if isinstance(step, TermStep) and "term" in renderers:
            render_term_shot(
                step.command,
                step.stdout,
                out,
                title=step.title,
                highlight=step.highlight_patterns,
                exit_code=step.exit_code,
                allow_fallback=fallback,
            )
        if isinstance(step, WebStep) and "web" in renderers and docker_settings is not None:
            try:
                capture_web_shot(
                    str(step.url),
                    out,
                    show_address_bar=True,
                    docker_settings=docker_settings,
                )
            except (BrowserUnavailable, OSError):
                if not fallback:
                    raise


def generate_report(
    workspace: Path, out: Path, *, candidate: str | None = None, excel: Path | None = None,
) -> tuple[Path, Path, Path]:
    meta, audit, verify, deploy, candidate_root = load_report_inputs(workspace, candidate)
    repo = contained_path(workspace, "repo")
    if verify:
        render_saved_evidence(audit, verify, repo, candidate_root)
    stem = out / f"{meta.target_id}__{audit.candidate_id}"
    docx = stem.parent / f"{stem.name}.docx"
    form = make_form(meta, audit, verify, docx.name)
    reviewed_path = contained_path(candidate_root, "cnvd-form.json")
    if candidate is not None and reviewed_path.is_file():
        reviewed = read_contract(reviewed_path, CnvdForm)
        for field in ("vendor", "product", "affected_versions", "repo_url", "cwe", "severity"):
            if getattr(form, field) != getattr(reviewed, field):
                raise ValueError(f"reviewed form disagrees with source artifacts: {field}")
        form = reviewed.model_copy(update={"attachment_docx": docx.name})
    build_docx(meta, audit, verify, candidate_root, docx, repo_root=repo, deploy_log=deploy)
    markdown, json_file = export_form(form, stem)
    if excel is not None:
        append_report(excel, form)
    return docx, markdown, json_file
