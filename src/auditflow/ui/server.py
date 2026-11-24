import json
import mimetypes
import os
import shutil
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import yaml

from auditflow.adapters.registry import AdapterRegistry
from auditflow.backends import get_backend
from auditflow.core.config import Env, Pipeline, load_env, load_pipeline
from auditflow.core.paths import artifact_id, atomic_write, contained_path
from auditflow.core.schemas import (
    Audit,
    AuditDisposition,
    CnvdForm,
    DeployLog,
    Meta,
    Surface,
    Verify,
    read_contract,
)
from auditflow.core.skill_registry import SkillRegistry
from auditflow.core.state import Tracker
from auditflow.dispatcher.engine import Dispatcher
from auditflow.reporting.cnvd_form import make_form
from auditflow.scout.dedup import save_new_projects
from auditflow.scout.platforms import metadata_from_url, search_projects
from auditflow.sync import sync_pull


class UIContext:
    def __init__(
        self,
        *,
        pipeline_path: Path,
        env_path: Path,
        workspaces: Path,
        skills_dir: Path,
    ) -> None:
        self.pipeline_path = pipeline_path
        self.env_path = env_path
        self.workspaces = workspaces.resolve()
        self.skills_dir = skills_dir.resolve()

    def load_pipeline_cfg(self) -> tuple[Path, Pipeline]:
        path = self.pipeline_path
        if not path.is_file():
            fallback = path.with_name("pipeline.example.yaml")
            if fallback.is_file():
                path = fallback
        return path, load_pipeline(path)

    def load_env_cfg(self) -> tuple[Path | None, Env]:
        if self.env_path.is_file():
            return self.env_path, load_env(self.env_path)
        fallback = self.env_path.with_name("env.example.yaml")
        if fallback.is_file():
            return fallback, load_env(fallback)
        return None, Env()

    def tracker(self) -> Tracker:
        _, env = self.load_env_cfg()
        return Tracker(env.paths.tracker_db_path)

    def dispatcher(self) -> Dispatcher:
        _, pipeline = self.load_pipeline_cfg()
        _, env = self.load_env_cfg()
        return Dispatcher(
            pipeline,
            env,
            Tracker(env.paths.tracker_db_path),
            SkillRegistry(self.skills_dir),
            self.workspaces,
        )

    def overview_payload(self) -> dict[str, Any]:
        _, pipeline = self.load_pipeline_cfg()
        _, env = self.load_env_cfg()
        tracker = Tracker(env.paths.tracker_db_path)
        skills = SkillRegistry(self.skills_dir)

        targets: list[dict[str, Any]] = []
        counts = {
            "targets": 0,
            "gate1_pending": 0,
            "candidates": 0,
            "gate2_pending": 0,
            "needs_human_env": 0,
            "verified": 0,
            "reported": 0,
        }

        with tracker.connect() as db:
            target_rows = db.execute(
                "SELECT target_id, status FROM targets ORDER BY rowid DESC"
            ).fetchall()
            cand_rows = db.execute(
                "SELECT target_id, candidate_id, status FROM candidates ORDER BY rowid ASC"
            ).fetchall()
            report_rows = db.execute(
                "SELECT target_id, candidate_id, path FROM reports"
            ).fetchall()

        reports_map = {(t, c): p for t, c, p in report_rows}
        cands_by_target: dict[str, list[tuple[str, str]]] = {}
        for tid, cid, cstatus in cand_rows:
            cands_by_target.setdefault(tid, []).append((cid, cstatus))

        for tid, tstatus in target_rows:
            counts["targets"] += 1
            if tstatus == "GATE1_PENDING":
                counts["gate1_pending"] += 1
            troot = self.workspaces / tid
            meta_dict: dict[str, Any] = {}
            meta_file = troot / "meta.json"
            if meta_file.is_file():
                try:
                    meta_dict = read_contract(meta_file, Meta).model_dump(mode="json")
                except Exception:
                    meta_dict = {}

            disp_map: dict[str, dict[str, Any]] = {}
            disp_file = troot / "audit-disposition.json"
            if disp_file.is_file():
                try:
                    disp = read_contract(disp_file, AuditDisposition)
                    disp_map = {c.candidate_id: c.model_dump(mode="json") for c in disp.candidates}
                except Exception:
                    disp_map = {}

            candidates_out = []
            for cid, cstatus in cands_by_target.get(tid, []):
                counts["candidates"] += 1
                if cstatus == "GATE2_PENDING":
                    counts["gate2_pending"] += 1
                elif cstatus == "NEEDS_HUMAN_ENV":
                    counts["needs_human_env"] += 1
                elif cstatus in {"VERIFIED", "EVIDENCE_READY"}:
                    counts["verified"] += 1
                elif cstatus in {"REPORTED", "SUBMITTED"}:
                    counts["reported"] += 1

                croot = troot / "candidates" / cid
                cinfo = disp_map.get(cid, {})
                audit_summary: dict[str, Any] = {}
                if (croot / "audit.json").is_file():
                    try:
                        audit_summary = read_contract(croot / "audit.json", Audit).model_dump(
                            mode="json"
                        )
                    except Exception:
                        pass
                candidates_out.append(
                    {
                        "candidate_id": cid,
                        "status": cstatus,
                        "title": audit_summary.get("title_hint")
                        or cinfo.get("title_hint")
                        or cid,
                        "cwe": cinfo.get("cwe")
                        or (audit_summary.get("cwe", [None])[0] if audit_summary else None),
                        "severity": audit_summary.get("severity")
                        or cinfo.get("severity_estimate")
                        or "",
                        "confidence": cinfo.get("confidence") or "",
                        "triage_recommendation": cinfo.get("triage_recommendation") or "",
                        "triage_reason": cinfo.get("triage_reason") or "",
                        "report_path": reports_map.get((tid, cid)),
                        "has_verify": (croot / "verify.json").is_file(),
                        "has_deploy_log": (croot / "deploy-log.json").is_file(),
                    }
                )

            targets.append(
                {
                    "target_id": tid,
                    "status": tstatus,
                    "has_repo": (troot / "repo").is_dir(),
                    "has_surface": (troot / "surface.json").is_file(),
                    "meta": meta_dict,
                    "candidates": candidates_out,
                }
            )

        return {
            "counts": counts,
            "targets": targets,
            "available_skills": skills.list(),
            "available_adapters": sorted(
                set(AdapterRegistry(pipeline.adapters | pipeline.custom_adapters).factories)
                | set(pipeline.adapters)
                | set(pipeline.custom_adapters)
            ),
            "available_backends": ["local", "ssh-ubuntu", "wsl2"],
            "pipeline_name": pipeline.pipeline_name,
        }

    def doctor_payload(self) -> dict[str, Any]:
        _, config = self.load_pipeline_cfg()
        _, settings = self.load_env_cfg()
        registry = AdapterRegistry(config.adapters | config.custom_adapters)
        rows = []
        adapters = {stage.adapter for stage in config.stages.values() if stage.adapter}
        backends = {stage.backend for stage in config.stages.values()}
        for name in sorted(adapters):
            ok, detail = registry.get(name).check_health()
            rows.append({"kind": "adapter", "name": name, "ok": ok, "detail": detail})
        for name in sorted(backends):
            try:
                ok, detail = get_backend(name, settings.backends).check_health()
            except ValueError as exc:
                ok, detail = False, str(exc)
            rows.append({"kind": "backend", "name": name, "ok": ok, "detail": detail})
        return {"checks": rows}

    def discover_agents_payload(self) -> dict[str, Any]:
        """Auto-detect locally installed coding/audit agents and API credentials on this machine."""
        _, config = self.load_pipeline_cfg()
        configured = config.adapters | config.custom_adapters
        used_in_stages = {s.adapter for s in config.stages.values() if s.adapter}

        known_specs = [
            {
                "name": "codex",
                "label": "OpenAI Codex CLI",
                "kind": "cli",
                "binaries": ["codex"],
                "default_config": {"binary": "codex", "extra_args": ["exec", "--full-auto"]},
                "description": "工程执行与容器隔离验证强项",
            },
            {
                "name": "claude-code",
                "label": "Claude Code CLI",
                "kind": "cli",
                "binaries": ["claude"],
                "default_config": {"binary": "claude", "extra_args": ["-p", "--output-format", "json"]},
                "description": "长上下文代码审计与中文报告写作强项",
            },
            {
                "name": "dsh",
                "label": "DeepSeek Harness (dsh)",
                "kind": "cli",
                "binaries": ["dsh"],
                "default_config": {"binary": "dsh", "extra_args": ["--non-interactive"]},
                "description": "模型无关 Agent Runtime，适合批量高性价比深审",
            },
            {
                "name": "antigravity-cli",
                "label": "Antigravity CLI (agy)",
                "kind": "custom-cli",
                "binaries": ["agy", "antigravity"],
                "default_config": {
                    "type": "custom-cli",
                    "command_template": "agy --skill {skill_path} --workspace {workspace_dir} --out {output_file}",
                },
                "description": "本机 Antigravity CLI 适配器（可自定义命令模板）",
            },
            {
                "name": "openai-api",
                "label": "OpenAI 兼容 API（DeepSeek / Qwen / OpenAI）",
                "kind": "api",
                "env_keys": ["AUDITFLOW_OPENAI_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"],
                "default_config": {
                    "base_url_env": "AUDITFLOW_OPENAI_BASE_URL",
                    "api_key_env": "AUDITFLOW_OPENAI_API_KEY",
                    "model": "deepseek-chat",
                },
                "description": "直连便宜 API 批量初筛与字段提取",
            },
            {
                "name": "native-subagent",
                "label": "宿主原生 Subagent（Antigravity / 当前对话）",
                "kind": "host",
                "default_config": {},
                "description": "由当前主 Agent 直接接管执行或交接",
            },
        ]

        discovered: list[dict[str, Any]] = []
        seen: set[str] = set()
        for spec in known_specs:
            name = spec["name"]
            seen.add(name)
            detected = False
            detected_detail = ""
            cfg = dict(configured.get(name, spec["default_config"]))
            if spec["kind"] in {"cli", "custom-cli"}:
                custom_bin = cfg.get("binary")
                candidates = ([custom_bin] if custom_bin else []) + list(spec.get("binaries", []))
                for candidate_bin in candidates:
                    found = shutil.which(candidate_bin)
                    if found:
                        detected = True
                        detected_detail = found
                        break
                if not detected:
                    detected_detail = f"本机 PATH 未找到 {'/'.join(candidates)}（如装在远端 Ubuntu 仍可启用）"
            elif spec["kind"] == "api":
                configured_key = cfg.get("api_key_env", "AUDITFLOW_OPENAI_API_KEY")
                keys_to_check = [configured_key, *spec.get("env_keys", [])]
                found_key = next((k for k in keys_to_check if os.environ.get(k)), None)
                if found_key:
                    detected = True
                    detected_detail = f"已检测到环境变量 {found_key}"
                    cfg["api_key_env"] = found_key
                else:
                    detected_detail = f"未检测到 {configured_key} 环境变量"
            else:
                detected = True
                detected_detail = "始终可用"

            discovered.append(
                {
                    "name": name,
                    "label": spec["label"],
                    "kind": spec["kind"],
                    "detected": detected,
                    "detail": detected_detail,
                    "enabled": name in configured or name in used_in_stages or name == "native-subagent",
                    "config": cfg,
                    "description": spec["description"],
                }
            )

        # Include any additional custom adapters already defined in pipeline.yaml
        for name, cfg in configured.items():
            if name in seen:
                continue
            cmd = str(cfg.get("command_template") or cfg.get("binary") or "")
            first_bin = cmd.split()[0] if cmd.strip() else ""
            found = shutil.which(first_bin) if first_bin else None
            discovered.append(
                {
                    "name": name,
                    "label": f"自定义 Agent ({name})",
                    "kind": cfg.get("type", "custom-cli"),
                    "detected": bool(found),
                    "detail": found or f"自定义配置：{cmd or 'handoff'}",
                    "enabled": True,
                    "config": cfg,
                    "description": "用户在 pipeline.yaml 中注册的自定义 Agent",
                }
            )

        skills_registry = SkillRegistry(self.skills_dir)
        skills_by_stage: dict[str, list[dict[str, str]]] = {}
        for sname in skills_registry.list():
            m = skills_registry.get(sname)
            skills_by_stage.setdefault(m.stage, []).append(
                {"name": m.name, "description": m.description}
            )

        return {
            "agents": discovered,
            "skills_by_stage": skills_by_stage,
            "stages": {k: v.model_dump(mode="json") for k, v in config.stages.items()},
            "gates": config.gates.model_dump(mode="json"),
            "backends": ["local", "ssh-ubuntu", "wsl2"],
            "pipeline_name": config.pipeline_name,
        }

    def apply_visual_pipeline(self, body: dict[str, Any]) -> dict[str, Any]:
        _, existing = self.load_pipeline_cfg()
        data = existing.model_dump(mode="json")
        if "gates" in body and isinstance(body["gates"], dict):
            data["gates"] = body["gates"]
        if "adapters" in body and isinstance(body["adapters"], dict):
            data["adapters"] = body["adapters"]
        if "custom_adapters" in body and isinstance(body["custom_adapters"], dict):
            data["custom_adapters"] = body["custom_adapters"]
        if "stages" in body and isinstance(body["stages"], dict):
            cleaned_stages: dict[str, dict[str, Any]] = {}
            for stage_name, stage_cfg in body["stages"].items():
                entry = {k: v for k, v in stage_cfg.items() if v is not None and v != [] and v != ""}
                if stage_name == "evidence":
                    entry.pop("skill", None)
                    entry.pop("skills", None)
                    entry.pop("adapter", None)
                    entry.setdefault("renderers", ["code", "web", "http", "term"])
                else:
                    entry.pop("renderers", None)
                    if entry.get("skills"):
                        entry.pop("skill", None)
                    elif entry.get("skill"):
                        entry.pop("skills", None)
                cleaned_stages[stage_name] = entry
            data["stages"] = cleaned_stages

        validated = Pipeline.model_validate(data)
        dumped = yaml.safe_dump(
            validated.model_dump(mode="json", exclude_defaults=False, exclude_none=True),
            allow_unicode=True,
            sort_keys=False,
        )
        atomic_write(self.pipeline_path, dumped.encode("utf-8"))
        return {"ok": True, "pipeline_path": str(self.pipeline_path), "pipeline_yaml": dumped}

    def candidate_detail(self, target: str, candidate: str) -> dict[str, Any]:
        target, candidate = artifact_id(target), artifact_id(candidate)
        troot = contained_path(self.workspaces, target)
        croot = contained_path(troot, f"candidates/{candidate}")
        meta = read_contract(troot / "meta.json", Meta) if (troot / "meta.json").is_file() else None
        surface = (
            read_contract(troot / "surface.json", Surface)
            if (troot / "surface.json").is_file()
            else None
        )
        audit = (
            read_contract(croot / "audit.json", Audit) if (croot / "audit.json").is_file() else None
        )
        deploy = (
            read_contract(croot / "deploy-log.json", DeployLog)
            if (croot / "deploy-log.json").is_file()
            else None
        )
        verify = (
            read_contract(croot / "verify.json", Verify)
            if (croot / "verify.json").is_file()
            else None
        )
        cnvd_form = None
        if (croot / "cnvd-form.json").is_file():
            cnvd_form = read_contract(croot / "cnvd-form.json", CnvdForm)
        elif meta is not None and audit is not None:
            cnvd_form = make_form(meta, audit, verify, f"{target}__{candidate}.docx")

        evidence_dir = croot / "evidence"
        images: list[dict[str, str]] = []
        if evidence_dir.is_dir():
            for png in sorted(evidence_dir.glob("*.png")):
                images.append(
                    {
                        "name": png.name,
                        "url": f"/api/evidence/{target}/{candidate}/{png.name}",
                    }
                )

        tracker = self.tracker()
        status = None
        try:
            status = tracker.candidate_status(target, candidate)
        except ValueError:
            pass
        report_path = None
        with tracker.connect() as db:
            row = db.execute(
                "SELECT path FROM reports WHERE target_id = ? AND candidate_id = ?",
                (target, candidate),
            ).fetchone()
            if row:
                report_path = row[0]

        return {
            "target_id": target,
            "candidate_id": candidate,
            "status": status,
            "meta": meta.model_dump(mode="json") if meta else None,
            "surface": surface.model_dump(mode="json") if surface else None,
            "audit": audit.model_dump(mode="json") if audit else None,
            "deploy_log": deploy.model_dump(mode="json") if deploy else None,
            "verify": verify.model_dump(mode="json") if verify else None,
            "cnvd_form": cnvd_form.model_dump(mode="json") if cnvd_form else None,
            "evidence_images": images,
            "report_path": report_path,
            "has_docx": bool(report_path and Path(report_path).is_file()),
        }


