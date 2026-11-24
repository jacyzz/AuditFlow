import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def _make_studio_client(tmp_path: Path) -> tuple[TestClient, Path, Path]:
    from auditflow.ui.app import create_app
    from auditflow.ui.server import UIContext

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True)
    pipeline_path = cfg_dir / "pipeline.yaml"
    env_path = cfg_dir / "env.yaml"
    shutil.copyfile(ROOT / "config" / "pipeline.example.yaml", pipeline_path)
    env_path.write_text(
        f"paths:\n"
        f"  windows_report_output_dir: '{(tmp_path / 'out').as_posix()}'\n"
        f"  tracker_db_path: '{(tmp_path / 'tracker.sqlite').as_posix()}'\n"
        f"  local_cache_dir: '{(tmp_path / 'cache').as_posix()}'\n",
        encoding="utf-8",
    )

    skills_copy = tmp_path / "skills"
    shutil.copytree(ROOT / "skills", skills_copy)

    ctx = UIContext(
        pipeline_path=pipeline_path,
        env_path=env_path,
        workspaces=tmp_path / "workspaces",
        skills_dir=skills_copy,
    )
    app = create_app(ctx)
    return TestClient(app), skills_copy, cfg_dir


def test_studio_spa_and_assets_served(tmp_path: Path) -> None:
    client, _, _ = _make_studio_client(tmp_path)
    res = client.get("/")
    assert res.status_code == 200
    assert "AuditFlow Studio" in res.text
    # Ensure the built Vite bundle is actually being served rather than the legacy fallback
    assert "/assets/" in res.text
    # Brand SVG icons served under /agents/
    icon = client.get("/agents/codex-light.svg")
    assert icon.status_code == 200
    assert "svg" in icon.headers.get("content-type", "")


def test_agent_profiles_custom_and_heterogeneous_recommendation(tmp_path: Path) -> None:
    client, _, _ = _make_studio_client(tmp_path)

    res = client.get("/api/agents/profiles")
    assert res.status_code == 200
    data = res.json()
    names = {p["name"] for p in data["profiles"]}
    assert {"codex", "claude-code", "dsh", "openai-api", "native-subagent"} <= names

    # Enable two distinct strong agents so heterogeneous cross-review must assign different ones
    r1 = client.post(
        "/api/agents/profiles/codex",
        json={"enabled": True, "capabilities": ["deep_reasoning", "docker_verify", "tool_use"]},
    )
    assert r1.status_code == 200
    r2 = client.post(
        "/api/agents/profiles/claude-code",
        json={"enabled": True, "capabilities": ["deep_reasoning", "long_context", "cn_writing"]},
    )
    assert r2.status_code == 200

    # Add a custom CLI agent
    rc = client.post(
        "/api/agents/custom",
        json={
            "name": "my-custom-auditor",
            "display_name": "自定义审计 Agent",
            "command_template": "python -c 'print(1)' --out {output_file}",
            "capabilities": ["bulk_triage", "cn_writing"],
            "cost_tier": "low",
        },
    )
    assert rc.status_code == 200

    rec_res = client.get("/api/agents/recommend")
    assert rec_res.status_code == 200
    recs = rec_res.json()["recommendations"]
    assert "deep_audit" in recs
    assert "triage_vuln" in recs
    # Heterogeneous cross-review: triage_vuln MUST differ from deep_audit when >=2 agents enabled
    assert recs["deep_audit"]["adapter"] != recs["triage_vuln"]["adapter"]


def test_providers_masking_roundtrip_and_connection_test(tmp_path: Path, monkeypatch) -> None:
    client, _, _ = _make_studio_client(tmp_path)

    # Create provider with inline key
    res = client.post(
        "/api/providers",
        json={
            "id": "deepseek-main",
            "name": "DeepSeek Main",
            "preset": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "default_model": "deepseek-chat",
            "models": ["deepseek-chat", "deepseek-reasoner"],
            "api_key_inline": "sk-test-secret-987654321",
            "enabled": True,
            "is_coordinator_default": True,
        },
    )
    assert res.status_code == 200
    masked = res.json()["provider"]["api_key_inline"]
    assert "****" in masked
    assert "987654321" not in masked

    # List providers verifies masking
    listed = client.get("/api/providers").json()
    assert len(listed["providers"]) == 1
    assert "****" in listed["providers"][0]["api_key_inline"]

    # Re-saving with masked placeholder preserves original inline secret
    res2 = client.post(
        "/api/providers",
        json={
            **listed["providers"][0],
            "default_model": "deepseek-reasoner",
        },
    )
    assert res2.status_code == 200

    # Mock connection test
    import auditflow.ui.app as ui_app

    monkeypatch.setattr(ui_app, "test_provider_connection", lambda p: (True, f"OK ({p.default_model})"))
    test_res = client.post("/api/providers/deepseek-main/test")
    assert test_res.status_code == 200
    assert test_res.json() == {"ok": True, "detail": "OK (deepseek-reasoner)"}

    # Delete provider
    del_res = client.delete("/api/providers/deepseek-main")
    assert del_res.status_code == 200
    assert client.get("/api/providers").json()["providers"] == []


