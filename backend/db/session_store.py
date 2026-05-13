"""
=============================================================
SESSION STORE — coreckoner.db persistence layer
=============================================================

All reads and writes to coreckoner.db go through this module.
No business logic here — pure CRUD only.

Tables:
  sessions   — one row per conversation
  messages   — one row per user or assistant turn
  artifacts  — one row per SQL result, citation set, or chart
  uploads    — one row per user-uploaded file (CSV/Excel/PDF/text)

Usage:
  from backend.db.session_store import (
      init_db, create_session, get_all_sessions,
      get_session, save_message, save_artifact,
      delete_session,
      create_upload, list_uploads, get_upload, delete_upload_record
  )
"""

import sqlite3
import uuid
import json
from pathlib import Path
from datetime import datetime, timezone

# ── Database path ──────────────────────────────────────────
# Separate from accounting.db — never mix persistence and demo data
PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH      = PROJECT_ROOT / "outputs" / "coreckoner.db"


def _get_conn() -> sqlite3.Connection:
    """Open a connection with row_factory so rows behave like dicts."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safe concurrent writes
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _now() -> str:
    """ISO 8601 UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


# ── Init ───────────────────────────────────────────────────

def init_db() -> None:
    """
    Create tables if they do not exist.
    Called once on FastAPI startup — safe to call repeatedly.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id  TEXT PRIMARY KEY,
                title       TEXT NOT NULL DEFAULT 'New Chat',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                message_id    TEXT PRIMARY KEY,
                session_id    TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                role          TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content       TEXT NOT NULL,
                pipeline_used TEXT,
                timestamp     TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_id   TEXT PRIMARY KEY,
                message_id    TEXT NOT NULL REFERENCES messages(message_id) ON DELETE CASCADE,
                artifact_type TEXT NOT NULL,
                content_json  TEXT NOT NULL,
                created_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS uploads (
                upload_id    TEXT PRIMARY KEY,
                session_id   TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                filename     TEXT NOT NULL,
                file_type    TEXT NOT NULL,
                target       TEXT NOT NULL,
                table_names  TEXT,
                chunk_count  INTEGER,
                row_count    INTEGER,
                uploaded_at  TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, timestamp);

            CREATE INDEX IF NOT EXISTS idx_artifacts_message
                ON artifacts(message_id);

            CREATE INDEX IF NOT EXISTS idx_uploads_session
                ON uploads(session_id, uploaded_at);
        """)
        conn.commit()
    finally:
        conn.close()


# ── Session CRUD ───────────────────────────────────────────

def create_session(title: str = "New Chat") -> dict:
    """
    Create a new session row.
    Returns the full session dict.
    """
    session_id = str(uuid.uuid4())
    now        = _now()
    conn       = _get_conn()
    try:
        conn.execute(
            "INSERT INTO sessions (session_id, title, created_at, updated_at) VALUES (?,?,?,?)",
            (session_id, title[:80], now, now)
        )
        conn.commit()
        return {"session_id": session_id, "title": title, "created_at": now, "updated_at": now}
    finally:
        conn.close()


def update_session_title(session_id: str, title: str) -> None:
    """Set the session title from the first user message."""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE sessions SET title=?, updated_at=? WHERE session_id=?",
            (title[:80], _now(), session_id)
        )
        conn.commit()
    finally:
        conn.close()


def touch_session(session_id: str) -> None:
    """Update updated_at so sidebar sorts by most recent activity."""
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE sessions SET updated_at=? WHERE session_id=?",
            (_now(), session_id)
        )
        conn.commit()
    finally:
        conn.close()


