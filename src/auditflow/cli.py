import json
import sysconfig
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from auditflow.adapters.registry import AdapterRegistry
from auditflow.backends import get_backend
from auditflow.core.config import Env, load_env, load_pipeline
from auditflow.core.paths import atomic_write, contained_path
from auditflow.core.schemas import (
    AuditDisposition,
    DeployLog,
    HttpStep,
    Meta,
    TermStep,
    Verify,
    export_schemas,
    load_artifact,
    read_contract,
    save_artifact,
)
from auditflow.core.skill_registry import SkillRegistry
from auditflow.core.state import Tracker
from auditflow.dispatcher.engine import Dispatcher
from auditflow.dispatcher.gates import candidates_table, projects_table
from auditflow.environment import (
    run_docker_compose_deploy,
    suggest_local_port,
    teardown_docker_compose,
    validate_environment_records,
)
from auditflow.evidence.code_shot import render_code_shot
from auditflow.evidence.common import BrowserUnavailable
from auditflow.evidence.http_shot import render_http_shot
from auditflow.evidence.term_shot import render_term_shot
from auditflow.evidence.web_shot import capture_web_shot
from auditflow.reporting.report import generate_report
from auditflow.scout.dedup import save_new_projects
from auditflow.scout.platforms import import_projects, search_projects
from auditflow.sync import sync_pull
from auditflow.ui import run_ui

app = typer.Typer(no_args_is_help=True, help="Modular multi-agent security audit & disclosure CLI.")
console = Console()
errors = Console(stderr=True)
DEFAULT_PIPELINE = Path("config/pipeline.yaml")
DEFAULT_ENV = Path("config/env.yaml")


def _fail(exc: Exception) -> None:
    errors.print(str(exc), markup=False)
    raise typer.Exit(1) from exc


def _shared_data() -> Path:
    installed = Path(sysconfig.get_path("data")) / "share/auditflow"
    local_target = Path(__file__).resolve().parents[1] / "share/auditflow"
    return local_target if local_target.is_dir() else installed


def _pipeline_file(path: Path) -> Path:
    fallback = path.with_name("pipeline.example.yaml")
    if path.is_file() or path != DEFAULT_PIPELINE:
        return path
    if fallback.is_file():
        return fallback
    return _shared_data() / "config/pipeline.example.yaml"


def _env_file(path: Path) -> Env:
    return load_env(path if path.is_file() or path != DEFAULT_ENV else None)


def _dispatcher(pipeline: Path, env: Path, workspaces: Path, skills: Path) -> Dispatcher:
    config = load_pipeline(_pipeline_file(pipeline))
    settings = _env_file(env)
    if skills == Path("skills") and not skills.is_dir():
        skills = _shared_data() / "skills"
    return Dispatcher(
        config, settings, Tracker(settings.paths.tracker_db_path), SkillRegistry(skills), workspaces
    )


@app.command()
def validate(
    artifact: Path,
    schema: Annotated[str | None, typer.Option(help="Contract filename, if different.")] = None,
) -> None:
    """Validate a JSON artifact against its contract."""
    try:
        result = load_artifact(artifact, schema)
    except (ValueError, OSError) as exc:
        _fail(exc)
    console.print(f"{artifact.name}: {type(result).__name__} valid", markup=False)


@app.command("export-schemas")
def export_schemas_command(out: Path) -> None:
    """Export the seven JSON Schema documents."""
    for name, schema in export_schemas().items():
        text = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
        atomic_write(out / f"{name.removesuffix('.json')}.schema.json", text.encode("utf-8"))
    console.print(f"Exported seven schemas to {out}", markup=False)


@app.command()
def doctor(
    pipeline: Annotated[Path, typer.Option()] = DEFAULT_PIPELINE,
    env: Annotated[Path, typer.Option()] = DEFAULT_ENV,
) -> None:
    """Check configured execution backends and agent adapters."""
    table = Table("Component", "Status", "Detail")
    try:
        config = load_pipeline(_pipeline_file(pipeline))
        settings = _env_file(env)
        registry = AdapterRegistry(config.adapters | config.custom_adapters)
        adapters = {stage.adapter for stage in config.stages.values() if stage.adapter}
        backends = {stage.backend for stage in config.stages.values()}
        for name in sorted(adapters):
            ok, detail = registry.get(name).check_health()
            table.add_row(name, "available" if ok else "unavailable", detail)
        for name in sorted(backends):
            try:
                ok, detail = get_backend(name, settings.backends).check_health()
            except ValueError as exc:
                ok, detail = False, str(exc)
            table.add_row(name, "available" if ok else "unavailable", detail)
    except (ValueError, OSError) as exc:
        _fail(exc)
    console.print(table)


