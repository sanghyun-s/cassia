"""
=============================================================
CASSIA — Phase 5a auth queries
=============================================================

All database operations supporting authentication and Phase 5 data
isolation. Two domains:

  USERS
    create_user(email, password_hash, username=None, invite_code_used=None)
    get_user_by_id(user_id)
    get_user_by_email(email)        — case-insensitive
    get_user_by_username(username)  — case-insensitive
    find_user_by_identifier(ident)  — tries email first, then username
    count_real_users()              — excludes 'default' tombstone
    claim_orphaned_data(user_id)    — first-signup migration

  AUTH SESSIONS (cookie tokens)
    create_auth_session(user_id, token, expires_at)
    get_auth_session_by_token(token)
    touch_auth_session(token, new_expires_at)
    delete_auth_session(token)
    delete_user_auth_sessions(user_id)
    purge_expired_auth_sessions()

Each function opens its own connection via session_store._get_conn(),
matching the existing pattern in session_store.py. No connection is
held across calls — keeps the code straightforward at the cost of
slight connection churn (acceptable for SQLite + low QPS).
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from db.session_store import _get_conn, DEFAULT_USER_ID


def _now() -> str:
    """ISO 8601 UTC timestamp string — matches session_store._now()."""
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# USERS
# ============================================================

def create_user(
    email:            str,
    password_hash:    str,
    username:         Optional[str] = None,
    invite_code_used: Optional[str] = None,
    display_name:     Optional[str] = None,
) -> str:
    """
    Create a real user and return the new user_id.

    Validation is light here — the API layer (auth_router) does the
    full input validation. This function trusts its inputs and only
    enforces structural rules (non-empty email and password_hash).

    Raises sqlite3.IntegrityError on duplicate email or username — the
    caller is expected to catch and translate to 409 Conflict with a
    friendly message.
    """
    if not email or not email.strip():
        raise ValueError("email is required")
    if not password_hash:
        raise ValueError("password_hash is required")

    user_id = f"usr_{uuid.uuid4().hex[:12]}"
    email_clean = email.strip()
    username_clean = username.strip() if username and username.strip() else None
    display = display_name or username_clean or email_clean.split("@")[0]

    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO users
               (user_id, email, username, password_hash, invite_code_used,
                display_name, created_at, is_default, is_admin)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0)""",
            (user_id, email_clean, username_clean, password_hash,
             invite_code_used, display, _now())
        )
        conn.commit()
        return user_id
    finally:
        conn.close()


