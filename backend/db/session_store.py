"""
=============================================================
SESSION STORE — coreckoner.db persistence layer
=============================================================

All reads and writes to coreckoner.db go through this module.
No business logic here — pure CRUD only.

Tables:
  sessions    — one row per conversation
  messages    — one row per user or assistant turn
  artifacts   — one row per SQL result, citation set, or chart
  uploads     — one row per user-uploaded file (CSV/Excel/PDF/text)
  users       — one row per user
  core_topics — one row per user-defined topic
  core_saves  — one row per saved message/upload committed to core

Phase history:
  4b-1: uploads gains summary_json
  4d:   embeddings live on core_saves; update_save_embedding helper
  4e:   sessions gains topic_id; update_session_topic helper
  5a:   migrations added user_id columns to sessions and uploads
        (via db/auth_migrations.py, not via this module)
  5b/c: function signatures updated to scope reads/writes by user_id

Phase 5b/c additions in this file:
  - create_session(user_id, title)            — user_id now required
  - get_all_sessions(user_id)                 — filtered by user
  - create_upload(session_id, user_id, ...)   — user_id now required
  - session_belongs_to_user(session_id, ...)  — NEW helper for endpoint checks
  - upload_belongs_to_user(upload_id, ...)    — NEW helper for endpoint checks
  - list_uploads_for_user(user_id)            — NEW (cross-session) for user audit

Functions that DO NOT change signature (caller does the ownership check):
  - get_session(session_id)
  - get_session_with_messages(session_id)
  - update_session_title(session_id, title)
  - update_session_topic(session_id, topic_id)
  - touch_session(session_id)
  - delete_session(session_id)
  - save_message(session_id, role, content, ...)
  - get_session_messages(session_id)
  - save_artifact(message_id, artifact_type, content)
  - get_message_artifacts(message_id)
  - list_uploads(session_id)
  - get_upload(upload_id)
  - delete_upload_record(upload_id)

These functions take only the object id and trust the caller. Endpoints
in main.py and upload_router.py call session_belongs_to_user() or
upload_belongs_to_user() FIRST, then operate.
"""

import sqlite3
import uuid
import json
from utils.json_safe import safe_json_dumps
from pathlib import Path
from datetime import datetime, timezone

# ── Database path ──────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH      = PROJECT_ROOT / "outputs" / "coreckoner.db"

# Tombstone user id — kept for migration purposes. Real users get usr_<uuid>.
DEFAULT_USER_ID = "default"