@app.command()
def report(
    workspace: Annotated[Path | None, typer.Option(help="Directory containing meta.json.")] = None,
    target: Annotated[str | None, typer.Option(help="Target under workspaces/.")] = None,
    candidate: Annotated[str | None, typer.Option(help="Candidate under candidates/.")] = None,
    out: Annotated[Path | None, typer.Option(help="Output directory.")] = None,
    env: Annotated[Path, typer.Option()] = DEFAULT_ENV,
    pipeline: Annotated[Path, typer.Option()] = DEFAULT_PIPELINE,
    workspaces: Annotated[Path, typer.Option()] = Path("workspaces"),
    skills: Annotated[Path, typer.Option()] = Path("skills"),
) -> None:
    """Generate a local Word draft and CNVD copy-and-paste form."""
    try:
        if (workspace is None) == (target is None):
            raise ValueError("specify exactly one of --workspace or --target")
        settings = _env_file(env)
        output = out or settings.paths.windows_report_output_dir
        excel = settings.paths.excel_sync
        if target is not None:
            if candidate is None:
                raise ValueError("--candidate is required with --target")
            result = _dispatcher(pipeline, env, workspaces, skills).report(target, candidate, output)
        else:
            result = generate_report(
                workspace,
                output,
                candidate=candidate,
                excel=Path(excel.excel_path) if excel.enabled else None,
            )
    except (ValueError, OSError, BrowserUnavailable) as exc:
        _fail(exc)
    for path in result:
        console.print(str(path), markup=False)


@app.command()
def scout(
    from_list: Annotated[Path | None, typer.Option(help="Local repository URL list.")] = None,
    platform: Annotated[str | None, typer.Option(help="github, gitee or gitcode.")] = None,
    query: Annotated[str | None, typer.Option(help="Repository metadata search keyword.")] = None,
    limit: Annotated[int, typer.Option(min=1, max=100)] = 10,
    history: Annotated[Path | None, typer.Option(help="Historical Excel or URL list.")] = None,
    workspaces: Annotated[Path, typer.Option()] = Path("workspaces"),
    env: Annotated[Path, typer.Option()] = DEFAULT_ENV,
) -> None:
    """Import a list or fetch repository metadata from GitHub/Gitee/GitCode."""
    try:
        settings = _env_file(env)
        if from_list is not None and platform is None and query is None:
            projects = import_projects(from_list)[:limit]
        elif from_list is None and platform and query:
            projects = search_projects(platform, query, settings.platforms, limit=limit)
        else:
            raise ValueError("specify --from-list or both --platform and --query")
        tracker = Tracker(settings.paths.tracker_db_path)
        accepted = save_new_projects(projects, tracker, workspaces, history=history)
    except (ValueError, OSError) as exc:
        _fail(exc)
    console.print(projects_table(accepted))


@app.command()
def clone(
    target: str,
    backend: Annotated[str | None, typer.Option(help="Override execution backend.")] = None,
    pipeline: Annotated[Path, typer.Option()] = DEFAULT_PIPELINE,
    env: Annotated[Path, typer.Option()] = DEFAULT_ENV,
    workspaces: Annotated[Path, typer.Option()] = Path("workspaces"),
) -> None:
    """Shallow-clone the approved target repository into workspaces/<target>/repo/."""
    try:
        repo_path = _dispatcher(pipeline, env, workspaces, Path("skills")).clone_target(
            target, backend_name=backend
        )
    except (ValueError, OSError) as exc:
        _fail(exc)
    console.print(str(repo_path), markup=False)


