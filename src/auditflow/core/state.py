import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Literal

from auditflow.core.paths import artifact_id

TARGET_TRANSITIONS = {
    "DISCOVERED": {"GATE1_PENDING"},
    "GATE1_PENDING": {"SKIPPED", "CLONED"},
    "CLONED": {"MAPPED"},
    "MAPPED": {"AUDITED"},
    "AUDITED": {"COMPLETED"},
}
CANDIDATE_TRANSITIONS = {
    "CANDIDATE_NEW": {"GATE2_PENDING"},
    "GATE2_PENDING": {"REJECTED_FP", "VERIFY_APPROVED"},
    "VERIFY_APPROVED": {"DEPLOYING"},
    "DEPLOYING": {"NEEDS_HUMAN_ENV", "VERIFIED"},
    "NEEDS_HUMAN_ENV": {"DEPLOYING"},
    "VERIFIED": {"EVIDENCE_READY"},
    "EVIDENCE_READY": {"REPORTED"},
    "REPORTED": {"SUBMITTED"},
}


class Tracker:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS targets (
                    target_id TEXT PRIMARY KEY COLLATE NOCASE,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS candidates (
                    target_id TEXT NOT NULL COLLATE NOCASE REFERENCES targets(target_id),
                    candidate_id TEXT NOT NULL COLLATE NOCASE,
                    status TEXT NOT NULL,
                    PRIMARY KEY (target_id, candidate_id)
                );
                CREATE TABLE IF NOT EXISTS state_events (
                    event_id INTEGER PRIMARY KEY,
                    target_id TEXT NOT NULL,
                    candidate_id TEXT,
                    previous_status TEXT NOT NULL,
                    next_status TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS reports (
                    target_id TEXT NOT NULL REFERENCES targets(target_id),
                    candidate_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    PRIMARY KEY (target_id, candidate_id),
                    FOREIGN KEY (target_id, candidate_id)
                      REFERENCES candidates(target_id, candidate_id)
                );
                CREATE TABLE IF NOT EXISTS project_repositories (
                    repo_url TEXT PRIMARY KEY COLLATE NOCASE,
                    target_id TEXT NOT NULL REFERENCES targets(target_id)
                );
            """)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute("PRAGMA foreign_keys = ON")
            with db:
                yield db
        finally:
            db.close()

    def add_target(self, target: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO targets VALUES (?, 'DISCOVERED') ON CONFLICT DO NOTHING",
                (artifact_id(target),),
            )

    def add_candidate(self, target: str, candidate: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO candidates VALUES (?, ?, 'CANDIDATE_NEW') ON CONFLICT DO NOTHING",
                (artifact_id(target), artifact_id(candidate)),
            )

    def target_status(self, target: str) -> str:
        return self._status("targets", (target,))

    def has_target(self, target: str) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT 1 FROM targets WHERE target_id = ?", (target,)).fetchone()
        return row is not None

    def candidate_status(self, target: str, candidate: str) -> str:
        return self._status("candidates", (target, candidate))

    def transition_target(self, target: str, status: str, *, actor: str = "system") -> None:
        self._transition("targets", (target,), status, TARGET_TRANSITIONS, actor)

    def transition_candidate(
        self, target: str, candidate: str, status: str, *, actor: str = "system"
    ) -> None:
        self._transition("candidates", (target, candidate), status, CANDIDATE_TRANSITIONS, actor)

    def register_audited(self, target: str, candidates: list[str]) -> None:
        with self.connect() as db:
            self._change(db, "targets", (target,), "MAPPED", "AUDITED", "system")
            db.executemany(
                "INSERT INTO candidates VALUES (?, ?, 'CANDIDATE_NEW')",
                [(target, artifact_id(candidate)) for candidate in candidates],
            )

    def open_candidate_gate(self, target: str, candidates: list[str]) -> None:
        with self.connect() as db:
            for candidate in candidates:
                self._change(
                    db, "candidates", (target, candidate), "CANDIDATE_NEW", "GATE2_PENDING",
                    "system",
                )

    def record_report(self, target: str, candidate: str, path: Path) -> None:
        with self.connect() as db:
            self._change(db, "candidates", (target, candidate), "EVIDENCE_READY", "REPORTED", "system")
            db.execute("INSERT INTO reports VALUES (?, ?, ?)", (target, candidate, str(path)))

    def complete_if_reviewed(self, target: str) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT status FROM targets WHERE target_id = ?", (target,)
            ).fetchone()
            if current != ("AUDITED",):
                return
            unfinished = db.execute(
                """SELECT 1 FROM candidates WHERE target_id = ?
                   AND status NOT IN ('REJECTED_FP', 'REPORTED', 'SUBMITTED') LIMIT 1""",
                (target,),
            ).fetchone()
            if unfinished is None:
                self._change(db, "targets", (target,), "AUDITED", "COMPLETED", "system")

    def _status(self, table: Literal["targets", "candidates"], ids: tuple[str, ...]) -> str:
        where = "target_id = ?" if len(ids) == 1 else "target_id = ? AND candidate_id = ?"
        with self.connect() as db:
            row = db.execute(f"SELECT status FROM {table} WHERE {where}", ids).fetchone()
        if row is None:
            raise ValueError(f"unknown {table[:-1]}: {' / '.join(ids)}")
        return row[0]

    def _transition(
        self,
        table: Literal["targets", "candidates"],
        ids: tuple[str, ...],
        status: str,
        transitions: dict[str, set[str]],
        actor: str,
    ) -> None:
        previous = self._status(table, ids)
        if status not in transitions.get(previous, set()):
            raise ValueError(f"invalid transition: {previous} -> {status}")
        with self.connect() as db:
            self._change(db, table, ids, previous, status, actor)

    @staticmethod
    def _change(
        db: sqlite3.Connection, table: Literal["targets", "candidates"], ids: tuple[str, ...],
        previous: str, status: str, actor: str,
    ) -> None:
        where = "target_id = ?" if len(ids) == 1 else "target_id = ? AND candidate_id = ?"
        changed = db.execute(
            f"UPDATE {table} SET status = ? WHERE {where} AND status = ?",
            (status, *ids, previous),
        )
        if changed.rowcount != 1:
            raise ValueError(f"state no longer matches {previous}; reload before retrying")
        db.execute(
            """INSERT INTO state_events
               (target_id, candidate_id, previous_status, next_status, actor)
               VALUES (?, ?, ?, ?, ?)""",
            (ids[0], ids[1] if len(ids) == 2 else None, previous, status, actor),
        )