def _get_conn() -> sqlite3.Connection:
    """Open a connection with row_factory so rows behave like dicts."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


# ── Init ───────────────────────────────────────────────────

def init_db() -> None:
    """
    Create tables if they do not exist, then run idempotent column
    migrations for columns added in later phases.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id  TEXT PRIMARY KEY,
                title       TEXT NOT NULL DEFAULT 'New Chat',
                topic_id    TEXT REFERENCES core_topics(topic_id) ON DELETE SET NULL,
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
                summary_json TEXT,
                uploaded_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id      TEXT PRIMARY KEY,
                email        TEXT UNIQUE,
                display_name TEXT,
                created_at   TEXT NOT NULL,
                is_default   INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS core_topics (
                topic_id    TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                name        TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                UNIQUE(user_id, name)
            );

            CREATE TABLE IF NOT EXISTS core_saves (
                save_id           TEXT PRIMARY KEY,
                user_id           TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                topic_id          TEXT REFERENCES core_topics(topic_id) ON DELETE SET NULL,
                kind              TEXT NOT NULL CHECK(kind IN ('message','upload')),
                source_session_id TEXT,
                source_message_id TEXT,
                source_upload_id  TEXT,
                title             TEXT,
                content           TEXT,
                metadata_json     TEXT,
                note              TEXT,
                embedding_json    TEXT,
                created_at        TEXT NOT NULL,
                archived_at       TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, timestamp);

            CREATE INDEX IF NOT EXISTS idx_artifacts_message
                ON artifacts(message_id);

            CREATE INDEX IF NOT EXISTS idx_uploads_session
                ON uploads(session_id, uploaded_at);

            CREATE INDEX IF NOT EXISTS idx_core_saves_user
                ON core_saves(user_id, archived_at);

            CREATE INDEX IF NOT EXISTS idx_core_saves_topic
                ON core_saves(topic_id);

            CREATE INDEX IF NOT EXISTS idx_core_topics_user
                ON core_topics(user_id);
        """)

        # Idempotent column migrations
        _ensure_column(conn, "uploads",  "summary_json", "TEXT")
        _ensure_column(conn, "sessions", "topic_id",     "TEXT")

        conn.commit()
    finally:
        conn.close()


# ── Session CRUD ───────────────────────────────────────────

def create_session(user_id: str, title: str = "New Chat") -> dict:
    """
    Create a new session row.
    Phase 5b/c: user_id is now required and stored on the row.
    """
    if not user_id:
        raise ValueError("user_id is required to create a session")

    session_id = str(uuid.uuid4())
    now        = _now()
    conn       = _get_conn()
    try:
        conn.execute(
            """INSERT INTO sessions (session_id, user_id, title, created_at, updated_at)
               VALUES (?,?,?,?,?)""",
            (session_id, user_id, title[:80], now, now)
        )
        conn.commit()
        return {
            "session_id": session_id,
            "user_id":    user_id,
            "title":      title,
            "created_at": now,
            "updated_at": now,
        }
    finally:
        conn.close()


def update_session_title(session_id: str, title: str) -> None:
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
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE sessions SET updated_at=? WHERE session_id=?",
            (_now(), session_id)
        )
        conn.commit()
    finally:
        conn.close()


def update_session_topic(session_id: str, topic_id: str | None) -> bool:
    conn = _get_conn()
    try:
        cur = conn.execute(
            "UPDATE sessions SET topic_id=?, updated_at=? WHERE session_id=?",
            (topic_id, _now(), session_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_all_sessions(user_id: str) -> list[dict]:
    """
    Return sessions owned by this user, ordered by most recently updated.
    Phase 5b/c: filtered by user_id (was unfiltered in Phase 4).
    """
    if not user_id:
        return []
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT session_id, title, topic_id, created_at, updated_at
               FROM sessions
               WHERE user_id = ?
               ORDER BY updated_at DESC""",
            (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_session(session_id: str) -> dict | None:
    """
    Return session metadata, or None if not found.
    Does NOT check ownership — callers must call session_belongs_to_user
    first if access control matters.
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def session_belongs_to_user(session_id: str, user_id: str) -> bool:
    """
    Phase 5b/c: cheap ownership check used by every per-session endpoint.

    Returns True only if a row exists matching BOTH the session_id AND
    the user_id. Used to gate /sessions/{id}, /chat (when a session_id
    is provided), /sessions/{id}/topic, /sessions/{id}/uploads, etc.

    Callers should treat False as 404 (NOT 403) — revealing "you don't
    own this session" leaks the fact that the session exists for some
    other user, which we don't want.
    """
    if not session_id or not user_id:
        return False
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM sessions WHERE session_id=? AND user_id=?",
            (session_id, user_id)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def delete_session(session_id: str) -> bool:
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
    artifact_id  = str(uuid.uuid4())
    content_json = safe_json_dumps(content)
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
    Return full session + messages + artifacts per message.
    Does NOT check ownership — caller verifies first.
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
    session_id:   str,
    user_id:      str,
    filename:     str,
    file_type:    str,
    target:       str,
    table_names:  list[str] | None = None,
    chunk_count:  int | None       = None,
    row_count:    int | None       = None,
    summary_json: dict | list | str | None = None,
) -> str:
    """
    Record a user-uploaded file.
    Phase 5b/c: user_id is now required and stored on the row.
    """
    if not user_id:
        raise ValueError("user_id is required to create an upload")

    upload_id = f"upl_{uuid.uuid4().hex[:12]}"

    summary_str = None
    if summary_json is not None:
        summary_str = (summary_json if isinstance(summary_json, str)
                       else safe_json_dumps(summary_json))

    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO uploads
               (upload_id, session_id, user_id, filename, file_type, target,
                table_names, chunk_count, row_count, summary_json, uploaded_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                upload_id, session_id, user_id, filename, file_type, target,
                safe_json_dumps(table_names) if table_names else None,
                chunk_count, row_count, summary_str, _now()
            )
        )
        conn.commit()
        return upload_id
    finally:
        conn.close()


def _row_to_upload(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["table_names"] = json.loads(d["table_names"]) if d.get("table_names") else []
    if d.get("summary_json"):
        try:
            d["summary"] = json.loads(d["summary_json"])
        except Exception:
            d["summary"] = None
    else:
        d["summary"] = None
    return d


def list_uploads(session_id: str) -> list[dict]:
    """
    Return all uploads for a session. Does NOT check ownership —
    caller (the endpoint) verifies session belongs to user first.
    """
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT upload_id, session_id, user_id, filename, file_type, target,
                      table_names, chunk_count, row_count, summary_json, uploaded_at
               FROM uploads WHERE session_id=? ORDER BY uploaded_at DESC""",
            (session_id,)
        ).fetchall()
        return [_row_to_upload(r) for r in rows]
    finally:
        conn.close()