@app.command("stage")
def run_stage(
    stage: str,
    target: str,
    candidate: Annotated[str | None, typer.Option()] = None,
    artifact: Annotated[Path | None, typer.Option(help="Manually reviewed artifact to import.")] = None,
    pipeline: Annotated[Path, typer.Option()] = DEFAULT_PIPELINE,
    env: Annotated[Path, typer.Option()] = DEFAULT_ENV,
    workspaces: Annotated[Path, typer.Option()] = Path("workspaces"),
    skills: Annotated[Path, typer.Option()] = Path("skills"),
) -> None:
    """Execute a stage using its configured adapter or import a reviewed artifact."""
    try:
        dispatcher = _dispatcher(pipeline, env, workspaces, skills)
        accepted = dispatcher.run_stage(stage, target, candidate, supplied=artifact)
        state = (
            dispatcher.tracker.candidate_status(target, candidate)
            if candidate
            else None
        )
        if stage == "triage_project" and accepted:
            root = dispatcher.workspace(target)
            console.print(projects_table([read_contract(root / "meta.json", Meta)]))
        elif stage == "triage_vuln" and accepted:
            root = dispatcher.workspace(target)
            disposition = read_contract(root / "audit-disposition.json", AuditDisposition)
            console.print(candidates_table(disposition, dispatcher.tracker))
    except (ValueError, OSError, BrowserUnavailable) as exc:
        _fail(exc)
    if accepted:
        console.print("Stage accepted")
    elif state == "NEEDS_HUMAN_ENV":
        console.print("NEEDS_HUMAN_ENV. Review the deployment log before resuming.")
    else:
        console.print("Awaiting host subagent or manually reviewed artifact. See workspace logs/.")


@app.command()
def decide(
    target: str,
    actor: Annotated[str, typer.Option()],
    approve: Annotated[bool, typer.Option("--approve/--reject")],
    candidate: Annotated[str | None, typer.Option()] = None,
    auto_clone: Annotated[bool, typer.Option(help="Shallow-clone repo on Gate 1 approval.")] = False,
    pipeline: Annotated[Path, typer.Option()] = DEFAULT_PIPELINE,
    env: Annotated[Path, typer.Option()] = DEFAULT_ENV,
    workspaces: Annotated[Path, typer.Option()] = Path("workspaces"),
) -> None:
    """Record a named human decision at Gate 1 or Gate 2."""
    try:
        dispatcher = _dispatcher(pipeline, env, workspaces, Path("skills"))
        if candidate:
            dispatcher.approve_candidate(target, candidate, approve=approve, actor=actor)
        else:
            dispatcher.approve_project(target, approve=approve, actor=actor, auto_clone=auto_clone)
    except (ValueError, OSError) as exc:
        _fail(exc)
    console.print("Decision recorded")


@app.command("resume-environment")
def resume_environment(
    target: str,
    candidate: str,
    actor: Annotated[str, typer.Option()],
    pipeline: Annotated[Path, typer.Option()] = DEFAULT_PIPELINE,
    env: Annotated[Path, typer.Option()] = DEFAULT_ENV,
    workspaces: Annotated[Path, typer.Option()] = Path("workspaces"),
) -> None:
    """Record that a human reviewer reopened a blocked environment review."""
    try:
        _dispatcher(pipeline, env, workspaces, Path("skills")).resume_environment(
            target, candidate, actor=actor
        )
    except (ValueError, OSError) as exc:
        _fail(exc)
    console.print("Environment review reopened")


@app.command("deploy-docker")
def deploy_docker(
    target: str,
    candidate: str,
    exposed_url: Annotated[str | None, typer.Option(help="Isolated base URL exposed by compose.")] = None,
    healthcheck_url: Annotated[str | None, typer.Option(help="Isolated URL for healthcheck.")] = None,
    compose_file: Annotated[str | None, typer.Option(help="Optional compose filename.")] = None,
    backend: Annotated[str, typer.Option(help="local, ssh-ubuntu or wsl2.")] = "local",
    workspaces: Annotated[Path, typer.Option()] = Path("workspaces"),
    env: Annotated[Path, typer.Option()] = DEFAULT_ENV,
) -> None:
    """Deploy an isolated docker-compose stack with proxy injection & fail-fast retry cap."""
    try:
        settings = _env_file(env)
        exec_backend = get_backend(backend, settings.backends)
        root = contained_path(workspaces, target)
        repo_dir = contained_path(root, "repo")
        log = run_docker_compose_deploy(
            exec_backend,
            repo_dir,
            candidate,
            settings.docker_verify,
            exposed_base_url=exposed_url,
            healthcheck_url=healthcheck_url,
            compose_file=compose_file,
        )
        out_path = contained_path(root, f"candidates/{candidate}/deploy-log.json")
        save_artifact(out_path, log)
    except (ValueError, OSError) as exc:
        _fail(exc)
    console.print(f"{log.final_status} -> {out_path}", markup=False)


