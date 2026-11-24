from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from auditflow.adapters.base import AdapterRequest
from auditflow.adapters.registry import AdapterRegistry
from auditflow.backends import get_backend
from auditflow.core.config import Env, Pipeline, Stage
from auditflow.core.paths import artifact_id, atomic_write, contained_path, workspace_lock
from auditflow.core.schemas import (
    Artifact,
    Audit,
    AuditDisposition,
    DeployLog,
    Meta,
    Verify,
    load_artifact,
    read_contract,
    save_artifact,
)
from auditflow.core.skill_registry import SkillRegistry
from auditflow.core.state import Tracker
from auditflow.dispatcher.gates import (
    decide_candidate,
    decide_project,
    require_actor,
    require_state,
)
from auditflow.environment import build_docker_env, validate_environment_records
from auditflow.reporting.report import generate_report, load_report_inputs, render_saved_evidence

_PROJECT = {
    "scout": (None, "meta.json", ()),
    "triage_project": ("DISCOVERED", "meta.json", ("meta.json",)),
    "surface_map": ("CLONED", "surface.json", ("meta.json",)),
    "deep_audit": ("MAPPED", "audit-disposition.json", ("meta.json", "surface.json")),
    "triage_vuln": ("AUDITED", "audit-disposition.json", ("audit-disposition.json",)),
}
_SKILL_STAGE = {
    "scout": "scout",
    "triage_project": "triage_project",
    "surface_map": "surface_map",
    "deep_audit": "deep_audit",
    "triage_vuln": "triage_vuln",
    "verify": "verify",
    "report": "report",
}