def _index_html() -> bytes:
    return files("auditflow.ui").joinpath("static/index.html").read_bytes()


def create_server(
    host: str,
    port: int,
    ctx: UIContext,
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send(self, code: int, body: bytes, content_type: str, extra_headers: dict[str, str] | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if extra_headers:
                for k, v in extra_headers.items():
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, code: int, data: Any) -> None:
            self._send(
                code,
                (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            parsed = json.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("JSON body must be an object")
            return parsed

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            path = parsed.path
            try:
                if path in {"/", "/index.html"}:
                    self._send(HTTPStatus.OK, _index_html(), "text/html; charset=utf-8")
                    return
                if path == "/api/overview":
                    self._send_json(HTTPStatus.OK, ctx.overview_payload())
                    return
                if path == "/api/doctor":
                    self._send_json(HTTPStatus.OK, ctx.doctor_payload())
                    return
                if path == "/api/discover-agents":
                    self._send_json(HTTPStatus.OK, ctx.discover_agents_payload())
                    return
                if path == "/api/config":
                    p_path, pipeline = ctx.load_pipeline_cfg()
                    e_path, env = ctx.load_env_cfg()
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            "pipeline_path": str(p_path),
                            "env_path": str(e_path) if e_path else str(ctx.env_path),
                            "pipeline": pipeline.model_dump(mode="json"),
                            "env": env.model_dump(mode="json", by_alias=True),
                            "pipeline_yaml": p_path.read_text(encoding="utf-8") if p_path.is_file() else "",
                            "env_yaml": e_path.read_text(encoding="utf-8") if (e_path and e_path.is_file()) else "",
                        },
                    )
                    return
                if path.startswith("/api/candidate/"):
                    parts = [unquote(p) for p in path.removeprefix("/api/candidate/").split("/") if p]
                    if len(parts) != 2:
                        self._send_json(HTTPStatus.BAD_REQUEST, {"error": "expected /api/candidate/<target>/<candidate>"})
                        return
                    self._send_json(HTTPStatus.OK, ctx.candidate_detail(parts[0], parts[1]))
                    return
                if path.startswith("/api/evidence/"):
                    parts = [unquote(p) for p in path.removeprefix("/api/evidence/").split("/") if p]
                    if len(parts) != 3:
                        self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid evidence path"})
                        return
                    target, candidate, filename = artifact_id(parts[0]), artifact_id(parts[1]), parts[2]
                    png = contained_path(ctx.workspaces, f"{target}/candidates/{candidate}/evidence/{filename}")
                    if not png.is_file() or png.suffix.lower() != ".png":
                        self._send_json(HTTPStatus.NOT_FOUND, {"error": "evidence image not found"})
                        return
                    self._send(HTTPStatus.OK, png.read_bytes(), "image/png")
                    return
                if path.startswith("/api/download-docx/"):
                    parts = [unquote(p) for p in path.removeprefix("/api/download-docx/").split("/") if p]
                    if len(parts) != 2:
                        self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid download path"})
                        return
                    detail = ctx.candidate_detail(parts[0], parts[1])
                    report_path = detail.get("report_path")
                    if not report_path or not Path(report_path).is_file():
                        self._send_json(HTTPStatus.NOT_FOUND, {"error": "docx report not generated yet"})
                        return
                    file_path = Path(report_path)
                    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
                    self._send(
                        HTTPStatus.OK,
                        file_path.read_bytes(),
                        mime,
                        {"Content-Disposition": f'attachment; filename="{file_path.name}"'},
                    )
                    return
                qs = parse_qs(parsed.query)
                self._send_json(HTTPStatus.NOT_FOUND, {"error": f"unknown endpoint: {path}", "query": qs})
            except Exception as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            try:
                body = self._read_json()
                if path == "/api/scout":
                    _, settings = ctx.load_env_cfg()
                    tracker = Tracker(settings.paths.tracker_db_path)
                    urls_text = str(body.get("urls", "")).strip()
                    if urls_text:
                        projects = []
                        for line in urls_text.splitlines():
                            line = line.strip()
                            if line:
                                projects.append(metadata_from_url(line))
                    else:
                        platform = str(body.get("platform", "github")).strip()
                        query = str(body.get("query", "")).strip()
                        limit = int(body.get("limit", 10))
                        projects = search_projects(platform, query, settings.platforms, limit=limit)
                    accepted = save_new_projects(projects, tracker, ctx.workspaces)
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "added": len(accepted),
                            "targets": [item.model_dump(mode="json") for item in accepted],
                        },
                    )
                    return

                if path == "/api/decide":
                    target = str(body["target"])
                    actor = str(body.get("actor", "reviewer")).strip() or "reviewer"
                    approve = bool(body.get("approve", True))
                    candidate = body.get("candidate")
                    auto_clone = bool(body.get("auto_clone", False))
                    dispatcher = ctx.dispatcher()
                    if candidate:
                        dispatcher.approve_candidate(target, str(candidate), approve=approve, actor=actor)
                    else:
                        dispatcher.approve_project(target, approve=approve, actor=actor, auto_clone=auto_clone)
                    self._send_json(HTTPStatus.OK, {"ok": True})
                    return

                if path == "/api/clone":
                    target = str(body["target"])
                    backend = body.get("backend")
                    repo = ctx.dispatcher().clone_target(target, backend_name=backend)
                    self._send_json(HTTPStatus.OK, {"ok": True, "repo_path": str(repo)})
                    return

                if path == "/api/resume-env":
                    target = str(body["target"])
                    candidate = str(body["candidate"])
                    actor = str(body.get("actor", "reviewer")).strip() or "reviewer"
                    ctx.dispatcher().resume_environment(target, candidate, actor=actor)
                    self._send_json(HTTPStatus.OK, {"ok": True})
                    return

                if path == "/api/stage":
                    stage = str(body["stage"])
                    target = str(body["target"])
                    candidate = body.get("candidate")
                    dispatcher = ctx.dispatcher()
                    accepted = dispatcher.run_stage(stage, target, str(candidate) if candidate else None)
                    self._send_json(HTTPStatus.OK, {"ok": True, "accepted": accepted})
                    return

                if path == "/api/sync-pull":
                    target = str(body["target"])
                    candidate = str(body["candidate"])
                    backend_name = str(body.get("backend", "ssh-ubuntu"))
                    replace = bool(body.get("replace", False))
                    _, settings = ctx.load_env_cfg()
                    paths = sync_pull(
                        get_backend(backend_name, settings.backends),
                        ctx.workspaces,
                        target,
                        candidate,
                        replace=replace,
                        settings=settings.docker_verify,
                        tracker=Tracker(settings.paths.tracker_db_path),
                    )
                    self._send_json(HTTPStatus.OK, {"ok": True, "files": [str(p) for p in paths]})
                    return

                if path == "/api/report":
                    target = str(body["target"])
                    candidate = str(body["candidate"])
                    _, settings = ctx.load_env_cfg()
                    out_dir = Path(str(body.get("out") or settings.paths.windows_report_output_dir))
                    paths = ctx.dispatcher().report(target, candidate, out_dir)
                    self._send_json(HTTPStatus.OK, {"ok": True, "files": [str(p) for p in paths]})
                    return

                if path == "/api/config/apply-visual":
                    self._send_json(HTTPStatus.OK, ctx.apply_visual_pipeline(body))
                    return

                if path == "/api/config/save":
                    if "pipeline_yaml" in body:
                        raw_yaml = str(body["pipeline_yaml"])
                        parsed_pipeline = yaml.safe_load(raw_yaml)
                        Pipeline.model_validate(parsed_pipeline)
                        atomic_write(ctx.pipeline_path, raw_yaml.encode("utf-8"))
                    if "env_yaml" in body:
                        raw_env = str(body["env_yaml"])
                        parsed_env = yaml.safe_load(raw_env)
                        Env.model_validate(parsed_env)
                        atomic_write(ctx.env_path, raw_env.encode("utf-8"))
                    self._send_json(HTTPStatus.OK, {"ok": True})
                    return

                self._send_json(HTTPStatus.NOT_FOUND, {"error": f"unknown endpoint: {path}"})
            except Exception as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    return ThreadingHTTPServer((host, port), Handler)


def run_ui(
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    pipeline_path: Path = Path("config/pipeline.yaml"),
    env_path: Path = Path("config/env.yaml"),
    workspaces: Path = Path("workspaces"),
    skills_dir: Path = Path("skills"),
    open_browser: bool = True,
) -> None:
    ctx = UIContext(
        pipeline_path=pipeline_path,
        env_path=env_path,
        workspaces=workspaces,
        skills_dir=skills_dir,
    )
    server = create_server(host, port, ctx)
    url = f"http://{host}:{port}"
    print(f"AuditFlow Web UI listening at {url} (Press Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
