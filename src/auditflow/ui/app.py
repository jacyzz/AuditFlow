import json
import webbrowser
from importlib.resources import files
from pathlib import Path
from typing import Any

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from auditflow.backends import get_backend
from auditflow.coordinator.agent import CoordinatorEngine
from auditflow.coordinator.sessions import ChatStore
from auditflow.core.agent_profiles import (
    PROVIDER_PRESETS,
    ApiProvider,
    discover_agent_profiles,
    load_profile_overrides,
    load_providers,
    recommend_stage_assignments,
    save_profile_overrides,
    save_providers,
    test_provider_connection,
)
from auditflow.core.config import Env, Pipeline
from auditflow.core.paths import artifact_id, atomic_write, contained_path
from auditflow.core.skill_manager import SkillManager
from auditflow.core.state import Tracker
from auditflow.scout.dedup import save_new_projects
from auditflow.scout.platforms import metadata_from_url, search_projects
from auditflow.sync import sync_pull
from auditflow.ui.server import UIContext


def _mask_provider(p: ApiProvider) -> dict[str, Any]:
    d = p.model_dump(mode="json")
    raw = d.get("api_key_inline")
    if raw:
        d["api_key_inline"] = (raw[:4] + "****" + raw[-3:]) if len(raw) > 8 else "****"
        d["has_inline_key"] = True
    else:
        d["has_inline_key"] = False
    return d


