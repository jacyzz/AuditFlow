import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

FIXTURES = Path(__file__).parent / "fixtures"
TARGET = "github_example_policy_demo"
CANDIDATE = "CAND-01"


def _remote(root: Path) -> Path:
    target = root / TARGET
    candidate = target / "candidates" / CANDIDATE
    (candidate / "evidence").mkdir(parents=True)
    for name in ("meta.json", "surface.json", "audit-disposition.json"):
        shutil.copyfile(FIXTURES / name, target / name)
    for name in ("audit.json", "deploy-log.json", "verify.json"):
        shutil.copyfile(FIXTURES / name, candidate / name)
    for name in ("code.png", "http.png", "term.png", "extra.png"):
        Image.new("RGB", (100, 50), "white").save(candidate / "evidence" / name)
    return candidate


def test_sync_copies_contracts_and_evidence_without_touching_source(tmp_path):
    from auditflow.backends.local import LocalBackend
    from auditflow.sync import sync_pull

    remote = tmp_path / "remote"
    candidate = _remote(remote)
    (remote / TARGET / "repo").mkdir()
    (remote / TARGET / "repo" / "private.py").write_text("class Sample: pass")
    out = tmp_path / "control"
    paths = sync_pull(LocalBackend(remote), out, TARGET, CANDIDATE)
    assert len(paths) == 10
    assert not (out / TARGET / "repo").exists()
    dest = out / TARGET / "candidates" / CANDIDATE
    assert (dest / "evidence" / "term.png").read_bytes() == (
        candidate / "evidence" / "term.png"
    ).read_bytes()
    assert (dest / "evidence" / "extra.png").is_file()
    assert sync_pull(LocalBackend(remote), out, TARGET, CANDIDATE) == paths


def test_sync_refuses_inconsistent_artifacts_without_partial_writes(tmp_path):
    from auditflow.backends.local import LocalBackend
    from auditflow.sync import sync_pull

    remote = tmp_path / "remote"
    candidate = _remote(remote)
    path = candidate / "verify.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["candidate_id"] = "CAND-OTHER"
    path.write_text(json.dumps(data), encoding="utf-8")
    out = tmp_path / "control"
    with pytest.raises(ValueError, match="candidate"):
        sync_pull(LocalBackend(remote), out, TARGET, CANDIDATE)
    assert not out.exists()


def test_sync_refuses_replacement_without_explicit_option(tmp_path):
    from auditflow.backends.local import LocalBackend
    from auditflow.sync import sync_pull

    remote = tmp_path / "remote"
    _remote(remote)
    out = tmp_path / "control"
    sync_pull(LocalBackend(remote), out, TARGET, CANDIDATE)
    path = out / TARGET / "meta.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["vendor"] = "Local edit"
    edited = json.dumps(data).encode()
    path.write_bytes(edited)
    with pytest.raises(ValueError, match="local"):
        sync_pull(LocalBackend(remote), out, TARGET, CANDIDATE)
    assert path.read_bytes() == edited


def test_sync_will_not_override_tracked_review_with_replace(tmp_path):
    from auditflow.backends.local import LocalBackend
    from auditflow.core.state import Tracker
    from auditflow.sync import sync_pull

    remote = tmp_path / "remote"
    _remote(remote)
    out = tmp_path / "control"
    sync_pull(LocalBackend(remote), out, TARGET, CANDIDATE)
    tracker = Tracker(tmp_path / "review.sqlite")
    tracker.add_target(TARGET)
    path = out / TARGET / "meta.json"
    edited = path.read_bytes().replace("示例维护团队".encode(), "人工审核内容".encode())
    path.write_bytes(edited)
    with pytest.raises(ValueError, match="tracked"):
        sync_pull(LocalBackend(remote), out, TARGET, CANDIDATE, replace=True, tracker=tracker)
    assert path.read_bytes() == edited


@pytest.mark.parametrize(
    "url",
    ["https://8.8.8.8", "http://169.254.169.254", "http://localhost.example.org",
     "http://user@localhost", "http://127.0.0.1:9090", "http://[::ffff:8.8.8.8]:18000"],
)
def test_recorded_endpoints_must_match_isolated_host_and_port(url):
    from auditflow.core.config import DockerSettings
    from auditflow.environment import validate_isolated_endpoint

    with pytest.raises(ValueError):
        validate_isolated_endpoint(url, DockerSettings())


def test_allowed_isolated_endpoint_accepts_loopback_and_configured_private_address():
    from auditflow.core.config import DockerSettings
    from auditflow.environment import validate_isolated_endpoint

    settings = DockerSettings(
        allowed_target_hosts=["localhost"],
        allowed_target_cidrs=["127.0.0.0/8", "::1/128", "192.168.4.0/24"],
    )
    for url in ["http://localhost:18000", "http://[::1]:19000", "http://192.168.4.8:19999"]:
        assert validate_isolated_endpoint(url, settings) == url
