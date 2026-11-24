import json
import sys
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def test_local_backend_run_cmd_and_push_file(tmp_path):
    from auditflow.backends.local import LocalBackend

    backend = LocalBackend(tmp_path)
    src = tmp_path / "source.txt"
    src.write_text("hello auditflow", encoding="utf-8")
    backend.push_file(src, "nested/pushed.txt")
    assert backend.read_file("nested/pushed.txt") == b"hello auditflow"

    res = backend.run_cmd(
        [sys.executable, "-c", "import os; print(os.environ['AF_TEST_VAR'])"],
        env={"AF_TEST_VAR": "ok-value"},
        timeout=15,
    )
    assert res.ok
    assert res.stdout.strip() == "ok-value"


def test_openai_api_adapter_real_http_execution(tmp_path):
    from auditflow.adapters.base import AdapterRequest
    from auditflow.adapters.openai_api import OpenAIAPIAdapter
    from auditflow.backends.local import LocalBackend
    from auditflow.core.schemas import Meta, read_contract

    sample_meta = (FIXTURES / "meta.json").read_text(encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "deepseek-chat"
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "model": "deepseek-chat",
                "choices": [{"message": {"content": f"```json\n{sample_meta}\n```"}}],
            },
        )

    skill = tmp_path / "SKILL.md"
    skill.write_text("Output meta.json.", encoding="utf-8")
    out_file = tmp_path / "logs" / "meta.json"
    req = AdapterRequest(
        stage="scout",
        skill_path=skill,
        workspace_dir=tmp_path,
        input_files={},
        output_file=out_file,
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = OpenAIAPIAdapter("openai-api", {"model": "deepseek-chat"}, client=client)
    result = adapter.run(req, LocalBackend(tmp_path))
    assert result.ok
    assert result.output_file == out_file
    assert result.trajectory_path is not None and result.trajectory_path.is_file()
    loaded = read_contract(out_file, Meta)
    assert loaded.target_id == "github_example_policy_demo"


def test_custom_cli_adapter_executes_command_template(tmp_path):
    from auditflow.adapters.base import AdapterRequest
    from auditflow.adapters.custom_cli import CustomCLIAdapter
    from auditflow.backends.local import LocalBackend
    from auditflow.core.schemas import Meta, read_contract

    script = tmp_path / "fake_agent.py"
    sample_meta = (FIXTURES / "meta.json").read_text(encoding="utf-8")
    script.write_text(
        f"import pathlib, sys\npathlib.Path(sys.argv[1]).write_text({sample_meta!r}, encoding='utf-8')\n",
        encoding="utf-8",
    )
    skill = tmp_path / "SKILL.md"
    skill.write_text("Write meta.json", encoding="utf-8")
    out_file = tmp_path / "logs" / "meta.json"
    out_file.parent.mkdir(parents=True)
    template = f'"{sys.executable}" "{script}" "{{output_file}}"'
    adapter = CustomCLIAdapter("my-agent", {"command_template": template})
    req = AdapterRequest(
        stage="scout",
        skill_path=skill,
        workspace_dir=tmp_path,
        input_files={},
        output_file=out_file,
    )
    result = adapter.run(req, LocalBackend(tmp_path))
    assert result.ok
    assert read_contract(out_file, Meta).target_id == "github_example_policy_demo"


def test_docker_compose_deploy_retries_and_auto_teardown(tmp_path):
    from auditflow.backends.base import BaseExecutionBackend, CmdResult
    from auditflow.core.config import DockerSettings
    from auditflow.environment import build_docker_env, run_docker_compose_deploy

    calls: list[tuple[list[str], dict[str, str] | None]] = []

    class FakeBackend(BaseExecutionBackend):
        name = "ssh-ubuntu"

        def run_cmd(self, argv, *, cwd=None, env=None, timeout=300):
            calls.append((argv, env))
            if "down" in argv:
                return CmdResult(returncode=0, stdout="removed")
            return CmdResult(returncode=1, stderr="image pull failed")

        def read_file(self, path):
            raise FileNotFoundError(path)

        def push_file(self, local_path, remote_path):
            pass

        def list_png(self, path):
            return []

        def check_health(self):
            return True, "fake"

    settings = DockerSettings(
        http_proxy="http://127.0.0.1:7890",
        https_proxy="http://127.0.0.1:7890",
        max_retries=2,
        enforce_port_range=False,
        burp_upstream_proxy="http://127.0.0.1:8080",
    )
    env_map = build_docker_env(settings)
    assert env_map["HTTP_PROXY"] == "http://127.0.0.1:7890"
    assert env_map["AUDITFLOW_BURP_UPSTREAM_PROXY"] == "http://127.0.0.1:8080"

    deploy_log = run_docker_compose_deploy(
        FakeBackend(),
        tmp_path,
        "CAND-01",
        settings,
        exposed_base_url="http://127.0.0.1:8035",
    )
    assert deploy_log.final_status == "NEEDS_HUMAN_ENV"
    assert deploy_log.teardown_completed is True
    assert len(deploy_log.attempts) == 3  # 1 initial + 2 retries
    assert any("down" in argv for argv, _ in calls)
    assert calls[0][1]["HTTPS_PROXY"] == "http://127.0.0.1:7890"


def test_http_client_for_verify_enforces_isolated_guardrail():
    from auditflow.core.config import DockerSettings
    from auditflow.environment import http_client_for_verify

    settings = DockerSettings(enforce_port_range=False)
    with http_client_for_verify(settings) as client:
        with pytest.raises(ValueError, match="outside private and loopback"):
            client.get("https://8.8.8.8/")


def test_capture_web_shot_rejects_public_live_url(tmp_path):
    from auditflow.core.config import DockerSettings
    from auditflow.evidence.web_shot import capture_web_shot

    with pytest.raises(ValueError, match="outside private and loopback"):
        capture_web_shot(
            "https://8.8.8.8/admin",
            tmp_path / "shot.png",
            docker_settings=DockerSettings(enforce_port_range=False),
        )


def test_dispatcher_verify_invokes_real_adapter(tmp_path):
    """Verify stage must call the configured adapter rather than forcing HandoffAdapter."""
    import shutil

    from tests.test_dispatcher_state_machine import CANDIDATE, TARGET, _before_verify, _engine

    engine, tracker, calls = _engine(tmp_path)
    audit_dir = _before_verify(engine, tracker)
    shutil.copyfile(FIXTURES / "deploy-log.json", audit_dir / "deploy-log.json")
    assert engine.run_stage("verify", TARGET, CANDIDATE)
    assert tracker.candidate_status(TARGET, CANDIDATE) == "VERIFIED"
    assert any(skill == "vm-plan-only" for _, skill, _ in calls)
