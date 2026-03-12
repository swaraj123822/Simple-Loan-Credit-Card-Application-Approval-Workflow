"""
database.py — SQLite setup with WorkflowState and AuditLog tables.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Optional

DATABASE_PATH = "workflow.db"


def get_connection() -> sqlite3.Connection:
    """Get a new SQLite connection with row factory enabled."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS WorkflowState (
                application_id TEXT PRIMARY KEY,
                status         TEXT NOT NULL DEFAULT 'pending',
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS AuditLog (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id  TEXT NOT NULL,
                action          TEXT NOT NULL,
                rule_triggered  TEXT,
                result          TEXT NOT NULL,
                timestamp       TEXT NOT NULL,
                FOREIGN KEY (application_id) REFERENCES WorkflowState(application_id)
            );
        """)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# WorkflowState helpers
# ---------------------------------------------------------------------------

def get_state(application_id: str) -> Optional[dict]:
    """Return the workflow state for an application, or None if not found."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM WorkflowState WHERE application_id = ?",
            (application_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def upsert_state(application_id: str, status: str) -> dict:
    """Insert or update a workflow state. Returns the resulting row."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT * FROM WorkflowState WHERE application_id = ?",
            (application_id,),
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE WorkflowState SET status = ?, updated_at = ? WHERE application_id = ?",
                (status, now, application_id),
            )
        else:
            conn.execute(
                "INSERT INTO WorkflowState (application_id, status, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (application_id, status, now, now),
            )
        conn.commit()
        return get_state(application_id)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# AuditLog helpers
# ---------------------------------------------------------------------------

def insert_audit_log(
    application_id: str,
    action: str,
    result: str,
    rule_triggered: Optional[str] = None,
) -> None:
    """Write one audit log entry."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO AuditLog (application_id, action, rule_triggered, result, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (application_id, action, rule_triggered, result, now),
        )
        conn.commit()
    finally:
        conn.close()


def get_audit_logs(application_id: str) -> list[dict]:
    """Return all audit log entries for a given application."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM AuditLog WHERE application_id = ? ORDER BY id",
            (application_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
