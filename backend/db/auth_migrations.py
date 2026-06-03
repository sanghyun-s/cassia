"""
=============================================================
CASSIA — Phase 5a migrations
=============================================================

Idempotent schema changes for Phase 5 authentication. Called once on
FastAPI startup, after init_db(), from main.py's lifespan hook.

What this adds:

  users (existing — gains four columns):
    password_hash       TEXT
    username            TEXT
    invite_code_used    TEXT
    is_admin            INTEGER DEFAULT 0

  sessions (existing — gains one column):
    user_id             TEXT REFERENCES users(user_id)

  uploads (existing — gains one column):
    user_id             TEXT REFERENCES users(user_id)

  auth_sessions (NEW table):
    token               TEXT PRIMARY KEY
    user_id             TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE
    created_at          TEXT NOT NULL
    expires_at          TEXT NOT NULL
    last_seen_at        TEXT NOT NULL

  Indexes:
    idx_users_email_lower_unique    — case-insensitive email uniqueness
    idx_users_username_lower_unique — case-insensitive username uniqueness (partial, WHERE username IS NOT NULL)
    idx_sessions_user_id            — fast per-user session listing
    idx_uploads_user_id             — fast per-user upload listing
    idx_auth_sessions_user_id       — fast logout-all queries
    idx_auth_sessions_expires_at    — fast expired-session cleanup

SQLite limitations worth noting:
  • ALTER TABLE ... ADD COLUMN cannot add a working REFERENCES constraint
    on a pre-existing table. The user_id columns added to sessions/uploads
    on already-existing databases won't enforce the FK. We compensate by
    explicitly clearing/validating user_id at the query layer.
  • Cannot add UNIQUE constraints via ALTER. We use UNIQUE INDEX instead.
  • Partial indexes (WHERE clause) work — username uniqueness only applies
    when username IS NOT NULL.
"""

from __future__ import annotations

import sqlite3

from db.session_store import _column_exists, _ensure_column, _get_conn


def migrate() -> None:
    """
    Run all Phase 5 schema migrations. Idempotent — safe to call on
    every server startup. Re-running is a no-op if everything is in place.
    """
    conn = _get_conn()
    try:
        # ── Idempotent column additions to existing tables ─────────────
        _ensure_column(conn, "users", "password_hash",    "TEXT")
        _ensure_column(conn, "users", "username",         "TEXT")
        _ensure_column(conn, "users", "invite_code_used", "TEXT")
        _ensure_column(conn, "users", "is_admin",         "INTEGER NOT NULL DEFAULT 0")

        _ensure_column(conn, "sessions", "user_id", "TEXT REFERENCES users(user_id)")
        _ensure_column(conn, "uploads",  "user_id", "TEXT REFERENCES users(user_id)")

        # ── New table for cookie-session tokens ────────────────────────
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token         TEXT PRIMARY KEY,
                user_id       TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                created_at    TEXT NOT NULL,
                expires_at    TEXT NOT NULL,
                last_seen_at  TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id
                ON auth_sessions(user_id);

            CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at
                ON auth_sessions(expires_at);
        """)

        # ── Case-insensitive uniqueness via UNIQUE INDEX ───────────────
        # Email: existing UNIQUE constraint is case-sensitive at the
        # column level. Add a unique index on lower(email) so 'sam@x.com'
        # and 'Sam@x.com' cannot both exist. Partial — skip NULL emails
        # (the 'default' user has NULL email).
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower_unique
            ON users(lower(email))
            WHERE email IS NOT NULL
        """)

        # Username: also case-insensitive, also partial (username is
        # optional — many users may have NULL username).
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower_unique
            ON users(lower(username))
            WHERE username IS NOT NULL
        """)

        # ── Supporting indexes for Pass 2 user-scoped queries ──────────
        # These already help even before Pass 2 lands; harmless if unused.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_uploads_user_id  ON uploads(user_id)")

        conn.commit()
    finally:
        conn.close()


def status_report() -> dict:
    """
    Diagnostic helper. Returns which migrations are currently in place.
    Called from /auth/_status (mounted as a dev convenience) or from
    a one-off ad-hoc check. Safe to call any time.
    """
    conn = _get_conn()
    try:
        rep = {
            "users_password_hash":     _column_exists(conn, "users",    "password_hash"),
            "users_username":          _column_exists(conn, "users",    "username"),
            "users_invite_code_used":  _column_exists(conn, "users",    "invite_code_used"),
            "users_is_admin":          _column_exists(conn, "users",    "is_admin"),
            "sessions_user_id":        _column_exists(conn, "sessions", "user_id"),
            "uploads_user_id":         _column_exists(conn, "uploads",  "user_id"),
            "auth_sessions_table":     _table_exists(conn, "auth_sessions"),
        }
        return rep
    finally:
        conn.close()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,)
    ).fetchone()
    return row is not None
