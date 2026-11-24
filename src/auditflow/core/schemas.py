from pathlib import Path
from typing import Annotated, Literal, Self, TypeVar

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    model_validator,
)

from auditflow.core.paths import artifact_id, atomic_write, relative_path

ArtifactId = Annotated[str, AfterValidator(artifact_id)]
RelativePath = Annotated[str, AfterValidator(relative_path)]
Text = Annotated[str, StringConstraints(min_length=1)]
Cwe = Annotated[str, StringConstraints(pattern=r"^CWE-[1-9][0-9]*$")]
Line = Annotated[int, Field(ge=1)]
Score = Annotated[int, Field(ge=0, le=100)]
Platform = Literal["github", "gitee", "gitcode", "other"]
CandidateStatus = Literal[
    "CANDIDATE_NEW", "GATE2_PENDING", "REJECTED_FP", "VERIFY_APPROVED", "DEPLOYING",
    "NEEDS_HUMAN_ENV", "VERIFIED", "EVIDENCE_READY", "REPORTED", "SUBMITTED",
]


def _evidence_path(value: str) -> str:
    if not value.startswith("evidence/") or not value.endswith(".png"):
        raise ValueError("expected a PNG path under evidence/")
    return value


EvidencePath = Annotated[RelativePath, AfterValidator(_evidence_path)]


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, allow_inf_nan=False, hide_input_in_errors=True,
    )


class Artifact(Contract):
    schema_version: Literal["1.0"] = "1.0"


class Worthiness(Contract):
    score: Score
    deployability_score: Score
    cnvd_fit_score: Score
    saturation_risk: Literal["low", "medium", "high", "unknown"]
    reason: Text


class Meta(Artifact):
    target_id: ArtifactId
    platform: Platform
    repo_url: HttpUrl
    homepage: HttpUrl | None = None
    vendor: Text
    product: Text
    description: str = ""
    stars: Annotated[int, Field(ge=0)] | None = None
    license: Text | None = None
    primary_language: Text | None = None
    languages: list[Text] = Field(default_factory=list)
    default_branch: Text | None = None
    commit_sha: Annotated[str, StringConstraints(pattern=r"^(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})$")] | None = None
    latest_tag: Text | None = None
    last_commit_at: AwareDatetime | None = None
    deploy_modes: list[Text] = Field(default_factory=list)
    project_tier: Text | None = None
    scout_profile: Text | None = None
    worthiness: Worthiness | None = None
    local_repo_path: Text | None = None


class RuntimePrivilege(Contract):
    default_user: Text
    evidence_file: RelativePath
    notes: str


class AuthMechanism(Contract):
    name: Text
    file: RelativePath
    lines: Annotated[list[Line], Field(min_length=1)]
    bypass_or_skip_conditions: str = ""

    @model_validator(mode="after")
    def ordered_lines(self) -> Self:
        if self.lines != sorted(set(self.lines)):
            raise ValueError("auth mechanism lines must be ascending and unique")
        return self


class Entrypoint(Contract):
    method: Text
    path: Text
    handler: Text
    file: RelativePath
    line: Line


class StaticHotspot(Contract):
    tool: Text
    rule_id: Text
    file: RelativePath
    line: Line
    summary: Text


class Surface(Artifact):
    target_id: ArtifactId
    frameworks: list[Text]
    runtime_privilege: RuntimePrivilege | None
    auth_mechanisms: list[AuthMechanism]
    role_model: list[Text]
    entrypoints: list[Entrypoint]
    static_hotspots: list[StaticHotspot]