@app.command("teardown-docker")
def teardown_docker(
    target: str,
    compose_file: Annotated[str | None, typer.Option(help="Optional compose filename.")] = None,
    backend: Annotated[str, typer.Option(help="local, ssh-ubuntu or wsl2.")] = "local",
    workspaces: Annotated[Path, typer.Option()] = Path("workspaces"),
    env: Annotated[Path, typer.Option()] = DEFAULT_ENV,
) -> None:
    """Stop and clean up an isolated docker-compose stack."""
    try:
        settings = _env_file(env)
        exec_backend = get_backend(backend, settings.backends)
        repo_dir = contained_path(contained_path(workspaces, target), "repo")
        ok = teardown_docker_compose(exec_backend, repo_dir, compose_file=compose_file)
    except (ValueError, OSError) as exc:
        _fail(exc)
    console.print("teardown ok" if ok else "teardown returned non-zero")


@app.command()
def status(
    target: str,
    candidate: Annotated[str | None, typer.Option()] = None,
    env: Annotated[Path, typer.Option()] = DEFAULT_ENV,
) -> None:
    """Show the tracked project or candidate state."""
    try:
        db = Tracker(_env_file(env).paths.tracker_db_path)
        state = db.candidate_status(target, candidate) if candidate else db.target_status(target)
    except (ValueError, OSError) as exc:
        _fail(exc)
    console.print(state)


@app.command("web-snapshot")
def web_snapshot(
    source: str,
    out: Path,
    show_address_bar: bool = False,
    wait_selector: Annotated[str | None, typer.Option()] = None,
    cookies_json: Annotated[Path | None, typer.Option(help="JSON file with Playwright cookies.")] = None,
    headers_json: Annotated[Path | None, typer.Option(help="JSON file with extra HTTP headers.")] = None,
    env: Annotated[Path, typer.Option()] = DEFAULT_ENV,
) -> None:
    """Render a saved local HTML snapshot or live isolated HTTP(S) URL to PNG."""
    try:
        settings = _env_file(env).docker_verify
        cookies = json.loads(cookies_json.read_text(encoding="utf-8")) if cookies_json else None
        headers = json.loads(headers_json.read_text(encoding="utf-8")) if headers_json else None
        capture_web_shot(
            source,
            out,
            show_address_bar=show_address_bar,
            wait_selector=wait_selector,
            docker_settings=settings,
            cookies=cookies,
            headers=headers,
        )
    except (ValueError, OSError, BrowserUnavailable) as exc:
        _fail(exc)
    console.print(str(out), markup=False)


@app.command("code-shot")
def code_shot(
    source: Path,
    start: int,
    end: int,
    out: Path,
    highlight: Annotated[list[int] | None, typer.Option(help="Repeat for each marked line.")] = None,
    label: Annotated[str | None, typer.Option()] = None,
    context: Annotated[int, typer.Option(min=0)] = 0,
) -> None:
    """Render a source excerpt with original line numbers."""
    try:
        render_code_shot(
            source,
            start,
            end,
            out,
            highlight=highlight,
            label=label,
            context=context,
            allow_fallback=True,
        )
    except (ValueError, OSError, BrowserUnavailable) as exc:
        _fail(exc)
    console.print(str(out), markup=False)


