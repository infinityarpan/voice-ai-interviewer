import os
import sqlite3
from threading import Lock
from typing import Protocol

from app.core.config import get_settings
from app.schemas.interview import InterviewSessionState


class InterviewStore(Protocol):
    def save(self, state: InterviewSessionState) -> None:
        ...

    def get(self, session_id: str) -> InterviewSessionState:
        ...


class InMemoryInterviewStore:
    def __init__(self) -> None:
        self._sessions: dict[str, InterviewSessionState] = {}

    def save(self, state: InterviewSessionState) -> None:
        self._sessions[state.session_id] = state

    def get(self, session_id: str) -> InterviewSessionState:
        return self._sessions[session_id]


class SQLiteInterviewStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = Lock()
        parent = os.path.dirname(os.path.abspath(db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS interview_sessions (
                session_id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._connection.commit()

    def save(self, state: InterviewSessionState) -> None:
        payload = state.model_dump_json()
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO interview_sessions (session_id, state_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (state.session_id, payload),
            )
            self._connection.commit()

    def get(self, session_id: str) -> InterviewSessionState:
        with self._lock:
            row = self._connection.execute(
                "SELECT state_json FROM interview_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            raise KeyError(session_id)
        return InterviewSessionState.model_validate_json(row[0])


def create_interview_store() -> InterviewStore:
    settings = get_settings()
    if settings.interview_store == "sqlite":
        return SQLiteInterviewStore(settings.interview_db_path)
    return InMemoryInterviewStore()
