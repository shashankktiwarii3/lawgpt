"""SQLite persistence for chat_memory_app.py.

Stores per-session conversation turns in a single local .db file.
No external service or API key required.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "chat_memory.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the messages and user_settings tables if they don't already exist."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id TEXT PRIMARY KEY,
                memory_enabled INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def add_message(session_id: str, role: str, content: str) -> None:
    """Append a single turn (user or assistant) to a session's history."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def get_history(session_id: str, limit: Optional[int] = None) -> list[dict]:
    """Return a session's turns in chronological order.

    If `limit` is given, only the most recent `limit` turns are returned
    (still in chronological order).
    """
    with get_connection() as conn:
        if limit is not None:
            rows = conn.execute(
                """
                SELECT role, content, created_at FROM (
                    SELECT role, content, created_at, id
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                ) ORDER BY id ASC
                """,
                (session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()

    return [dict(row) for row in rows]


def clear_history(session_id: str) -> int:
    """Delete all turns for a session. Returns the number of rows deleted."""
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.commit()
        return cursor.rowcount


def set_memory_enabled(user_id: str, enabled: bool) -> None:
    """Set (or update) whether conversation history should be used for a user."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_settings (user_id, memory_enabled, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                memory_enabled = excluded.memory_enabled,
                updated_at = excluded.updated_at
            """,
            (user_id, 1 if enabled else 0, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def is_memory_enabled(user_id: str) -> bool:
    """Whether history should be used for a user. Defaults to True (ON) if unset."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT memory_enabled FROM user_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    if row is None:
        return True

    return bool(row["memory_enabled"])