def test_skill_studio_crud_and_safe_builtin_overlay(tmp_path: Path) -> None:
    client, skills_copy, _ = _make_studio_client(tmp_path)

    # List built-in skills
    listed = client.get("/api/skills").json()["skills"]
    assert len(listed) == 15
    assert all(s["source"] == "builtin" for s in listed)

    # Inspect built-in skill detail
    target_skill = "audit/auth-rbac"
    detail = client.get("/api/skills/detail", params={"name": target_skill}).json()["skill"]
    original_md = detail["prompt_markdown"]
    original_disk = (skills_copy / "audit" / "auth-rbac" / "SKILL.md").read_text(encoding="utf-8")
    assert original_md == original_disk

    # Override built-in skill -> writes only to skills_custom/, NEVER mutates skills/
    new_md = original_md + "\n\n## Custom Note\nCheck MCP tool permissions.\n"
    saved = client.post(
        "/api/skills/save",
        json={
            "name": target_skill,
            "manifest_yaml": detail["manifest_yaml"],
            "prompt_markdown": new_md,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["skill"]["source"] == "override"
    assert saved.json()["skill"]["can_reset"] is True
    # Built-in file untouched!
    assert (skills_copy / "audit" / "auth-rbac" / "SKILL.md").read_text(encoding="utf-8") == original_disk

    # Create brand-new custom skill
    created = client.post(
        "/api/skills/create",
        json={
            "name": "audit/ai-mcp-audit",
            "stage": "deep_audit",
            "description": "Audit MCP servers and AI agent tool execution",
            "prompt_markdown": "# AI MCP Audit\nCheck command injection in tool handlers.\n",
        },
    )
    assert created.status_code == 200
    assert created.json()["skill"]["source"] == "custom"
    assert created.json()["skill"]["can_delete"] is True

    # Fork custom skill
    forked = client.post(
        "/api/skills/fork",
        json={"source_name": "audit/ai-mcp-audit", "new_name": "audit/ai-mcp-audit-v2"},
    )
    assert forked.status_code == 200
    assert forked.json()["skill"]["name"] == "audit/ai-mcp-audit-v2"

    # Reset override -> restores built-in
    reset_res = client.post("/api/skills/reset", json={"name": target_skill})
    assert reset_res.status_code == 200
    assert reset_res.json()["action"] == "reset_to_builtin"
    restored = client.get("/api/skills/detail", params={"name": target_skill}).json()["skill"]
    assert restored["source"] == "builtin"
    assert restored["prompt_markdown"] == original_disk

    # Delete custom skill
    del_res = client.post("/api/skills/reset", json={"name": "audit/ai-mcp-audit-v2"})
    assert del_res.status_code == 200
    assert del_res.json()["action"] == "deleted"


def test_coordinator_chat_sse_and_inline_gate1_card(tmp_path: Path, monkeypatch) -> None:
    # Ensure deterministic router is exercised without hitting any external LLM API
    for var in ("AUDITFLOW_OPENAI_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    client, _, _ = _make_studio_client(tmp_path)

    sess_res = client.post("/api/chat/sessions", json={"title": "AI 漏洞审计测试"})
    assert sess_res.status_code == 200
    sid = sess_res.json()["session"]["session_id"]

    # Send a repo URL -> should invoke scout_projects tool & emit inline Gate 1 card
    sse_res = client.post(
        f"/api/chat/sessions/{sid}/send",
        json={"message": "帮我导入 https://github.com/IceWhaleTech/CasaOS 并准备审计"},
    )
    assert sse_res.status_code == 200
    events = [
        json.loads(line[6:])
        for line in sse_res.text.splitlines()
        if line.startswith("data: ")
    ]
    event_types = [e["type"] for e in events]
    assert "tool_call" in event_types
    assert "tool_result" in event_types
    assert "message" in event_types
    assert "done" in event_types

    msg_ev = next(e for e in events if e["type"] == "message")
    gate_card = msg_ev["message"]["gate_card"]
    assert gate_card is not None
    assert gate_card["kind"] == "gate1"
    assert len(gate_card["items"]) == 1
    assert gate_card["items"][0]["target_id"].startswith("github_icewhaletech_casaos")

    # Messages persisted in SQLite
    hist = client.get(f"/api/chat/sessions/{sid}/messages").json()["messages"]
    assert len(hist) == 2
    assert hist[0]["role"] == "user"
    assert hist[1]["role"] == "assistant"

    # Ask for team recommendation
    rec_sse = client.post(
        f"/api/chat/sessions/{sid}/send",
        json={"message": "按强项帮我推荐一套 Agent 团队分配方案"},
    )
    assert rec_sse.status_code == 200
    assert "recommend_team_assignment" in rec_sse.text

    # Delete session
    assert client.delete(f"/api/chat/sessions/{sid}").status_code == 200


def test_structured_env_config_save(tmp_path: Path) -> None:
    client, _, _ = _make_studio_client(tmp_path)
    cfg = client.get("/api/config").json()
    env_obj = cfg["env"]
    env_obj["docker_verify"]["burp_upstream_proxy"] = "http://127.0.0.1:8080"
    env_obj["backends"]["ssh-ubuntu"] = {
        "host": "192.168.159.10",
        "workspace_root": "/home/wood/audit-pipeline/workspaces",
        "connect_timeout_sec": 15,
    }

    save_res = client.post("/api/config/save", json={"env_structured": env_obj})
    assert save_res.status_code == 200

    reloaded = client.get("/api/config").json()["env"]
    assert reloaded["docker_verify"]["burp_upstream_proxy"] == "http://127.0.0.1:8080"
    assert reloaded["backends"]["ssh-ubuntu"]["host"] == "192.168.159.10"