@app.command("http-shot")
def http_shot(verify: Path, step: int, out: Path) -> None:
    """Render a saved HTTP exchange as a request and response card."""
    try:
        record = read_contract(verify, Verify)
        item = next((x for x in record.steps if x.step_no == step), None)
        if not isinstance(item, HttpStep):
            raise ValueError("the selected step is not a saved HTTP exchange")
        render_http_shot(
            item.raw_request,
            item.raw_response,
            out,
            title=item.title,
            highlight=item.highlight_response_patterns,
            allow_fallback=True,
        )
    except (ValueError, OSError, BrowserUnavailable) as exc:
        _fail(exc)
    console.print(str(out), markup=False)


@app.command("term-shot")
def term_shot(verify: Path, step: int, out: Path) -> None:
    """Render a saved terminal transcript."""
    try:
        record = read_contract(verify, Verify)
        item = next((x for x in record.steps if x.step_no == step), None)
        if not isinstance(item, TermStep):
            raise ValueError("the selected step is not a saved terminal transcript")
        render_term_shot(
            item.command,
            item.stdout,
            out,
            title=item.title,
            highlight=item.highlight_patterns,
            exit_code=item.exit_code,
            allow_fallback=True,
        )
    except (ValueError, OSError, BrowserUnavailable) as exc:
        _fail(exc)
    console.print(str(out), markup=False)


@app.command("check-environment")
def check_environment(
    deploy_log: Annotated[Path | None, typer.Option(help="Recorded deploy-log.json.")] = None,
    suggest_port: Annotated[bool, typer.Option(help="Check for a free loopback port.")] = False,
    env: Annotated[Path, typer.Option()] = DEFAULT_ENV,
) -> None:
    """Validate a recorded environment URL or check a loopback port."""
    try:
        settings = _env_file(env).docker_verify
        if deploy_log is None and not suggest_port:
            raise ValueError("specify --deploy-log or --suggest-port")
        if deploy_log is not None:
            record = read_contract(deploy_log, DeployLog)
            validate_environment_records(settings, record)
            console.print(f"{record.final_status} · cleanup recorded: {record.teardown_completed}")
        if suggest_port:
            console.print(suggest_local_port(settings))
    except (ValueError, OSError) as exc:
        _fail(exc)


@app.command("sync-pull")
def sync_pull_command(
    target: str,
    candidate: str,
    backend: Annotated[str, typer.Option(help="ssh-ubuntu or wsl2.")] = "ssh-ubuntu",
    workspaces: Annotated[Path, typer.Option()] = Path("workspaces"),
    env: Annotated[Path, typer.Option()] = DEFAULT_ENV,
    replace: Annotated[bool, typer.Option(help="Replace differing local artifact contents.")] = False,
) -> None:
    """Pull JSON contracts and evidence PNGs from a configured artifact host."""
    try:
        if backend not in {"ssh-ubuntu", "wsl2"}:
            raise ValueError("choose ssh-ubuntu or wsl2 for remote artifact sync")
        settings = _env_file(env)
        paths = sync_pull(
            get_backend(backend, settings.backends),
            workspaces,
            target,
            candidate,
            replace=replace,
            settings=settings.docker_verify,
            tracker=Tracker(settings.paths.tracker_db_path),
        )
    except (ValueError, OSError, SyntaxError) as exc:
        _fail(exc)
    for path in paths:
        console.print(str(path), markup=False)


@app.command()
def ui(
    host: Annotated[str, typer.Option(help="Bind host (default 127.0.0.1).")] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1024, max=65535)] = 8787,
    pipeline: Annotated[Path, typer.Option()] = DEFAULT_PIPELINE,
    env: Annotated[Path, typer.Option()] = DEFAULT_ENV,
    workspaces: Annotated[Path, typer.Option()] = Path("workspaces"),
    skills: Annotated[Path, typer.Option()] = Path("skills"),
    open_browser: Annotated[bool, typer.Option("--open/--no-open")] = True,
) -> None:
    """Launch the local AuditFlow Web UI dashboard (pipeline board, gates, config, screenshots & CNVD form)."""
    try:
        resolved_skills = skills
        if resolved_skills == Path("skills") and not resolved_skills.is_dir():
            resolved_skills = _shared_data() / "skills"
        run_ui(
            host=host,
            port=port,
            pipeline_path=pipeline,
            env_path=env,
            workspaces=workspaces,
            skills_dir=resolved_skills,
            open_browser=open_browser,
        )
    except (ValueError, OSError) as exc:
        _fail(exc)