def get_all_sessions() -> list[dict]:
    """
    Return all sessions ordered by most recently updated.
    Used for the sidebar list.
    """
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT session_id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_session(session_id: str) -> dict | None:
    """Return session metadata, or None if not found."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_session(session_id: str) -> bool:
    """
    Delete session and all child messages and artifacts (CASCADE).
    Returns True if a row was deleted.
    """
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ── Message CRUD ───────────────────────────────────────────

def save_message(
    session_id:    str,
    role:          str,
    content:       str,
    pipeline_used: str | None = None,
) -> str:
    """
    Persist a single message turn.
    Returns the new message_id.
    """
    message_id = str(uuid.uuid4())
    conn       = _get_conn()
    try:
        conn.execute(
            """INSERT INTO messages
               (message_id, session_id, role, content, pipeline_used, timestamp)
               VALUES (?,?,?,?,?,?)""",
            (message_id, session_id, role, content, pipeline_used, _now())
        )
        conn.commit()
        return message_id
    finally:
        conn.close()


def get_session_messages(session_id: str) -> list[dict]:
    """Return all messages for a session in chronological order."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT message_id, role, content, pipeline_used, timestamp
               FROM messages WHERE session_id=? ORDER BY timestamp ASC""",
            (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Artifact CRUD ──────────────────────────────────────────

def save_artifact(
    message_id:    str,
    artifact_type: str,
    content:       dict | list | str,
) -> str:
    """
    Persist one artifact attached to an assistant message.

    artifact_type values:
      sql_query       — the generated SQL string
      sql_result      — {"columns": [...], "rows": [...]}
      citations       — list of {page, preview} dicts
      route_explanation — plain string from query router
    """
    artifact_id  = str(uuid.uuid4())
    content_json = json.dumps(content, ensure_ascii=False)
    conn         = _get_conn()
    try:
        conn.execute(
            """INSERT INTO artifacts
               (artifact_id, message_id, artifact_type, content_json, created_at)
               VALUES (?,?,?,?,?)""",
            (artifact_id, message_id, artifact_type, content_json, _now())
        )
        conn.commit()
        return artifact_id
    finally:
        conn.close()


def get_message_artifacts(message_id: str) -> list[dict]:
    """Return all artifacts for a single message."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT artifact_id, artifact_type, content_json, created_at
               FROM artifacts WHERE message_id=? ORDER BY created_at ASC""",
            (message_id,)
        ).fetchall()
        result = []
        for r in rows:
            row = dict(r)
            try:
                row["content"] = json.loads(row["content_json"])
            except Exception:
                row["content"] = row["content_json"]
            result.append(row)
        return result
    finally:
        conn.close()


def get_session_with_messages(session_id: str) -> dict | None:
    """
    Return full session: metadata + messages + artifacts per message.
    Used by GET /sessions/{session_id} for full thread restore.
    """
    session = get_session(session_id)
    if not session:
        return None

    messages = get_session_messages(session_id)
    for msg in messages:
        msg["artifacts"] = get_message_artifacts(msg["message_id"])

    session["messages"] = messages
    return session


# ── Upload CRUD ────────────────────────────────────────────

def create_upload(
    session_id:  str,
    filename:    str,
    file_type:   str,
    target:      str,
    table_names: list[str] | None = None,
    chunk_count: int | None       = None,
    row_count:   int | None       = None,
) -> str:
    """
    Record a user-uploaded file.

    Args:
      session_id  — owning session
      filename    — original uploaded name (e.g. 'sales_2026.csv')
      file_type   — 'csv' | 'xlsx' | 'pdf' | 'txt'
      target      — 'sql' (tabular → session DB) or 'rag' (document → ChromaDB)
      table_names — list of table names created in the session DB (sql target)
      chunk_count — number of vector chunks created in ChromaDB (rag target)
      row_count   — total rows ingested across all tables (sql target)

    Returns the new upload_id.
    """
    upload_id = f"upl_{uuid.uuid4().hex[:12]}"
    conn      = _get_conn()
    try:
        conn.execute(
            """INSERT INTO uploads
               (upload_id, session_id, filename, file_type, target,
                table_names, chunk_count, row_count, uploaded_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                upload_id, session_id, filename, file_type, target,
                json.dumps(table_names) if table_names else None,
                chunk_count, row_count, _now()
            )
        )
        conn.commit()
        return upload_id
    finally:
        conn.close()


def list_uploads(session_id: str) -> list[dict]:
    """Return all uploads for a session, newest first."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT upload_id, session_id, filename, file_type, target,
                      table_names, chunk_count, row_count, uploaded_at
               FROM uploads WHERE session_id=? ORDER BY uploaded_at DESC""",
            (session_id,)
        ).fetchall()
        result = []
        for r in rows:
            row = dict(r)
            row["table_names"] = json.loads(row["table_names"]) if row["table_names"] else []
            result.append(row)
        return result
    finally:
        conn.close()


def get_upload(upload_id: str) -> dict | None:
    """Fetch a single upload record, or None if not found."""
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT upload_id, session_id, filename, file_type, target,
                      table_names, chunk_count, row_count, uploaded_at
               FROM uploads WHERE upload_id=?""",
            (upload_id,)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["table_names"] = json.loads(result["table_names"]) if result["table_names"] else []
        return result
    finally:
        conn.close()


def delete_upload_record(upload_id: str) -> bool:
    """
    Remove the uploads row only.
    Caller is responsible for dropping tables in the session DB
    or removing vectors from ChromaDB before calling this.
    Returns True if a row was deleted.
    """
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM uploads WHERE upload_id=?", (upload_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