def get_upload(upload_id: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT upload_id, session_id, user_id, filename, file_type, target,
                      table_names, chunk_count, row_count, summary_json, uploaded_at
               FROM uploads WHERE upload_id=?""",
            (upload_id,)
        ).fetchone()
        if not row:
            return None
        return _row_to_upload(row)
    finally:
        conn.close()


def upload_belongs_to_user(upload_id: str, user_id: str) -> bool:
    """
    Phase 5b/c: cheap ownership check used by upload-touching endpoints.
    """
    if not upload_id or not user_id:
        return False
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM uploads WHERE upload_id=? AND user_id=?",
            (upload_id, user_id)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def delete_upload_record(upload_id: str) -> bool:
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM uploads WHERE upload_id=?", (upload_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# =============================================================
# PHASE 4a — Users / Topics / Core Saves
# =============================================================

def ensure_default_user() -> str:
    """
    Create the 'default' tombstone user if it doesn't exist.
    Kept around for migration purposes — real users get usr_<uuid> ids.
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT user_id FROM users WHERE user_id=?", (DEFAULT_USER_ID,)
        ).fetchone()
        if not row:
            conn.execute(
                """INSERT INTO users (user_id, email, display_name, created_at, is_default)
                   VALUES (?,?,?,?,1)""",
                (DEFAULT_USER_ID, None, "Default User", _now())
            )
            conn.commit()
        return DEFAULT_USER_ID
    finally:
        conn.close()


def get_user(user_id: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ── Topics ─────────────────────────────────────────────────

def create_topic(user_id: str, name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("Topic name cannot be empty")

    conn = _get_conn()
    try:
        existing = conn.execute(
            "SELECT topic_id FROM core_topics WHERE user_id=? AND name=?",
            (user_id, name)
        ).fetchone()
        if existing:
            return existing["topic_id"]

        topic_id = f"top_{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO core_topics (topic_id, user_id, name, created_at) VALUES (?,?,?,?)",
            (topic_id, user_id, name, _now())
        )
        conn.commit()
        return topic_id
    finally:
        conn.close()


def list_topics(user_id: str) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT t.topic_id, t.user_id, t.name, t.created_at,
                      COUNT(s.save_id) AS save_count
               FROM core_topics t
               LEFT JOIN core_saves s
                      ON s.topic_id = t.topic_id AND s.archived_at IS NULL
               WHERE t.user_id=?
               GROUP BY t.topic_id
               ORDER BY t.name COLLATE NOCASE ASC""",
            (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def rename_topic(topic_id: str, new_name: str) -> bool:
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("Topic name cannot be empty")
    conn = _get_conn()
    try:
        cur = conn.execute(
            "UPDATE core_topics SET name=? WHERE topic_id=?",
            (new_name, topic_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def topic_belongs_to_user(topic_id: str, user_id: str) -> bool:
    """Phase 5b/c: ownership check used before rename/delete."""
    if not topic_id or not user_id:
        return False
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM core_topics WHERE topic_id=? AND user_id=?",
            (topic_id, user_id)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def delete_topic(topic_id: str) -> bool:
    """
    Delete a topic. Saves keep their data but lose the topic.
    Also clears topic_id from any sessions that referenced it.
    """
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE sessions SET topic_id=NULL WHERE topic_id=?", (topic_id,)
        )
        cur = conn.execute("DELETE FROM core_topics WHERE topic_id=?", (topic_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ── Core saves ─────────────────────────────────────────────

def create_save(
    user_id:           str,
    kind:              str,
    title:             str | None = None,
    content:           str | None = None,
    metadata_json:     dict | list | str | None = None,
    note:              str | None = None,
    topic_id:          str | None = None,
    source_session_id: str | None = None,
    source_message_id: str | None = None,
    source_upload_id:  str | None = None,
) -> str:
    if kind not in ("message", "upload"):
        raise ValueError("kind must be 'message' or 'upload'")

    conn = _get_conn()
    try:
        if kind == "message" and source_message_id:
            existing = conn.execute(
                """SELECT save_id FROM core_saves
                   WHERE user_id=? AND source_message_id=? AND archived_at IS NULL""",
                (user_id, source_message_id)
            ).fetchone()
            if existing:
                return existing["save_id"]
        elif kind == "upload" and source_upload_id:
            existing = conn.execute(
                """SELECT save_id FROM core_saves
                   WHERE user_id=? AND source_upload_id=? AND archived_at IS NULL""",
                (user_id, source_upload_id)
            ).fetchone()
            if existing:
                return existing["save_id"]

        save_id = f"sav_{uuid.uuid4().hex[:12]}"
        meta_str = None
        if metadata_json is not None:
            meta_str = (metadata_json if isinstance(metadata_json, str)
                        else safe_json_dumps(metadata_json))

        conn.execute(
            """INSERT INTO core_saves
               (save_id, user_id, topic_id, kind,
                source_session_id, source_message_id, source_upload_id,
                title, content, metadata_json, note, embedding_json,
                created_at, archived_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                save_id, user_id, topic_id, kind,
                source_session_id, source_message_id, source_upload_id,
                title, content, meta_str, note, None,
                _now(), None
            )
        )
        conn.commit()
        return save_id
    finally:
        conn.close()


