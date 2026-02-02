"""
Database layer for Panel session monitoring.
Uses SQLite to store session information across all monitored apps.
"""

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Default database path - can be overridden via environment variable
DB_PATH = Path(__file__).parent / "sessions.db"

# Thread-local storage for connections
_local = threading.local()


def get_connection() -> sqlite3.Connection:
    """Get a thread-local database connection."""
    if not hasattr(_local, "connection") or _local.connection is None:
        _local.connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.connection.row_factory = sqlite3.Row
    return _local.connection


@contextmanager
def get_cursor():
    """Context manager for database cursor with auto-commit."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


def init_db():
    """Initialize the database schema."""
    with get_cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                app_name TEXT NOT NULL,
                user_id TEXT,
                start_time TEXT NOT NULL,
                last_heartbeat TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'idle',
                current_task TEXT,
                kill_requested INTEGER NOT NULL DEFAULT 0
            )
        """)
        # Add kill_requested column if it doesn't exist (for existing databases)
        cursor.execute("PRAGMA table_info(sessions)")
        columns = [row[1] for row in cursor.fetchall()]
        if "kill_requested" not in columns:
            cursor.execute("ALTER TABLE sessions ADD COLUMN kill_requested INTEGER NOT NULL DEFAULT 0")
        # Index for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_app_name
            ON sessions(app_name)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_last_heartbeat
            ON sessions(last_heartbeat)
        """)


def register_session(
    session_id: str,
    app_name: str,
    user_id: Optional[str] = None
) -> None:
    """Register a new session or update existing one."""
    now = datetime.utcnow().isoformat()
    with get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO sessions (session_id, app_name, user_id, start_time, last_heartbeat, status)
            VALUES (?, ?, ?, ?, ?, 'idle')
            ON CONFLICT(session_id) DO UPDATE SET
                last_heartbeat = excluded.last_heartbeat,
                app_name = excluded.app_name,
                user_id = excluded.user_id
        """, (session_id, app_name, user_id, now, now))


def update_heartbeat(session_id: str) -> None:
    """Update the last heartbeat time for a session."""
    now = datetime.utcnow().isoformat()
    with get_cursor() as cursor:
        cursor.execute("""
            UPDATE sessions SET last_heartbeat = ? WHERE session_id = ?
        """, (now, session_id))


def set_status(
    session_id: str,
    status: str,
    current_task: Optional[str] = None
) -> None:
    """Update session status and optionally the current task."""
    now = datetime.utcnow().isoformat()
    with get_cursor() as cursor:
        cursor.execute("""
            UPDATE sessions
            SET status = ?, current_task = ?, last_heartbeat = ?
            WHERE session_id = ?
        """, (status, current_task, now, session_id))


def remove_session(session_id: str) -> None:
    """Remove a session from the database."""
    with get_cursor() as cursor:
        cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


def request_kill(session_id: str) -> None:
    """Request a session to be killed. The session will terminate on next heartbeat."""
    with get_cursor() as cursor:
        cursor.execute(
            "UPDATE sessions SET kill_requested = 1 WHERE session_id = ?",
            (session_id,)
        )


def check_kill_requested(session_id: str) -> bool:
    """Check if a kill has been requested for this session."""
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT kill_requested FROM sessions WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        return row is not None and row[0] == 1


def get_all_sessions() -> list[dict]:
    """Get all sessions with computed duration and staleness."""
    now = datetime.utcnow()
    stale_threshold = now - timedelta(minutes=2)

    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM sessions ORDER BY start_time DESC")
        rows = cursor.fetchall()

    sessions = []
    for row in rows:
        start_time = datetime.fromisoformat(row["start_time"])
        last_heartbeat = datetime.fromisoformat(row["last_heartbeat"])
        duration = now - start_time
        is_stale = last_heartbeat < stale_threshold

        sessions.append({
            "session_id": row["session_id"],
            "app_name": row["app_name"],
            "user_id": row["user_id"],
            "start_time": start_time,
            "last_heartbeat": last_heartbeat,
            "duration": duration,
            "status": "stale" if is_stale else row["status"],
            "current_task": row["current_task"],
            "is_stale": is_stale,
            "kill_requested": bool(row["kill_requested"]) if "kill_requested" in row.keys() else False,
        })

    return sessions


def cleanup_stale_sessions(older_than_minutes: int = 10) -> int:
    """Remove sessions that haven't sent a heartbeat in the given time.

    Returns the number of sessions removed.
    """
    threshold = (datetime.utcnow() - timedelta(minutes=older_than_minutes)).isoformat()
    with get_cursor() as cursor:
        cursor.execute(
            "DELETE FROM sessions WHERE last_heartbeat < ?",
            (threshold,)
        )
        return cursor.rowcount


# Initialize database on module import
init_db()