class CandidateDisposition(Contract):
    candidate_id: ArtifactId
    title_hint: Text
    category: Text
    cwe: Cwe
    severity_estimate: Literal["critical", "high", "medium", "low", "informational", "unknown"]
    confidence: Literal["high", "medium", "low"]
    default_deploy_affected: bool | None
    is_duplicate_cve: bool | None
    triage_recommendation: Literal[
        "RECOMMEND_VERIFY", "NEEDS_MANUAL_REVIEW", "LOW_VALUE_SKIP", "DUPLICATE_CVE",
        "FALSE_POSITIVE",
    ]
    triage_reason: Text
    human_decision: Literal["PENDING", "APPROVED", "REJECTED"] | None = None
    status: CandidateStatus = "CANDIDATE_NEW"
    audit_file: RelativePath


class AuditDisposition(Artifact):
    target_id: ArtifactId
    audited_at: AwareDatetime
    audit_adapter: Text
    audit_model: Text | None
    candidates: list[CandidateDisposition]

    @model_validator(mode="after")
    def unique_candidates(self) -> Self:
        ids = [item.candidate_id.casefold() for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate candidate identifier")
        return self


class CodeEvidence(Contract):
    step: Line
    file: RelativePath
    start_line: Line
    end_line: Line
    highlight_lines: list[Line]
    analysis: Text

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("end_line must be at least start_line")
        if any(not self.start_line <= line <= self.end_line for line in self.highlight_lines):
            raise ValueError("highlight lines must be within the code range")
        return self


class VerificationPlan(Contract):
    target_type: Text
    deploy_mode: Text
    preferred_repro_style: list[Text]
    negative_control: Text
    positive_assertion: Text


class Remediation(Contract):
    temporary: list[Text]
    permanent: list[Text]


class Audit(Artifact):
    candidate_id: ArtifactId
    target_id: ArtifactId
    title_hint: Text
    vuln_type: Text
    cwe: Annotated[list[Cwe], Field(min_length=1)]
    severity: Text
    cvss_vector: Text | None = None
    cvss_score: Annotated[float, Field(ge=0, le=10)] | None = None
    affected_versions: Text
    default_deploy_affected: bool | None
    preconditions: list[Text]
    related_cve: Text | None = None
    technical_summary: Text
    impact_summary: Text
    code_evidence: list[CodeEvidence]
    verification_plan: VerificationPlan | None
    remediation: Remediation

    @model_validator(mode="after")
    def unique_steps(self) -> Self:
        steps = [item.step for item in self.code_evidence]
        if len(steps) != len(set(steps)):
            raise ValueError("duplicate code evidence step")
        return self


class DeployAttempt(Contract):
    attempt: Line
    status: Literal["success", "failed", "timeout", "aborted"]
    duration_sec: Annotated[float, Field(ge=0)]
    healthcheck: str | None
    error_summary: str | None


class DeployLog(Artifact):
    candidate_id: ArtifactId
    backend: Text
    deploy_mode: Text
    deploy_commands: list[Text]
    proxy_used: HttpUrl | None = None
    exposed_base_url: HttpUrl | None = None
    precondition_overrides: list[Text]
    attempts: list[DeployAttempt]
    final_status: Literal["READY", "NEEDS_HUMAN_ENV", "ABORTED"]
    teardown_completed: bool


class RealisticAssessment(Contract):
    default_deploy_exploitable: bool | None
    effective_privilege: str | None
    realistic_notes: str


class VerifyStep(Contract):
    step_no: Line
    title: Text
    expected: str = ""
    observed: str = ""
    screenshot: EvidencePath | None = None


class WebStep(VerifyStep):
    kind: Literal["web_browser"]
    url: HttpUrl


class HttpStep(VerifyStep):
    kind: Literal["http_exchange"]
    raw_request: Text
    raw_response: Text
    highlight_response_patterns: list[Text] = Field(default_factory=list)


class TermStep(VerifyStep):
    kind: Literal["terminal_check"]
    command: Text
    stdout: str
    highlight_patterns: list[Text] = Field(default_factory=list)
    exit_code: int | None = None


class ManualStep(VerifyStep):
    kind: Literal["manual"]


class CodeShot(Contract):
    step: Line
    path: EvidencePath


class VerifyShot(Contract):
    step_no: Line
    path: EvidencePath


class EvidenceManifest(Contract):
    app_home: EvidencePath | None = None
    code_shots: list[CodeShot]
    verify_shots: list[VerifyShot]
    manual_placeholders_needed: list[Text]

    @model_validator(mode="after")
    def unique_entries(self) -> Self:
        codes = [item.step for item in self.code_shots]
        verifies = [item.step_no for item in self.verify_shots]
        if len(codes) != len(set(codes)) or len(verifies) != len(set(verifies)):
            raise ValueError("duplicate entry in evidence manifest")
        return self


class Verify(Artifact):
    candidate_id: ArtifactId
    verified_by_adapter: Text
    verified_at: AwareDatetime
    verdict: Literal[
        "DYNAMIC_CONFIRMED", "STATIC_ONLY", "NOT_REPRODUCED", "INCONCLUSIVE", "NEEDS_HUMAN_ENV",
    ]
    realistic_assessment: RealisticAssessment
    steps: list[Annotated[WebStep | HttpStep | TermStep | ManualStep, Field(discriminator="kind")]]
    evidence_manifest: EvidenceManifest
    cleanup_summary: str

    @model_validator(mode="after")
    def check_manifest(self) -> Self:
        steps = {item.step_no: item for item in self.steps}
        if len(steps) != len(self.steps):
            raise ValueError("duplicate verification step")
        for shot in self.evidence_manifest.verify_shots:
            step = steps.get(shot.step_no)
            if step is None:
                raise ValueError("screenshot references an unknown verification step")
            if step.screenshot is not None and step.screenshot != shot.path:
                raise ValueError("conflicting screenshots for verification step")
        manifest = self.evidence_manifest
        step_paths = {item.step_no: item.path for item in manifest.verify_shots}
        step_paths.update({item.step_no: item.screenshot for item in steps.values() if item.screenshot})
        paths = [item.path for item in manifest.code_shots] + list(step_paths.values())
        if manifest.app_home is not None:
            paths.append(manifest.app_home)
        if len(paths) != len({path.casefold() for path in paths}):
            raise ValueError("the same image cannot be assigned to different evidence slots")
        return self


class CnvdForm(Artifact):
    vuln_title: Text
    vendor: Text
    product: Text
    affected_versions: Text
    homepage: HttpUrl | None = None
    repo_url: HttpUrl
    vuln_category: Text
    cwe: Cwe
    severity: Text
    vuln_description: Text
    vuln_impact: Text
    repro_summary: Text
    remediation_suggestion: Text
    reference_links: list[HttpUrl]
    attachment_docx: RelativePath

    @model_validator(mode="after")
    def attachment_name(self) -> Self:
        if "/" in self.attachment_docx or not self.attachment_docx.endswith(".docx"):
            raise ValueError("attachment_docx must be a Word filename")
        return self


SCHEMAS: dict[str, type[Artifact]] = {
    "meta.json": Meta,
    "surface.json": Surface,
    "audit-disposition.json": AuditDisposition,
    "audit.json": Audit,
    "deploy-log.json": DeployLog,
    "verify.json": Verify,
    "cnvd-form.json": CnvdForm,
}


def load_artifact(path: Path, schema_name: str | None = None) -> Artifact:
    name = schema_name or path.name
    if name not in SCHEMAS:
        raise ValueError(f"unknown artifact schema: {name}")
    return SCHEMAS[name].model_validate_json(path.read_bytes())


T = TypeVar("T", bound=Artifact)


def read_contract(path: Path, model: type[T]) -> T:
    return model.model_validate_json(path.read_bytes())


def export_schemas() -> dict[str, dict]:
    return {name: model.model_json_schema() for name, model in SCHEMAS.items()}


def save_artifact(path: Path, artifact: Artifact) -> None:
    atomic_write(path, (artifact.model_dump_json(indent=2) + "\n").encode("utf-8"))