class Dispatcher:
    def __init__(
        self,
        pipeline: Pipeline,
        env: Env,
        tracker: Tracker,
        skills: SkillRegistry,
        workspaces: Path,
        registry: AdapterRegistry | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.env = env
        self.tracker = tracker
        self.skills = skills
        self.workspaces = workspaces.resolve()
        self.registry = registry or AdapterRegistry(pipeline.adapters | pipeline.custom_adapters)

    def workspace(self, target: str) -> Path:
        return contained_path(self.workspaces, artifact_id(target))

    @contextmanager
    def _locked(self, target: str) -> Iterator[Path]:
        directory = self.workspace(target)
        with workspace_lock(directory):
            yield directory

    def _binding(self, stage: str) -> Stage:
        binding = self.pipeline.stages.get(stage)
        if binding is None:
            raise ValueError(f"stage is not configured: {stage}")
        return binding

    def _stage_artifact(
        self,
        stage: str,
        workspace: Path,
        output_name: str,
        inputs: dict[str, Path],
        *,
        supplied: Path | None,
        env_vars: dict[str, str] | None = None,
    ) -> Artifact | None:
        binding = self._binding(stage)
        if supplied is not None:
            return load_artifact(supplied, output_name)
        backend = get_backend(binding.backend, self.env.backends)
        if not binding.adapter:
            raise ValueError(f"stage {stage} requires an adapter")
        adapter = self.registry.get(binding.adapter)
        outputs = []
        for name in binding.skill_names:
            skill = self.skills.get(name)
            if skill.stage != _SKILL_STAGE[stage] or output_name not in skill.outputs:
                raise ValueError(f"{name} does not declare the {stage} output contract")
            scratch = contained_path(workspace, f"logs/{stage}-{uuid4().hex}")
            scratch.mkdir(parents=True)
            request = AdapterRequest(
                stage=stage,
                skill_path=skill.prompt_path,
                workspace_dir=workspace,
                input_files=inputs,
                output_file=scratch / output_name,
                timeout_sec=binding.timeout_sec,
                env_vars=dict(env_vars or {}),
                extra_instructions=(
                    "Follow the skill specification strictly and output valid JSON matching the schema."
                ),
            )
            artifact = self._receive(adapter, backend, request, output_name)
            if artifact is not None:
                outputs.append(artifact)
        if len(outputs) != len(binding.skill_names):
            return None
        if not outputs:
            raise ValueError(f"stage {stage} requires a skill")
        if len(outputs) == 1:
            return outputs[0]
        if stage != "deep_audit":
            raise ValueError(f"multiple output artifacts are unsupported for {stage}")
        return self._merge_dispositions(outputs)

    @staticmethod
    def _receive(adapter, backend, request: AdapterRequest, output_name: str) -> Artifact | None:
        for attempt in range(2):
            result = adapter.run(request, backend)
            log = request.output_file.parent / f"attempt-{attempt + 1}.json"
            atomic_write(log, (result.model_dump_json(indent=2) + "\n").encode())
            if not result.ok:
                if (
                    result.trajectory_path
                    and not result.output_file
                    and "Awaiting" in (result.error_message or "")
                ):
                    return None
                raise ValueError(result.error_message or f"adapter failed: {result.adapter_name}")
            try:
                if result.output_file and result.output_file.resolve() != request.output_file.resolve():
                    raise ValueError("adapter wrote to a different output path")
                output = contained_path(request.output_file.parent, output_name)
                return load_artifact(output, output_name)
            except (ValueError, OSError) as exc:
                if attempt:
                    raise ValueError(f"invalid {output_name} after one schema repair: {exc}") from exc
                request.output_file.unlink(missing_ok=True)
                request = request.model_copy(
                    update={
                        "extra_instructions": f"{request.extra_instructions}\nRepair schema errors: {exc}",
                    }
                )
        raise AssertionError("unreachable")

    @staticmethod
    def _merge_dispositions(outputs: list[Artifact]) -> AuditDisposition:
        first, *rest = outputs
        if not isinstance(first, AuditDisposition):
            raise ValueError("expected a disposition")
        candidates = list(first.candidates)
        for item in rest:
            if not isinstance(item, AuditDisposition) or item.target_id != first.target_id:
                raise ValueError("parallel audit artifacts refer to different targets")
            candidates.extend(item.candidates)
        data = first.model_dump()
        data["candidates"] = [item.model_dump() for item in candidates]
        return AuditDisposition.model_validate(data)

    def clone_target(self, target: str, *, backend_name: str | None = None) -> Path:
        """Shallow-clone the repository recorded in meta.json into workspaces/<target>/repo/."""
        with self._locked(target) as root:
            meta = read_contract(contained_path(root, "meta.json"), Meta)
            repo_dir = contained_path(root, "repo")
            if repo_dir.is_dir():
                return repo_dir
            chosen_backend = backend_name or (
                self.pipeline.stages["scout"].backend if "scout" in self.pipeline.stages else "local"
            )
            backend = get_backend(chosen_backend, self.env.backends)
            env = build_docker_env(self.env.docker_verify)
            result = backend.run_cmd(
                ["git", "clone", "--depth", "1", str(meta.repo_url), str(repo_dir)],
                cwd=root,
                env=env,
                timeout=300,
            )
            if not result.ok:
                detail = (result.stderr or result.stdout or f"exit {result.returncode}").strip()[:400]
                raise ValueError(f"git clone failed for {target}: {detail}")
            updated = meta.model_copy(update={"local_repo_path": str(repo_dir)})
            save_artifact(contained_path(root, "meta.json"), updated)
            return repo_dir

    def run_stage(
        self, stage: str, target: str, candidate: str | None = None, *, supplied: Path | None = None,
    ) -> bool:
        with self._locked(target) as workspace:
            if stage in _PROJECT and candidate is None:
                return self._project(stage, target, workspace, supplied)
            if stage in {"verify", "evidence", "report"} and candidate is not None:
                return self._candidate(stage, target, candidate, workspace, supplied)
            raise ValueError("stage and candidate selection are incompatible")

    def _project(self, stage: str, target: str, root: Path, supplied: Path | None) -> bool:
        previous, output, required = _PROJECT[stage]
        if previous:
            require_state(self.tracker.target_status(target), {previous})
        destination = contained_path(root, output)
        if stage == "scout" and destination.exists():
            raise ValueError("target metadata already exists; run triage_project")
        inputs = {name: contained_path(root, name) for name in required}
        for name, path in inputs.items():
            item = load_artifact(path, name)
            if getattr(item, "target_id", None) != target:
                raise ValueError(f"input refers to a different target: {name}")
        result = self._stage_artifact(stage, root, output, inputs, supplied=supplied)
        if result is None:
            return False
        if getattr(result, "target_id", None) != target:
            raise ValueError("output target does not match the requested target")
        if isinstance(result, AuditDisposition):
            self._accept_disposition(stage, root, result)
            return True
        save_artifact(destination, result)
        if stage == "scout":
            self.tracker.add_target(target)
        elif stage == "triage_project":
            self.tracker.transition_target(target, "GATE1_PENDING")
        elif stage == "surface_map":
            self.tracker.transition_target(target, "MAPPED")
        return True

    def _accept_disposition(self, stage: str, root: Path, disposition: AuditDisposition) -> None:
        target = disposition.target_id
        destination = contained_path(root, "audit-disposition.json")
        if stage == "triage_vuln":
            existing = read_contract(destination, AuditDisposition)
            if {x.candidate_id for x in existing.candidates} != {
                x.candidate_id for x in disposition.candidates
            }:
                raise ValueError("triage must retain the original candidate identifiers")
        for item in disposition.candidates:
            if item.human_decision not in {None, "PENDING"}:
                raise ValueError("human decisions must be recorded through Gate 2")
            if item.status not in {"CANDIDATE_NEW", "GATE2_PENDING"}:
                raise ValueError("candidate disposition cannot advance past Gate 2")
            expected = f"candidates/{item.candidate_id}/audit.json"
            if item.audit_file != expected:
                raise ValueError(f"candidate audit_file must be {expected}")
            audit = read_contract(contained_path(root, expected), Audit)
            if (audit.target_id, audit.candidate_id) != (target, item.candidate_id):
                raise ValueError("candidate audit artifact has mismatched identifiers")
        save_artifact(destination, disposition)
        if stage == "deep_audit":
            self.tracker.register_audited(target, [item.candidate_id for item in disposition.candidates])
        else:
            self.tracker.open_candidate_gate(
                target, [item.candidate_id for item in disposition.candidates]
            )
            self.tracker.complete_if_reviewed(target)

    def _candidate(
        self, stage: str, target: str, candidate: str, root: Path, supplied: Path | None,
    ) -> bool:
        candidate = artifact_id(candidate)
        current = self.tracker.candidate_status(target, candidate)
        if stage == "verify":
            require_state(current, {"VERIFY_APPROVED", "DEPLOYING"})
            return self._intake_verification(target, candidate, root, supplied)
        if stage == "evidence":
            require_state(current, {"VERIFIED"})
            if supplied is not None:
                raise ValueError("evidence uses the saved manifest and local records")
            _, audit, verify, _, candidate_root = load_report_inputs(root, candidate)
            if verify is None:
                raise ValueError("verify.json is required for the evidence stage")
            binding = self._binding(stage)
            render_saved_evidence(
                audit,
                verify,
                contained_path(root, "repo"),
                candidate_root,
                renderers=tuple(binding.renderers),
                docker_settings=self.env.docker_verify,
            )
            self.tracker.transition_candidate(target, candidate, "EVIDENCE_READY")
            return True
        require_state(current, {"EVIDENCE_READY"})
        candidate_root = contained_path(root, f"candidates/{candidate}")
        intake = {
            name: contained_path(base, name)
            for name, base in (
                ("meta.json", root),
                ("audit.json", candidate_root),
                ("verify.json", candidate_root),
            )
        }
        load_report_inputs(root, candidate)
        result = self._stage_artifact(stage, root, "cnvd-form.json", intake, supplied=supplied)
        if result is None:
            return False
        save_artifact(contained_path(candidate_root, "cnvd-form.json"), result)
        return True

    def _intake_verification(
        self, target: str, candidate: str, root: Path, supplied: Path | None,
    ) -> bool:
        self._binding("verify")
        candidate_root = contained_path(root, f"candidates/{candidate}")
        audit_file = contained_path(candidate_root, "audit.json")
        audit = read_contract(audit_file, Audit)
        if (audit.target_id, audit.candidate_id) != (target, candidate):
            raise ValueError("audit identifiers do not match")
        deploy_file = contained_path(candidate_root, "deploy-log.json")
        deploy = read_contract(deploy_file, DeployLog) if deploy_file.is_file() else None
        if deploy and deploy.candidate_id != candidate:
            raise ValueError("deployment log candidate does not match")
        validate_environment_records(self.env.docker_verify, deploy)
        if self.tracker.candidate_status(target, candidate) == "VERIFY_APPROVED":
            self.tracker.transition_candidate(target, candidate, "DEPLOYING")
        if deploy and deploy.final_status != "READY":
            self.tracker.transition_candidate(target, candidate, "NEEDS_HUMAN_ENV")
            return False
        verify_env = build_docker_env(self.env.docker_verify)
        verify_inputs = {"audit.json": audit_file}
        if deploy_file.is_file():
            verify_inputs["deploy-log.json"] = deploy_file
        result = self._stage_artifact(
            "verify",
            root,
            "verify.json",
            verify_inputs,
            supplied=supplied,
            env_vars=verify_env,
        )
        if result is None:
            return False
        if not isinstance(result, Verify) or result.candidate_id != candidate:
            raise ValueError("verification record candidate does not match")
        # Reload deploy-log.json in case the verify adapter produced it during execution
        if deploy is None and deploy_file.is_file():
            deploy = read_contract(deploy_file, DeployLog)
        if result.verdict == "DYNAMIC_CONFIRMED" and deploy is None:
            raise ValueError("a deployment log is required with a dynamic confirmation")
        validate_environment_records(self.env.docker_verify, deploy=deploy, verify=result)
        code_steps = {item.step for item in audit.code_evidence}
        if any(shot.step not in code_steps for shot in result.evidence_manifest.code_shots):
            raise ValueError("verification references an unknown source excerpt")
        save_artifact(contained_path(candidate_root, "verify.json"), result)
        status = "NEEDS_HUMAN_ENV" if result.verdict == "NEEDS_HUMAN_ENV" else "VERIFIED"
        self.tracker.transition_candidate(target, candidate, status)
        return status == "VERIFIED"

    def approve_project(
        self, target: str, *, approve: bool, actor: str, auto_clone: bool = False
    ) -> None:
        if approve and auto_clone:
            self.clone_target(target)
        with self._locked(target) as root:
            require_state(self.tracker.target_status(target), {"GATE1_PENDING"})
            if approve and not contained_path(root, "repo").is_dir():
                raise ValueError(
                    "repository checkout missing in repo/; pass --auto-clone or run `auditflow clone`"
                )
            decide_project(self.tracker, target, approve, actor)

    def approve_candidate(self, target: str, candidate: str, *, approve: bool, actor: str) -> None:
        with self._locked(target):
            decide_candidate(self.tracker, target, candidate, approve, actor)
            self.tracker.complete_if_reviewed(target)

    def resume_environment(self, target: str, candidate: str, *, actor: str) -> None:
        with self._locked(target):
            require_state(self.tracker.candidate_status(target, candidate), {"NEEDS_HUMAN_ENV"})
            self.tracker.transition_candidate(target, candidate, "DEPLOYING", actor=require_actor(actor))

    def report(self, target: str, candidate: str, out: Path) -> tuple[Path, Path, Path]:
        with self._locked(target) as root:
            self._binding("report")
            require_state(self.tracker.candidate_status(target, candidate), {"EVIDENCE_READY"})
            settings = self.env.paths.excel_sync
            result = generate_report(
                root,
                out,
                candidate=candidate,
                excel=Path(settings.excel_path) if settings.enabled else None,
            )
            self.tracker.record_report(target, candidate, result[0])
            self.tracker.complete_if_reviewed(target)
            return result
