import shutil
import threading
from pathlib import Path

import httpx
from PIL import Image

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]


def test_ui_server_endpoints_and_workflow(tmp_path):
    from auditflow.core.state import Tracker
    from auditflow.ui.server import UIContext, create_server

    pipeline_path = tmp_path / "pipeline.yaml"
    env_path = tmp_path / "env.yaml"
    shutil.copyfile(ROOT / "config" / "pipeline.example.yaml", pipeline_path)
    env_path.write_text(
        f"paths:\n  windows_report_output_dir: '{(tmp_path / 'out').as_posix()}'\n"
        f"  tracker_db_path: '{(tmp_path / 'tracker.sqlite').as_posix()}'\n",
        encoding="utf-8",
    )

    workspaces = tmp_path / "workspaces"
    target = "github_example_policy_demo"
    cand = "CAND-01"
    croot = workspaces / target / "candidates" / cand
    (croot / "evidence").mkdir(parents=True)
    shutil.copytree(FIXTURES / "repo", workspaces / target / "repo")
    for name in ("meta.json", "surface.json", "audit-disposition.json"):
        shutil.copyfile(FIXTURES / name, workspaces / target / name)
    for name in ("audit.json", "deploy-log.json", "verify.json"):
        shutil.copyfile(FIXTURES / name, croot / name)
    Image.new("RGB", (120, 60), "white").save(croot / "evidence" / "code.png")

    tracker = Tracker(tmp_path / "tracker.sqlite")
    tracker.add_target(target)
    tracker.transition_target(target, "GATE1_PENDING")
    tracker.transition_target(target, "CLONED")
    tracker.transition_target(target, "MAPPED")
    tracker.register_audited(target, [cand])
    tracker.open_candidate_gate(target, [cand])

    ctx = UIContext(
        pipeline_path=pipeline_path,
        env_path=env_path,
        workspaces=workspaces,
        skills_dir=ROOT / "skills",
    )
    server = create_server("127.0.0.1", 0, ctx)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(timeout=10) as client:
            home = client.get(f"{base}/")
            assert home.status_code == 200
            assert "AuditFlow 控制台" in home.text

            overview = client.get(f"{base}/api/overview").json()
            assert overview["counts"]["targets"] == 1
            assert overview["counts"]["gate2_pending"] == 1
            assert len(overview["available_skills"]) == 15

            doctor = client.get(f"{base}/api/doctor").json()
            assert doctor["checks"]

            detail = client.get(f"{base}/api/candidate/{target}/{cand}").json()
            assert detail["cnvd_form"]["cwe"] == "CWE-862"
            assert any(img["name"] == "code.png" for img in detail["evidence_images"])

            img_res = client.get(f"{base}/api/evidence/{target}/{cand}/code.png")
            assert img_res.status_code == 200
            assert img_res.headers["content-type"] == "image/png"

            # Import a new repo URL via UI scout API
            scout_res = client.post(
                f"{base}/api/scout",
                json={"urls": "https://github.com/IceWhaleTech/CasaOS\n"},
            )
            assert scout_res.status_code == 200
            assert scout_res.json()["added"] == 1

            # Approve candidate at Gate 2 via UI API
            dec_res = client.post(
                f"{base}/api/decide",
                json={"target": target, "candidate": cand, "approve": True, "actor": "tester"},
            )
            assert dec_res.status_code == 200
            assert tracker.candidate_status(target, cand) == "VERIFY_APPROVED"

            # Discover local agents & skills by stage
            disc = client.get(f"{base}/api/discover-agents").json()
            agent_names = {a["name"] for a in disc["agents"]}
            assert {"codex", "claude-code", "dsh", "openai-api", "native-subagent"} <= agent_names
            assert "scout" in disc["skills_by_stage"]
            assert "deep_audit" in disc["skills_by_stage"]

            # Apply visual pipeline assignment (hot-swap verify to claude-code & custom agent)
            stages = dict(disc["stages"])
            stages["verify"] = {
                "skill": "verify/cli-harness",
                "adapter": "my-local-agent",
                "backend": "local",
                "timeout_sec": 600,
            }
            vis_res = client.post(
                f"{base}/api/config/apply-visual",
                json={
                    "adapters": {"codex": {"binary": "codex"}},
                    "custom_adapters": {
                        "my-local-agent": {
                            "type": "custom-cli",
                            "command_template": "my-agent --out {output_file}",
                        }
                    },
                    "stages": stages,
                },
            )
            assert vis_res.status_code == 200
            assert "my-local-agent" in vis_res.json()["pipeline_yaml"]

            # Save config validation test (rejects invalid YAML)
            bad_cfg = client.post(
                f"{base}/api/config/save",
                json={"pipeline_yaml": "pipeline_name: bad\nstages: {}\n"},
            )
            assert bad_cfg.status_code == 400
    finally:
        server.shutdown()
        server.server_close()
