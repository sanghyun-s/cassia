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
  users       — one row per user (Phase 4a; single 'default' user for now)
  core_topics — one row per user-defined topic (Phase 4a)
  core_saves  — one row per saved message/upload committed to core (Phase 4a)

Phase 4b-1:
  - uploads gains a summary_json column (columns + sample rows for tabular,
    preview text for PDFs) captured at ingest time so core-saves can be rich.
  - An idempotent ALTER guard adds the column to pre-existing databases.

Phase 4d:
  - update_save_embedding(save_id, embedding_json) writes the cached vector.
  - list_saves_needing_embedding(user_id) finds saves with no embedding yet
    (used by the one-time backfill script).
  - The embedding_json column itself was provisioned back in 4a, so no
    schema change here.

Usage:
  from db.session_store import (
      init_db, create_session, get_all_sessions,
      get_session, save_message, save_artifact,
      delete_session,
      create_upload, list_uploads, get_upload, delete_upload_record,
      ensure_default_user, get_user,
      create_topic, list_topics, rename_topic, delete_topic,
      create_save, list_saves, get_save, update_save_topic, archive_save,
      count_users, count_topics, count_saves,
      update_save_embedding, list_saves_needing_embedding,   # 4d
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

# The hard-coded single user for Phase 4 (real auth arrives in 4f).
DEFAULT_USER_ID = "default"


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


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True if `column` exists on `table`."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """
    Idempotently add a column to an existing table.
    CREATE TABLE IF NOT EXISTS does NOT add columns to a table that already
    exists, so for new columns on pre-existing databases we ALTER here.
    """
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


# ── Init ───────────────────────────────────────────────────

def init_db() -> None:
    """
    Create tables if they do not exist, then run idempotent column
    migrations for any new columns added in later phases.
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
                summary_json TEXT,
                uploaded_at  TEXT NOT NULL
            );

            -- ── Phase 4a: users / core_topics / core_saves ──────────

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
                embedding_json    TEXT,     -- cached embedding for 4d recall
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

        # ── Idempotent column migrations (for pre-existing databases) ──
        # The uploads table may already exist from before 4b-1 without
        # summary_json. CREATE TABLE IF NOT EXISTS won't add it — ALTER does.
        _ensure_column(conn, "uploads", "summary_json", "TEXT")

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
      core_sources    — Phase 4d: list of {title, date, kind, score} saves used
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
    session_id:   str,
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
    """
    upload_id = f"upl_{uuid.uuid4().hex[:12]}"

    summary_str = None
    if summary_json is not None:
        summary_str = (summary_json if isinstance(summary_json, str)
                       else json.dumps(summary_json, ensure_ascii=False))

    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO uploads
               (upload_id, session_id, filename, file_type, target,
                table_names, chunk_count, row_count, summary_json, uploaded_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                upload_id, session_id, filename, file_type, target,
                json.dumps(table_names) if table_names else None,
                chunk_count, row_count, summary_str, _now()
            )
        )
        conn.commit()
        return upload_id
    finally:
        conn.close()


def _row_to_upload(row: sqlite3.Row) -> dict:
    """Convert an uploads row to a dict, parsing JSON fields."""
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
    """Return all uploads for a session, newest first."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT upload_id, session_id, filename, file_type, target,
                      table_names, chunk_count, row_count, summary_json, uploaded_at
               FROM uploads WHERE session_id=? ORDER BY uploaded_at DESC""",
            (session_id,)
        ).fetchall()
        return [_row_to_upload(r) for r in rows]
    finally:
        conn.close()


def get_upload(upload_id: str) -> dict | None:
    """Fetch a single upload record, or None if not found."""
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT upload_id, session_id, filename, file_type, target,
                      table_names, chunk_count, row_count, summary_json, uploaded_at
               FROM uploads WHERE upload_id=?""",
            (upload_id,)
        ).fetchone()
        if not row:
            return None
        return _row_to_upload(row)
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


# =============================================================
# PHASE 4a — Users / Topics / Core Saves
# =============================================================

# ── Users ──────────────────────────────────────────────────

def ensure_default_user() -> str:
    """
    Create the hard-coded single user if it doesn't exist.
    Idempotent — safe to call on every startup.
    Returns DEFAULT_USER_ID.
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
    """Return user row, or None if not found."""
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
    """
    Create a topic for a user. Topic names are unique per user.
    If the topic already exists, returns the existing topic_id.
    """
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
    """
    Return all topics for a user, with a save_count per topic.
    Ordered alphabetically by name.
    """
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
    """Rename a topic. Returns True if a row was updated."""
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


def delete_topic(topic_id: str) -> bool:
    """
    Delete a topic. Saves keep their data but lose the topic
    (topic_id set to NULL via ON DELETE SET NULL).
    Returns True if a row was deleted.
    """
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM core_topics WHERE topic_id=?", (topic_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ── Core saves ─────────────────────────────────────────────

def create_save(
    user_id:           str,
    kind:              str,                 # 'message' | 'upload'
    title:             str | None = None,
    content:           str | None = None,
    metadata_json:     dict | list | str | None = None,
    note:              str | None = None,
    topic_id:          str | None = None,
    source_session_id: str | None = None,
    source_message_id: str | None = None,
    source_upload_id:  str | None = None,
) -> str:
    """
    Commit a message or upload to the user's core.

    Idempotency: if a save already exists for the same source
    (message_id or upload_id) and user, returns the existing save_id
    instead of creating a duplicate.

    Returns the save_id.
    """
    if kind not in ("message", "upload"):
        raise ValueError("kind must be 'message' or 'upload'")

    conn = _get_conn()
    try:
        # Idempotency check
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
                        else json.dumps(metadata_json, ensure_ascii=False))

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
    """Convert a core_saves row to a dict, parsing JSON fields."""
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
    """
    Return saves for a user, newest first.
    Optionally filter by topic_id. Archived saves excluded by default.
    Pass topic_id='__none__' to get only untopiced saves.
    """
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
    """Return a single save (including embedding_json), or None."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM core_saves WHERE save_id=?", (save_id,)
        ).fetchone()
        return _row_to_save(row) if row else None
    finally:
        conn.close()


def update_save_topic(save_id: str, topic_id: str | None,
                      note: str | None = None) -> bool:
    """
    Move a save to a topic (or to no topic if topic_id is None),
    and optionally update its note. Returns True if updated.
    """
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
    """Soft-delete a save (sets archived_at). Returns True if updated."""
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
    """
    Look up an active save by its source. Used by the frontend to render
    the 'already saved' (filled) state on the 💾 button.
    """
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
    """
    Cache the vector for a save. Called by main.py at save time (embed-on-save)
    and by the one-time backfill script for pre-4d saves.
    embedding_json is expected to be a JSON-serialized list of floats.
    """
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
    """
    Return active saves for a user that don't yet have an embedding.
    Used by scripts/backfill_save_embeddings.py.
    """
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
