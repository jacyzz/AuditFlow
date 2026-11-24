import shutil
from pathlib import Path

import pytest
import yaml

FIXTURES = Path(__file__).parent / "fixtures"
TARGET = "github_example_policy_demo"
CANDIDATE = "CAND-01"


def _engine(tmp_path, *, scout_adapter="mock", scout_skill="scout/from-list"):
    from auditflow.adapters.base import AdapterResult, BaseAgentAdapter
    from auditflow.adapters.registry import AdapterRegistry
    from auditflow.core.config import Env, load_pipeline
    from auditflow.core.skill_registry import SkillRegistry
    from auditflow.core.state import Tracker
    from auditflow.dispatcher.engine import Dispatcher

    calls = []

    class RecordedAdapter(BaseAgentAdapter):
        def __init__(self, name, options):
            self.name = name

        def check_health(self):
            return True, "local fixture"

        def run(self, req, backend):
            calls.append((self.name, req.skill_path.parent.name, tuple(req.input_files)))
            shutil.copyfile(FIXTURES / req.output_file.name, req.output_file)
            return AdapterResult(ok=True, adapter_name=self.name, output_file=req.output_file)

    bindings = {
        "scout": scout_skill,
        "triage_project": "triage/project-worthiness",
        "surface_map": "audit/surface-mapper",
        "deep_audit": "audit/auth-rbac",
        "triage_vuln": "triage/vuln-worthiness",
        "verify": "verify/vm-plan-only",
        "report": "report/cnvd-docx-writer",
    }
    stages = {
        key: {"skill": skill, "adapter": scout_adapter if key == "scout" else "mock"}
        for key, skill in bindings.items()
    }
    stages["evidence"] = {"renderers": ["code", "http", "term"]}
    tmp_path.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        yaml.safe_dump({"pipeline_name": "fixture", "stages": stages}), encoding="utf-8"
    )
    pipeline = load_pipeline(config_path)
    tracker = Tracker(tmp_path / "tracker.sqlite")
    registry = AdapterRegistry()
    registry.register("mock", RecordedAdapter)
    registry.register("alternate", RecordedAdapter)
    skills = SkillRegistry(Path(__file__).resolve().parents[1] / "skills")
    root = tmp_path / "workspaces"
    dispatcher = Dispatcher(pipeline, Env(), tracker, skills, root, registry)
    return dispatcher, tracker, calls


def _before_verify(engine, tracker):
    engine.run_stage("scout", TARGET)
    engine.run_stage("triage_project", TARGET)
    assert tracker.target_status(TARGET) == "GATE1_PENDING"
    with pytest.raises(ValueError, match="GATE1_PENDING"):
        engine.run_stage("surface_map", TARGET)
    workspace = engine.workspaces / TARGET
    shutil.copytree(FIXTURES / "repo", workspace / "repo")
    engine.approve_project(TARGET, approve=True, actor="reviewer")
    engine.run_stage("surface_map", TARGET)
    audit_dir = workspace / "candidates" / CANDIDATE
    audit_dir.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "audit.json", audit_dir / "audit.json")
    engine.run_stage("deep_audit", TARGET)
    engine.run_stage("triage_vuln", TARGET)
    assert tracker.candidate_status(TARGET, CANDIDATE) == "GATE2_PENDING"
    with pytest.raises(ValueError, match="GATE2_PENDING"):
        engine.run_stage("verify", TARGET, CANDIDATE, supplied=FIXTURES / "verify.json")
    engine.approve_candidate(TARGET, CANDIDATE, approve=True, actor="reviewer")
    return audit_dir


def test_full_workflow_and_approval_events(tmp_path):
    engine, tracker, calls = _engine(tmp_path)
    audit_dir = _before_verify(engine, tracker)
    shutil.copyfile(FIXTURES / "deploy-log.json", audit_dir / "deploy-log.json")
    assert engine.run_stage("verify", TARGET, CANDIDATE, supplied=FIXTURES / "verify.json")
    engine.run_stage("evidence", TARGET, CANDIDATE)
    paths = engine.report(TARGET, CANDIDATE, tmp_path / "output")
    assert all(path.is_file() for path in paths)
    assert tracker.candidate_status(TARGET, CANDIDATE) == "REPORTED"
    assert tracker.target_status(TARGET) == "COMPLETED"
    assert {name for _, name, _ in calls} >= {"from-list", "surface-mapper", "auth-rbac"}
    with tracker.connect() as db:
        decisions = db.execute(
            "SELECT next_status FROM state_events WHERE actor = 'reviewer' ORDER BY event_id"
        ).fetchall()
    assert decisions == [("CLONED",), ("VERIFY_APPROVED",)]


def test_hot_swap_only_changes_config(tmp_path):
    first, _, original = _engine(tmp_path / "first")
    second, _, alternate = _engine(
        tmp_path / "second", scout_adapter="alternate", scout_skill="scout/infra-lib",
    )
    first.run_stage("scout", TARGET)
    second.run_stage("scout", TARGET)
    assert original == [("mock", "from-list", ())]
    assert alternate == [("alternate", "infra-lib", ())]


def test_blocker_pauses_and_requires_human_resume(tmp_path):
    import json

    engine, tracker, calls = _engine(tmp_path)
    audit_dir = _before_verify(engine, tracker)
    blocker = json.loads((FIXTURES / "deploy-log.json").read_text(encoding="utf-8"))
    blocker.update(final_status="NEEDS_HUMAN_ENV")
    (audit_dir / "deploy-log.json").write_text(json.dumps(blocker), encoding="utf-8")
    assert not engine.run_stage("verify", TARGET, CANDIDATE)
    assert tracker.candidate_status(TARGET, CANDIDATE) == "NEEDS_HUMAN_ENV"
    with pytest.raises(ValueError, match="NEEDS_HUMAN_ENV"):
        engine.run_stage("verify", TARGET, CANDIDATE, supplied=FIXTURES / "verify.json")
    engine.resume_environment(TARGET, CANDIDATE, actor="reviewer")
    assert tracker.candidate_status(TARGET, CANDIDATE) == "DEPLOYING"
    assert not any(skill == "vm-plan-only" for _, skill, _ in calls)


def test_builtin_manifests_load():
    from auditflow.core.skill_registry import SkillRegistry

    registry = SkillRegistry(Path(__file__).resolve().parents[1] / "skills")
    names = registry.list()
    assert len(names) == 15
    assert all(registry.get(name).prompt_path.is_file() for name in names)