def _row_to_save(row: sqlite3.Row) -> dict:
    d = dict(row)
    if d.get("metadata_json"):
        try:
            d["metadata"] = json.loads(d["metadata_json"])
        except Exception:
            d["metadata"] = d["metadata_json"]
    else:
        d["metadata"] = None
    return d


def list_saves(user_id: str, topic_id: str | None = None,
               include_archived: bool = False) -> list[dict]:
    conn = _get_conn()
    try:
        clauses = ["user_id=?"]
        params  = [user_id]

        if topic_id == "__none__":
            clauses.append("topic_id IS NULL")
        elif topic_id is not None:
            clauses.append("topic_id=?")
            params.append(topic_id)

        if not include_archived:
            clauses.append("archived_at IS NULL")

        where = " AND ".join(clauses)
        rows = conn.execute(
            f"""SELECT save_id, user_id, topic_id, kind,
                       source_session_id, source_message_id, source_upload_id,
                       title, content, metadata_json, note,
                       created_at, archived_at
                FROM core_saves
                WHERE {where}
                ORDER BY created_at DESC""",
            tuple(params)
        ).fetchall()
        return [_row_to_save(r) for r in rows]
    finally:
        conn.close()


def get_save(save_id: str) -> dict | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM core_saves WHERE save_id=?", (save_id,)
        ).fetchone()
        return _row_to_save(row) if row else None
    finally:
        conn.close()


def save_belongs_to_user(save_id: str, user_id: str) -> bool:
    """Phase 5b/c: ownership check used before save move/archive."""
    if not save_id or not user_id:
        return False
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM core_saves WHERE save_id=? AND user_id=?",
            (save_id, user_id)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def update_save_topic(save_id: str, topic_id: str | None,
                      note: str | None = None) -> bool:
    conn = _get_conn()
    try:
        if note is not None:
            cur = conn.execute(
                "UPDATE core_saves SET topic_id=?, note=? WHERE save_id=?",
                (topic_id, note, save_id)
            )
        else:
            cur = conn.execute(
                "UPDATE core_saves SET topic_id=? WHERE save_id=?",
                (topic_id, save_id)
            )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def archive_save(save_id: str) -> bool:
    conn = _get_conn()
    try:
        cur = conn.execute(
            "UPDATE core_saves SET archived_at=? WHERE save_id=? AND archived_at IS NULL",
            (_now(), save_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def find_save_by_source(user_id: str, source_message_id: str | None = None,
                        source_upload_id: str | None = None) -> dict | None:
    conn = _get_conn()
    try:
        if source_message_id:
            row = conn.execute(
                """SELECT * FROM core_saves
                   WHERE user_id=? AND source_message_id=? AND archived_at IS NULL""",
                (user_id, source_message_id)
            ).fetchone()
        elif source_upload_id:
            row = conn.execute(
                """SELECT * FROM core_saves
                   WHERE user_id=? AND source_upload_id=? AND archived_at IS NULL""",
                (user_id, source_upload_id)
            ).fetchone()
        else:
            return None
        return _row_to_save(row) if row else None
    finally:
        conn.close()


# ── Phase 4d: embedding I/O ────────────────────────────────

def update_save_embedding(save_id: str, embedding_json: str) -> bool:
    if not embedding_json:
        return False
    conn = _get_conn()
    try:
        cur = conn.execute(
            "UPDATE core_saves SET embedding_json=? WHERE save_id=?",
            (embedding_json, save_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_saves_needing_embedding(user_id: str) -> list[dict]:
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT save_id, title, content
               FROM core_saves
               WHERE user_id=?
                 AND archived_at IS NULL
                 AND (embedding_json IS NULL OR embedding_json='')
               ORDER BY created_at ASC""",
            (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── Counts (for /stats) ────────────────────────────────────

def count_users() -> int:
    conn = _get_conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


def count_topics() -> int:
    conn = _get_conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM core_topics").fetchone()[0]
    finally:
        conn.close()


def count_saves() -> int:
    conn = _get_conn()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM core_saves WHERE archived_at IS NULL"
        ).fetchone()[0]
    finally:
        conn.close()