def create_app(ctx: UIContext) -> FastAPI:
    app = FastAPI(title="AuditFlow Studio API", version="2.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    config_dir = ctx.pipeline_path.parent
    providers_path = config_dir / "providers.yaml"
    overrides_path = config_dir / "agent_profiles.yaml"

    def _skill_manager() -> SkillManager:
        return SkillManager(ctx.skills_dir)

    def _chat_store() -> ChatStore:
        _, env = ctx.load_env_cfg()
        return ChatStore(env.paths.local_cache_dir / "chat_sessions.sqlite")

    def _coordinator() -> CoordinatorEngine:
        _, pipeline = ctx.load_pipeline_cfg()
        _, env = ctx.load_env_cfg()
        return CoordinatorEngine(
            pipeline=pipeline,
            env=env,
            workspaces=ctx.workspaces,
            skills_dir=ctx.skills_dir,
            providers_path=providers_path,
            overrides_path=overrides_path,
            chat_store=_chat_store(),
            dispatcher=ctx.dispatcher(),
        )

    def _err(exc: Exception, status: int = 400) -> HTTPException:
        return HTTPException(status_code=status, detail=str(exc))

    # ── Overview & Doctor ───────────────────────────────────────────
    @app.get("/api/overview")
    def api_overview() -> dict[str, Any]:
        try:
            payload = ctx.overview_payload()
            _, pipeline = ctx.load_pipeline_cfg()
            profiles = discover_agent_profiles(
                pipeline, overrides_path=overrides_path, providers_path=providers_path
            )
            payload["agent_profiles"] = [p.model_dump(mode="json") for p in profiles]
            payload["skills"] = [s.model_dump(mode="json") for s in _skill_manager().list_skills()]
            return payload
        except Exception as exc:
            raise _err(exc) from exc

    @app.get("/api/doctor")
    def api_doctor() -> dict[str, Any]:
        try:
            return ctx.doctor_payload()
        except Exception as exc:
            raise _err(exc) from exc

    # ── Coordinator Chat & SSE ──────────────────────────────────────
    @app.get("/api/chat/sessions")
    def api_chat_sessions() -> dict[str, Any]:
        store = _chat_store()
        sessions = store.list_sessions()
        if not sessions:
            sessions = [store.create_session("默认审计工作台")]
        return {"sessions": sessions}

    @app.post("/api/chat/sessions")
    def api_chat_create(body: dict[str, Any]) -> dict[str, Any]:
        title = str(body.get("title") or "新审计会话").strip()
        target_id = body.get("target_id")
        return {"session": _chat_store().create_session(title, target_id)}

    @app.delete("/api/chat/sessions/{session_id}")
    def api_chat_delete(session_id: str) -> dict[str, Any]:
        _chat_store().delete_session(session_id)
        return {"ok": True}

    @app.get("/api/chat/sessions/{session_id}/messages")
    def api_chat_messages(session_id: str) -> dict[str, Any]:
        return {"messages": _chat_store().get_messages(session_id)}

    @app.post("/api/chat/sessions/{session_id}/send")
    def api_chat_send(session_id: str, body: dict[str, Any]) -> StreamingResponse:
        text = str(body.get("message") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="message cannot be empty")
        engine = _coordinator()

        def event_stream():
            for ev in engine.handle_message_stream(session_id, text):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # ── Agent Capability Hub & API Providers ────────────────────────
    @app.get("/api/agents/profiles")
    def api_agent_profiles() -> dict[str, Any]:
        _, pipeline = ctx.load_pipeline_cfg()
        profiles = discover_agent_profiles(
            pipeline, overrides_path=overrides_path, providers_path=providers_path
        )
        return {
            "profiles": [p.model_dump(mode="json") for p in profiles],
            "recommendations": recommend_stage_assignments(profiles),
        }

    @app.post("/api/agents/profiles/{name}")
    def api_agent_profile_update(name: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            overrides = load_profile_overrides(overrides_path)
            entry = dict(overrides.get(name, {}))
            for key in (
                "display_name",
                "enabled",
                "capabilities",
                "capability_scores",
                "cost_tier",
                "preferred_backend",
                "recommended_roles",
                "description",
                "adapter_config",
            ):
                if key in body:
                    entry[key] = body[key]
            overrides[name] = entry
            save_profile_overrides(overrides_path, overrides)
            return {"ok": True, "name": name}
        except Exception as exc:
            raise _err(exc) from exc

    @app.post("/api/agents/custom")
    def api_agent_add_custom(body: dict[str, Any]) -> dict[str, Any]:
        try:
            name = str(body.get("name") or "").strip()
            cmd = str(body.get("command_template") or "").strip()
            if not name or not cmd:
                raise ValueError("name and command_template are required")
            _, pipeline = ctx.load_pipeline_cfg()
            data = pipeline.model_dump(mode="json")
            data.setdefault("custom_adapters", {})[name] = {
                "type": "custom-cli",
                "command_template": cmd,
            }
            validated = Pipeline.model_validate(data)
            dumped = yaml.safe_dump(
                validated.model_dump(mode="json", exclude_none=True),
                allow_unicode=True,
                sort_keys=False,
            )
            atomic_write(ctx.pipeline_path, dumped.encode("utf-8"))
            overrides = load_profile_overrides(overrides_path)
            overrides[name] = {
                "display_name": str(body.get("display_name") or f"自定义 Agent ({name})"),
                "enabled": True,
                "capabilities": body.get("capabilities") or ["tool_use", "deep_reasoning"],
                "cost_tier": body.get("cost_tier") or "medium",
                "preferred_backend": body.get("preferred_backend") or "local",
                "description": str(body.get("description") or f"自定义 CLI：{cmd}"),
                "adapter_config": {"type": "custom-cli", "command_template": cmd},
            }
            save_profile_overrides(overrides_path, overrides)
            return {"ok": True, "name": name}
        except Exception as exc:
            raise _err(exc) from exc

    @app.get("/api/agents/recommend")
    def api_agents_recommend() -> dict[str, Any]:
        _, pipeline = ctx.load_pipeline_cfg()
        profiles = discover_agent_profiles(
            pipeline, overrides_path=overrides_path, providers_path=providers_path
        )
        return {"recommendations": recommend_stage_assignments(profiles)}

    @app.get("/api/providers")
    def api_providers_list() -> dict[str, Any]:
        return {
            "providers": [_mask_provider(p) for p in load_providers(providers_path)],
            "presets": PROVIDER_PRESETS,
        }

    @app.post("/api/providers")
    def api_providers_upsert(body: dict[str, Any]) -> dict[str, Any]:
        try:
            providers = load_providers(providers_path)
            existing_map = {p.id: p for p in providers}
            pid = str(body.get("id") or "").strip()
            if not pid:
                raise ValueError("provider id is required")
            # Keep existing inline key if masked placeholder returned
            inline = body.get("api_key_inline")
            if isinstance(inline, str) and "****" in inline and pid in existing_map:
                body = {**body, "api_key_inline": existing_map[pid].api_key_inline}
            item = ApiProvider.model_validate(body)
            if item.is_coordinator_default:
                for p in providers:
                    p.is_coordinator_default = False
            updated = [p for p in providers if p.id != item.id]
            updated.append(item)
            save_providers(providers_path, updated)
            return {"ok": True, "provider": _mask_provider(item)}
        except Exception as exc:
            raise _err(exc) from exc

    @app.delete("/api/providers/{provider_id}")
    def api_providers_delete(provider_id: str) -> dict[str, Any]:
        providers = [p for p in load_providers(providers_path) if p.id != provider_id]
        save_providers(providers_path, providers)
        return {"ok": True}

    @app.post("/api/providers/{provider_id}/test")
    def api_providers_test(provider_id: str) -> dict[str, Any]:
        providers = load_providers(providers_path)
        found = next((p for p in providers if p.id == provider_id), None)
        if found is None:
            raise HTTPException(status_code=404, detail="provider not found")
        ok, detail = test_provider_connection(found)
        return {"ok": ok, "detail": detail}

    # ── Skill Studio CRUD ───────────────────────────────────────────
    @app.get("/api/skills")
    def api_skills_list() -> dict[str, Any]:
        return {"skills": [s.model_dump(mode="json") for s in _skill_manager().list_skills()]}

    @app.get("/api/skills/detail")
    def api_skills_detail(name: str = Query(...)) -> dict[str, Any]:
        try:
            return {"skill": _skill_manager().get_skill(name).model_dump(mode="json")}
        except Exception as exc:
            raise _err(exc) from exc

    @app.post("/api/skills/save")
    def api_skills_save(body: dict[str, Any]) -> dict[str, Any]:
        try:
            saved = _skill_manager().save_skill(
                str(body["name"]),
                manifest_yaml=str(body["manifest_yaml"]),
                prompt_markdown=str(body["prompt_markdown"]),
            )
            return {"ok": True, "skill": saved.model_dump(mode="json")}
        except Exception as exc:
            raise _err(exc) from exc

    @app.post("/api/skills/create")
    def api_skills_create(body: dict[str, Any]) -> dict[str, Any]:
        try:
            created = _skill_manager().create_skill(
                name=str(body["name"]).strip(),
                stage=str(body["stage"]).strip(),
                description=str(body.get("description") or "").strip() or "自定义 Skill",
                prompt_markdown=str(body.get("prompt_markdown") or "# 自定义 Skill\n"),
                inputs=body.get("inputs"),
                outputs=body.get("outputs"),
                recommended_adapter=body.get("recommended_adapter"),
                target_categories=body.get("target_categories"),
            )
            return {"ok": True, "skill": created.model_dump(mode="json")}
        except Exception as exc:
            raise _err(exc) from exc

    @app.post("/api/skills/fork")
    def api_skills_fork(body: dict[str, Any]) -> dict[str, Any]:
        try:
            forked = _skill_manager().fork_skill(str(body["source_name"]), str(body["new_name"]))
            return {"ok": True, "skill": forked.model_dump(mode="json")}
        except Exception as exc:
            raise _err(exc) from exc

    @app.post("/api/skills/reset")
    def api_skills_reset(body: dict[str, Any]) -> dict[str, Any]:
        try:
            action = _skill_manager().reset_or_delete_skill(str(body["name"]))
            return {"ok": True, "action": action}
        except Exception as exc:
            raise _err(exc) from exc

    # ── Workflow & Config ───────────────────────────────────────────
    @app.get("/api/discover-agents")
    def api_discover_agents_compat() -> dict[str, Any]:
        return ctx.discover_agents_payload()

    @app.get("/api/config")
    def api_config_get() -> dict[str, Any]:
        p_path, pipeline = ctx.load_pipeline_cfg()
        e_path, env = ctx.load_env_cfg()
        return {
            "pipeline_path": str(p_path),
            "env_path": str(e_path) if e_path else str(ctx.env_path),
            "pipeline": pipeline.model_dump(mode="json"),
            "env": env.model_dump(mode="json", by_alias=True),
            "pipeline_yaml": p_path.read_text(encoding="utf-8") if p_path.is_file() else "",
            "env_yaml": e_path.read_text(encoding="utf-8") if (e_path and e_path.is_file()) else "",
        }

    @app.post("/api/config/apply-visual")
    def api_config_apply_visual(body: dict[str, Any]) -> dict[str, Any]:
        try:
            return ctx.apply_visual_pipeline(body)
        except Exception as exc:
            raise _err(exc) from exc

    @app.post("/api/config/save")
    def api_config_save(body: dict[str, Any]) -> dict[str, Any]:
        try:
            if "pipeline_yaml" in body:
                raw_yaml = str(body["pipeline_yaml"])
                Pipeline.model_validate(yaml.safe_load(raw_yaml))
                atomic_write(ctx.pipeline_path, raw_yaml.encode("utf-8"))
            if "env_yaml" in body:
                raw_env = str(body["env_yaml"])
                Env.model_validate(yaml.safe_load(raw_env))
                atomic_write(ctx.env_path, raw_env.encode("utf-8"))
            if "env_structured" in body and isinstance(body["env_structured"], dict):
                validated_env = Env.model_validate(body["env_structured"])
                dumped = yaml.safe_dump(
                    validated_env.model_dump(mode="json", by_alias=True, exclude_none=True),
                    allow_unicode=True,
                    sort_keys=False,
                )
                atomic_write(ctx.env_path, dumped.encode("utf-8"))
            return {"ok": True}
        except Exception as exc:
            raise _err(exc) from exc

    # ── Pipeline Actions ────────────────────────────────────────────
    @app.post("/api/scout")
    def api_scout(body: dict[str, Any]) -> dict[str, Any]:
        try:
            _, settings = ctx.load_env_cfg()
            tracker = Tracker(settings.paths.tracker_db_path)
            urls_text = str(body.get("urls", "")).strip()
            if urls_text:
                projects = [metadata_from_url(line.strip()) for line in urls_text.splitlines() if line.strip()]
            else:
                projects = search_projects(
                    str(body.get("platform", "github")).strip(),
                    str(body.get("query", "")).strip(),
                    settings.platforms,
                    limit=int(body.get("limit", 10)),
                )
            accepted = save_new_projects(projects, tracker, ctx.workspaces)
            return {"ok": True, "added": len(accepted), "targets": [p.model_dump(mode="json") for p in accepted]}
        except Exception as exc:
            raise _err(exc) from exc

    @app.post("/api/decide")
    def api_decide(body: dict[str, Any]) -> dict[str, Any]:
        try:
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
            return {"ok": True}
        except Exception as exc:
            raise _err(exc) from exc

    @app.post("/api/clone")
    def api_clone(body: dict[str, Any]) -> dict[str, Any]:
        try:
            repo = ctx.dispatcher().clone_target(str(body["target"]), backend_name=body.get("backend"))
            return {"ok": True, "repo_path": str(repo)}
        except Exception as exc:
            raise _err(exc) from exc

    @app.post("/api/resume-env")
    def api_resume_env(body: dict[str, Any]) -> dict[str, Any]:
        try:
            ctx.dispatcher().resume_environment(
                str(body["target"]),
                str(body["candidate"]),
                actor=str(body.get("actor", "reviewer")).strip() or "reviewer",
            )
            return {"ok": True}
        except Exception as exc:
            raise _err(exc) from exc

    @app.post("/api/stage")
    def api_stage(body: dict[str, Any]) -> dict[str, Any]:
        try:
            accepted = ctx.dispatcher().run_stage(
                str(body["stage"]),
                str(body["target"]),
                str(body["candidate"]) if body.get("candidate") else None,
            )
            return {"ok": True, "accepted": accepted}
        except Exception as exc:
            raise _err(exc) from exc

    @app.post("/api/sync-pull")
    def api_sync_pull(body: dict[str, Any]) -> dict[str, Any]:
        try:
            _, settings = ctx.load_env_cfg()
            paths = sync_pull(
                get_backend(str(body.get("backend", "ssh-ubuntu")), settings.backends),
                ctx.workspaces,
                str(body["target"]),
                str(body["candidate"]),
                replace=bool(body.get("replace", False)),
                settings=settings.docker_verify,
                tracker=Tracker(settings.paths.tracker_db_path),
            )
            return {"ok": True, "files": [str(p) for p in paths]}
        except Exception as exc:
            raise _err(exc) from exc

    @app.post("/api/report")
    def api_report(body: dict[str, Any]) -> dict[str, Any]:
        try:
            _, settings = ctx.load_env_cfg()
            out_dir = Path(str(body.get("out") or settings.paths.windows_report_output_dir))
            paths = ctx.dispatcher().report(str(body["target"]), str(body["candidate"]), out_dir)
            return {"ok": True, "files": [str(p) for p in paths]}
        except Exception as exc:
            raise _err(exc) from exc

    # ── Candidate Detail, Evidence & Docx Download ──────────────────
    @app.get("/api/candidate/{target}/{candidate}")
    def api_candidate(target: str, candidate: str) -> dict[str, Any]:
        try:
            return ctx.candidate_detail(target, candidate)
        except Exception as exc:
            raise _err(exc) from exc

    @app.get("/api/evidence/{target}/{candidate}/{filename}")
    def api_evidence_png(target: str, candidate: str, filename: str) -> Response:
        try:
            t, c = artifact_id(target), artifact_id(candidate)
            png = contained_path(ctx.workspaces, f"{t}/candidates/{c}/evidence/{filename}")
            if not png.is_file() or png.suffix.lower() != ".png":
                raise HTTPException(status_code=404, detail="evidence image not found")
            return Response(content=png.read_bytes(), media_type="image/png")
        except HTTPException:
            raise
        except Exception as exc:
            raise _err(exc) from exc

    @app.get("/api/download-docx/{target}/{candidate}")
    def api_download_docx(target: str, candidate: str) -> FileResponse:
        detail = ctx.candidate_detail(target, candidate)
        report_path = detail.get("report_path")
        if not report_path or not Path(report_path).is_file():
            raise HTTPException(status_code=404, detail="docx report not generated yet")
        file_path = Path(report_path)
        return FileResponse(path=file_path, filename=file_path.name)

    # ── Serve React SPA (built into src/auditflow/ui/dist) ──────────
    dist_dir = Path(__file__).resolve().parent / "dist"
    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
    agents_dir = dist_dir / "agents"
    if agents_dir.is_dir():
        app.mount("/agents", StaticFiles(directory=str(agents_dir)), name="agents")

    @app.get("/", response_class=HTMLResponse)
    def serve_root() -> HTMLResponse:
        index_dist = dist_dir / "index.html"
        if index_dist.is_file():
            return HTMLResponse(index_dist.read_text(encoding="utf-8"))
        fallback = files("auditflow.ui").joinpath("static/index.html").read_text(encoding="utf-8")
        return HTMLResponse(fallback)

    return app


def run_studio_ui(
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
    app = create_app(ctx)
    url = f"http://{host}:{port}"
    print(f"AuditFlow Studio UI listening at {url} (Press Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(app, host=host, port=port, log_level="warning")
