from pathlib import Path

import pytest


def test_example_config_loads():
    from auditflow.core.config import load_env, load_pipeline

    root = Path(__file__).resolve().parents[1]
    config = root / "config"
    pipeline = load_pipeline(config / "pipeline.example.yaml")
    assert pipeline.stages["deep_audit"].skill_names[0] == "audit/auth-rbac"
    assert load_env(config / "env.example.yaml").docker_verify.max_retries == 2


def test_registry_manifest_and_handoff(tmp_path):
    from auditflow.adapters.base import AdapterRequest
    from auditflow.adapters.registry import AdapterRegistry
    from auditflow.backends.local import LocalBackend
    from auditflow.core.skill_registry import SkillRegistry

    skill = tmp_path / "report" / "example"
    skill.mkdir(parents=True)
    (skill / "skill.yaml").write_text(
        "name: report/example\nstage: report\nversion: '1.0.0'\n"
        "description: Example\ninputs: [meta.json]\noutputs: [cnvd-form.json]\n",
        encoding="utf-8",
    )
    (skill / "SKILL.md").write_text("Use the supplied facts.", encoding="utf-8")
    manifest = SkillRegistry(tmp_path).get("report/example")
    assert manifest.outputs == ["cnvd-form.json"]
    adapter = AdapterRegistry({"handoff": {"type": "custom-cli"}}).get("handoff")
    request = AdapterRequest(
        stage="report",
        skill_path=manifest.prompt_path,
        workspace_dir=tmp_path,
        input_files={},
        output_file=tmp_path / "cnvd-form.json",
    )
    result = adapter.run(request, LocalBackend())
    assert not result.ok
    assert result.trajectory_path.is_file()
    assert "Use the supplied facts." in result.trajectory_path.read_text(encoding="utf-8")
    assert not request.output_file.exists()


def test_config_rejects_duplicate_yaml_keys(tmp_path):
    from auditflow.core.config import load_env

    path = tmp_path / "env.yaml"
    path.write_text("paths: {}\npaths: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_env(path)
