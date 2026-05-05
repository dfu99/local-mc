"""SQLite-backed chat history.

Schema:
    sessions(id, project, claude_session_id, created_at, last_active_at)
    messages(id, session_id, role, content, attachments_json, artifacts_json,
             created_at)
    attachments(id, message_id, filename, mime, size_bytes, path)

Why SQLite: zero-deps, file-based, holds tens of millions of rows on a laptop,
fits the local-first design. Migrations are inline; the schema is small enough
that we just CREATE TABLE IF NOT EXISTS on every connect.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator

from .config import Paths, get_paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    claude_session_id TEXT,
    created_at REAL NOT NULL,
    last_active_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_project
    ON sessions(project, last_active_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    attachments_json TEXT NOT NULL DEFAULT '[]',
    artifacts_json TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_session
    ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    mime TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    path TEXT NOT NULL,
    FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE
);
"""


@dataclass
class Session:
    id: str
    project: str
    claude_session_id: str | None
    created_at: float
    last_active_at: float


@dataclass
class Message:
    id: int
    session_id: str
    role: str
    content: str
    attachments: list[dict] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "attachments": self.attachments,
            "artifacts": self.artifacts,
            "created_at": self.created_at,
        }


class Store:
    """Thin wrapper around a sqlite3 connection."""

    def __init__(self, db_path: Path | None = None, paths: Paths | None = None):
        if db_path is None:
            resolved = paths or get_paths()
            resolved.ensure()
            db_path = resolved.db_path
        assert db_path is not None
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── sessions ────────────────────────────────────────────────────────

    def create_session(self, project: str) -> Session:
        sid = uuid.uuid4().hex
        now = time.time()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO sessions(id, project, claude_session_id,"
                " created_at, last_active_at) VALUES (?,?,?,?,?)",
                (sid, project, None, now, now),
            )
        return Session(
            id=sid,
            project=project,
            claude_session_id=None,
            created_at=now,
            last_active_at=now,
        )

    def get_session(self, session_id: str) -> Session | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return _row_to_session(row) if row else None

    def latest_session(self, project: str) -> Session | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE project = ?"
                " ORDER BY last_active_at DESC LIMIT 1",
                (project,),
            ).fetchone()
        return _row_to_session(row) if row else None

    def list_sessions(self, project: str | None = None) -> list[Session]:
        with self.connect() as conn:
            if project:
                rows = conn.execute(
                    "SELECT * FROM sessions WHERE project = ?"
                    " ORDER BY last_active_at DESC",
                    (project,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM sessions ORDER BY last_active_at DESC"
                ).fetchall()
        return [_row_to_session(r) for r in rows]

    def update_session(
        self,
        session_id: str,
        *,
        claude_session_id: str | None = None,
        bump_activity: bool = True,
    ) -> None:
        with self.connect() as conn:
            if claude_session_id is not None:
                conn.execute(
                    "UPDATE sessions SET claude_session_id = ?,"
                    " last_active_at = ? WHERE id = ?",
                    (claude_session_id, time.time(), session_id),
                )
            elif bump_activity:
                conn.execute(
                    "UPDATE sessions SET last_active_at = ? WHERE id = ?",
                    (time.time(), session_id),
                )

    def delete_session(self, session_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    # ── messages ────────────────────────────────────────────────────────

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        attachments: list[dict] | None = None,
        artifacts: list[dict] | None = None,
    ) -> Message:
        now = time.time()
        attachments = attachments or []
        artifacts = artifacts or []
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO messages(session_id, role, content,"
                " attachments_json, artifacts_json, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (
                    session_id,
                    role,
                    content,
                    json.dumps(attachments),
                    json.dumps(artifacts),
                    now,
                ),
            )
            mid = cur.lastrowid
            assert mid is not None
            conn.execute(
                "UPDATE sessions SET last_active_at = ? WHERE id = ?",
                (now, session_id),
            )
        return Message(
            id=mid,
            session_id=session_id,
            role=role,
            content=content,
            attachments=attachments,
            artifacts=artifacts,
            created_at=now,
        )

    def append_to_message(self, message_id: int, chunk: str) -> None:
        """Append text to an existing message — used during streaming."""
        with self.connect() as conn:
            conn.execute(
                "UPDATE messages SET content = content || ? WHERE id = ?",
                (chunk, message_id),
            )

    def set_message_content(self, message_id: int, content: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE messages SET content = ? WHERE id = ?",
                (content, message_id),
            )

    def set_message_artifacts(
        self, message_id: int, artifacts: list[dict]
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE messages SET artifacts_json = ? WHERE id = ?",
                (json.dumps(artifacts), message_id),
            )

    def messages(self, session_id: str, limit: int = 500) -> list[Message]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE session_id = ?"
                " ORDER BY id ASC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [_row_to_message(r) for r in rows]


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        id=row["id"],
        project=row["project"],
        claude_session_id=row["claude_session_id"],
        created_at=row["created_at"],
        last_active_at=row["last_active_at"],
    )


def _row_to_message(row: sqlite3.Row) -> Message:
    return Message(
        id=row["id"],
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        attachments=json.loads(row["attachments_json"] or "[]"),
        artifacts=json.loads(row["artifacts_json"] or "[]"),
        created_at=row["created_at"],
    )