def get_user_by_id(user_id: str) -> Optional[dict]:
    """Fetch a user row by user_id. Returns dict or None."""
    if not user_id:
        return None
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_email(email: str) -> Optional[dict]:
    """
    Case-insensitive email lookup. Returns the matching user row or None.

    Trims whitespace and lowercases for the comparison. The stored email
    keeps its original casing.
    """
    if not email or not email.strip():
        return None
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE lower(email) = lower(?)",
            (email.strip(),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_username(username: str) -> Optional[dict]:
    """
    Case-insensitive username lookup. Returns the matching user row or None.
    """
    if not username or not username.strip():
        return None
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE lower(username) = lower(?)",
            (username.strip(),)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def find_user_by_identifier(identifier: str) -> Optional[dict]:
    """
    Resolve the login form's single identifier field.

    Tries email-lookup first (the common case), falls back to
    username-lookup. Returns the matching user row or None.

    Edge case: if a username happens to be email-shaped, the email
    lookup will miss (no @ in email column for that string), then
    username lookup succeeds. Correct.
    """
    if not identifier or not identifier.strip():
        return None
    by_email = get_user_by_email(identifier)
    if by_email:
        return by_email
    return get_user_by_username(identifier)


def count_real_users() -> int:
    """
    Count of users excluding the 'default' tombstone. Used by the
    signup endpoint to detect the first real signup (which triggers
    claim_orphaned_data).
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE is_default = 0"
        ).fetchone()
        return int(row["n"]) if row else 0
    finally:
        conn.close()


# ============================================================
# FIRST-SIGNUP DATA CLAIM
# ============================================================

def claim_orphaned_data(new_user_id: str) -> dict:
    """
    First-signup migration. Assigns all pre-Phase-5 data to the first
    real user account created.

    Called from the signup endpoint AFTER user creation, ONLY when
    count_real_users() returned 0 before this signup (i.e. this user
    is the very first non-default account).

    Wraps everything in a transaction so a partial failure rolls back
    cleanly. Reports how many rows were claimed in each table.

    Why this approach (vs wiping data, vs manual seeding):
      • Wiping loses the demo sessions, saves, topics you built in Phase 4.
      • Manual seeding requires pre-creating a user, then renaming, etc.
      • First-signup-claims-all is the cleanest migration story: you sign
        up, your account magically owns everything that came before.

    Returns: {sessions_claimed, uploads_claimed, saves_claimed, topics_claimed}
    """
    if not new_user_id:
        raise ValueError("new_user_id is required")

    conn = _get_conn()
    try:
        # Single transaction so partial failure rolls back.
        cur = conn.cursor()

        # sessions / uploads: claim rows with NULL user_id (the new column)
        cur.execute(
            "UPDATE sessions SET user_id = ? WHERE user_id IS NULL",
            (new_user_id,)
        )
        sessions_claimed = cur.rowcount

        cur.execute(
            "UPDATE uploads  SET user_id = ? WHERE user_id IS NULL",
            (new_user_id,)
        )
        uploads_claimed = cur.rowcount

        # core_saves / core_topics: claim rows that belonged to the
        # 'default' user (these already had a user_id column, just the
        # wrong owner). Only flip if the row really is the default user's.
        cur.execute(
            "UPDATE core_saves  SET user_id = ? WHERE user_id = ?",
            (new_user_id, DEFAULT_USER_ID)
        )
        saves_claimed = cur.rowcount

        cur.execute(
            "UPDATE core_topics SET user_id = ? WHERE user_id = ?",
            (new_user_id, DEFAULT_USER_ID)
        )
        topics_claimed = cur.rowcount

        conn.commit()

        return {
            "sessions_claimed": sessions_claimed,
            "uploads_claimed":  uploads_claimed,
            "saves_claimed":    saves_claimed,
            "topics_claimed":   topics_claimed,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================
# AUTH SESSIONS (cookie tokens)
# ============================================================

def create_auth_session(user_id: str, token: str, expires_at: str) -> None:
    """
    Persist a new auth session row when a user logs in (or signs up).

    The token has already been generated by auth.generate_session_token().
    expires_at is an ISO 8601 UTC string.
    """
    if not user_id or not token or not expires_at:
        raise ValueError("user_id, token, expires_at are all required")

    now = _now()
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO auth_sessions
               (token, user_id, created_at, expires_at, last_seen_at)
               VALUES (?, ?, ?, ?, ?)""",
            (token, user_id, now, expires_at, now)
        )
        conn.commit()
    finally:
        conn.close()


def get_auth_session_by_token(token: str) -> Optional[dict]:
    """
    Look up an auth session by its token, filtering out expired sessions
    at the SQL level. Returns dict with token/user_id/created_at/
    expires_at/last_seen_at, or None if not found / expired.
    """
    if not token:
        return None
    now = _now()
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT token, user_id, created_at, expires_at, last_seen_at
               FROM auth_sessions
               WHERE token = ? AND expires_at > ?""",
            (token, now)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def touch_auth_session(token: str, new_expires_at: str) -> bool:
    """
    Sliding renewal — update last_seen_at to now and extend expires_at.
    Called from get_current_user() when more than TOUCH_DEBOUNCE_MINUTES
    have passed since the last touch (see auth.py).

    Returns True if a row was updated.
    """
    if not token or not new_expires_at:
        return False
    conn = _get_conn()
    try:
        cur = conn.execute(
            """UPDATE auth_sessions
               SET last_seen_at = ?, expires_at = ?
               WHERE token = ?""",
            (_now(), new_expires_at, token)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_auth_session(token: str) -> bool:
    """Delete a single auth session (logout). Returns True if a row was deleted."""
    if not token:
        return False
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_user_auth_sessions(user_id: str) -> int:
    """
    Delete ALL auth sessions for a user (logout-all-devices). Used when
    a user changes their password (Phase 6+) or wants to revoke access.
    Returns the count of rows deleted.
    """
    if not user_id:
        return 0
    conn = _get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM auth_sessions WHERE user_id = ?", (user_id,)
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def purge_expired_auth_sessions() -> int:
    """
    Housekeeping — delete all expired auth sessions. Safe to call any time.
    Could be invoked from a background task or on each login. Returns the
    count of rows deleted.
    """
    now = _now()
    conn = _get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM auth_sessions WHERE expires_at <= ?", (now,)
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
