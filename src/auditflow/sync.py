from io import BytesIO
from pathlib import Path

from PIL import Image

from auditflow.backends.base import BaseExecutionBackend
from auditflow.core.config import DockerSettings
from auditflow.core.paths import artifact_id, atomic_write, contained_path, workspace_lock
from auditflow.core.schemas import SCHEMAS, Artifact, Audit, AuditDisposition, DeployLog, Verify
from auditflow.core.state import Tracker
from auditflow.environment import validate_environment_records

_MAX_SYNC_BYTES = 128 * 1024 * 1024


def sync_pull(
    backend: BaseExecutionBackend, workspaces: Path, target: str, candidate: str, *,
    replace: bool = False, settings: DockerSettings | None = None, tracker: Tracker | None = None,
) -> list[Path]:
    target, candidate = artifact_id(target), artifact_id(candidate)
    nested = f"candidates/{candidate}"
    data: dict[str, bytes] = {}
    contracts: dict[str, Artifact] = {}
    size = 0

    def collect(relative: str, *, optional: bool = False) -> bytes | None:
        nonlocal size
        try:
            content = backend.read_file(f"{target}/{relative}")
        except FileNotFoundError:
            if optional:
                return None
            raise FileNotFoundError(f"remote artifact missing: {relative}") from None
        size += len(content)
        if size > _MAX_SYNC_BYTES:
            raise ValueError("sync exceeds the total artifact size limit")
        data[relative] = content
        return content

    for base, names in (
        ("", ("meta.json", "surface.json", "audit-disposition.json")),
        (f"{nested}/", ("audit.json", "deploy-log.json", "verify.json", "cnvd-form.json")),
    ):
        for name in names:
            raw = collect(f"{base}{name}", optional=name not in {"meta.json", "audit.json"})
            if raw is None:
                continue
            item = SCHEMAS[name].model_validate_json(raw)
            if getattr(item, "target_id", target) != target:
                raise ValueError(f"remote artifact target mismatch: {name}")
            if getattr(item, "candidate_id", candidate) != candidate:
                raise ValueError(f"remote artifact candidate mismatch: {name}")
            contracts[name] = item

    disposition = contracts.get("audit-disposition.json")
    if isinstance(disposition, AuditDisposition) and not any(
        item.candidate_id == candidate and item.audit_file == f"{nested}/audit.json"
        for item in disposition.candidates
    ):
        raise ValueError("remote audit disposition does not refer to the requested candidate")

    audit = contracts["audit.json"]
    verify = contracts.get("verify.json")
    deploy = contracts.get("deploy-log.json")
    if settings is not None:
        validate_environment_records(
            settings, deploy if isinstance(deploy, DeployLog) else None,
            verify if isinstance(verify, Verify) else None,
        )

    try:
        pngs = {f"evidence/{name}" for name in backend.list_png(f"{target}/{nested}/evidence")}
    except FileNotFoundError:
        pngs = set()
    if isinstance(audit, Audit) and isinstance(verify, Verify):
        manifest = verify.evidence_manifest
        steps = {item.step for item in audit.code_evidence}
        if any(item.step not in steps for item in manifest.code_shots):
            raise ValueError("remote evidence references an unknown source excerpt")
        pngs.update(item.path for item in manifest.code_shots)
        pngs.update(item.path for item in manifest.verify_shots)
        pngs.update(step.screenshot for step in verify.steps if step.screenshot)
        if manifest.app_home:
            pngs.add(manifest.app_home)

    for filename in sorted(pngs):
        relative = f"{nested}/{filename}"
        raw = collect(relative, optional=True)
        if raw is not None:
            with Image.open(BytesIO(raw), formats=["PNG"]) as image:
                image.verify()

    root = contained_path(workspaces, target)
    with workspace_lock(root):
        destinations = {contained_path(root, path): content for path, content in data.items()}
        if len(destinations) != len(data):
            raise ValueError("sync paths resolve to the same local file")
        tracked = tracker is not None and tracker.has_target(target)
        changes = {}
        for path, content in destinations.items():
            original = path.read_bytes() if path.is_file() else None
            if original == content:
                continue
            if original is not None and tracked:
                raise ValueError(f"sync would replace an artifact in a tracked review: {path.name}")
            if original is not None and not replace:
                raise ValueError(f"sync would replace a different local artifact: {path.name}")
            changes[path] = original
        applied = []
        try:
            for path in changes:
                atomic_write(path, destinations[path])
                applied.append(path)
        except OSError:
            for path in reversed(applied):
                if changes[path] is None:
                    path.unlink()
                else:
                    atomic_write(path, changes[path])
            raise
    return list(destinations)
