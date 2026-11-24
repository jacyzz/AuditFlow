from rich.table import Table
from rich.text import Text

from auditflow.core.schemas import AuditDisposition, Meta
from auditflow.core.state import Tracker


def require_state(current: str, allowed: set[str]) -> None:
    if current not in allowed:
        raise ValueError(f"current state is {current}; required: {', '.join(sorted(allowed))}")


def require_actor(actor: str) -> str:
    actor = actor.strip()
    if not actor or actor.casefold() == "system":
        raise ValueError("a named human reviewer is required")
    return actor


def decide_project(tracker: Tracker, target: str, approve: bool, actor: str) -> None:
    tracker.transition_target(target, "CLONED" if approve else "SKIPPED", actor=require_actor(actor))


def decide_candidate(tracker: Tracker, target: str, candidate: str, approve: bool, actor: str) -> None:
    tracker.transition_candidate(
        target, candidate, "VERIFY_APPROVED" if approve else "REJECTED_FP",
        actor=require_actor(actor),
    )


def projects_table(projects: list[Meta]) -> Table:
    def score(item: Meta) -> int:
        return item.worthiness.score if item.worthiness else -1

    table = Table("Target", "Platform", "Stars", "Deployment", "Score", "Reason")
    for project in sorted(projects, key=score, reverse=True):
        worth = project.worthiness
        table.add_row(
            project.target_id, project.platform,
            str(project.stars) if project.stars is not None else "—",
            ", ".join(project.deploy_modes) or "—",
            str(worth.score) if worth else "—",
            Text(f"{worth.saturation_risk} · {worth.reason}") if worth else "—",
        )
    return table


def candidates_table(disposition: AuditDisposition, tracker: Tracker) -> Table:
    table = Table("Candidate", "Title", "Default deployment", "Duplicate", "Confidence", "Status")
    for candidate in disposition.candidates:
        table.add_row(
            candidate.candidate_id, Text(candidate.title_hint),
            str(candidate.default_deploy_affected), str(candidate.is_duplicate_cve),
            candidate.confidence, tracker.candidate_status(disposition.target_id, candidate.candidate_id),
        )
    return table
