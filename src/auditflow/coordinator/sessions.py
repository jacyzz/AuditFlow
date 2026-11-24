import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4


class ChatStore:
    """SQLite persistent store for Coordinator chat sessions, messages, tool logs & Gate cards."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    target_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS chat_messages (
                    msg_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    agent_name TEXT,
                    content TEXT NOT NULL,
                    events_json TEXT NOT NULL DEFAULT '[]',
                    gate_card_json TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            with db:
                yield db
        finally:
            db.close()

    def list_sessions(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT s.session_id, s.title, s.target_id, s.created_at, s.updated_at,
                       (SELECT COUNT(*) FROM chat_messages m WHERE m.session_id = s.session_id) AS msg_count
                FROM chat_sessions s
                ORDER BY s.updated_at DESC, s.rowid DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def create_session(self, title: str = "新审计会话", target_id: str | None = None) -> dict[str, Any]:
        sid = f"sess-{uuid4().hex[:10]}"
        with self.connect() as db:
            db.execute(
                "INSERT INTO chat_sessions (session_id, title, target_id) VALUES (?, ?, ?)",
                (sid, title, target_id),
            )
            row = db.execute(
                "SELECT session_id, title, target_id, created_at, updated_at FROM chat_sessions WHERE session_id = ?",
                (sid,),
            ).fetchone()
        return dict(row)

    def delete_session(self, session_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM chat_sessions WHERE session_id = ?", (session_id,))

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT msg_id, session_id, role, agent_name, content, events_json, gate_card_json, created_at
                FROM chat_messages
                WHERE session_id = ?
                ORDER BY msg_id ASC
                """,
                (session_id,),
            ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            item["events"] = json.loads(item.pop("events_json") or "[]")
            gc = item.pop("gate_card_json")
            item["gate_card"] = json.loads(gc) if gc else None
            out.append(item)
        return out

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        agent_name: str | None = None,
        events: list[dict[str, Any]] | None = None,
        gate_card: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.connect() as db:
            cur = db.execute(
                """
                INSERT INTO chat_messages (session_id, role, agent_name, content, events_json, gate_card_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    role,
                    agent_name,
                    content,
                    json.dumps(events or [], ensure_ascii=False),
                    json.dumps(gate_card, ensure_ascii=False) if gate_card else None,
                ),
            )
            db.execute(
                "UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (session_id,),
            )
            msg_id = cur.lastrowid
        return {
            "msg_id": msg_id,
            "session_id": session_id,
            "role": role,
            "agent_name": agent_name,
            "content": content,
            "events": events or [],
            "gate_card": gate_card,
        }

    def update_title_if_default(self, session_id: str, user_text: str) -> None:
        short = user_text.strip().replace("\n", " ")[:28]
        if not short:
            return
        with self.connect() as db:
            db.execute(
                "UPDATE chat_sessions SET title = ? WHERE session_id = ? AND title = '新审计会话'",
                (short, session_id),
            )
