from collections.abc import Iterable
from pathlib import Path

from auditflow.core.paths import contained_path, workspace_lock
from auditflow.core.schemas import Meta, save_artifact
from auditflow.core.state import Tracker
from auditflow.scout.platforms import import_projects, repository_url


def save_new_projects(
    projects: Iterable[Meta], tracker: Tracker, workspaces: Path, *, history: Path | None = None,
) -> list[Meta]:
    historical = {
        str(item.repo_url).casefold() for item in import_projects(history)
    } if history else set()
    accepted = []
    for item in projects:
        _, canonical, _ = repository_url(str(item.repo_url))
        if canonical.casefold() in historical:
            continue
        workspace = contained_path(workspaces, item.target_id)
        with workspace_lock(workspace):
            if _register_project(item, canonical, tracker, workspace):
                accepted.append(item)
    return accepted


def _register_project(item: Meta, canonical: str, tracker: Tracker, workspace: Path) -> bool:
    meta_path = contained_path(workspace, "meta.json")
    written = False
    try:
        with tracker.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            seen = db.execute(
                "SELECT 1 FROM project_repositories WHERE repo_url = ?", (canonical,),
            ).fetchone()
            existing = db.execute(
                "SELECT 1 FROM targets WHERE target_id = ?", (item.target_id,),
            ).fetchone()
            if seen or existing:
                return False
            if meta_path.exists():
                raise ValueError(f"untracked metadata would be overwritten: {item.target_id}")
            db.execute("INSERT INTO targets VALUES (?, 'DISCOVERED')", (item.target_id,))
            db.execute("INSERT INTO project_repositories VALUES (?, ?)", (canonical, item.target_id))
            save_artifact(meta_path, item)
            written = True
    except Exception:
        if written:
            meta_path.unlink(missing_ok=True)
        raise
    return True
