"""
=============================================================
CASSIA — Authentication module (Phase 5a, Pass 1)
=============================================================

Self-contained auth primitives:
  • password hashing (bcrypt via passlib)
  • session token generation (32-byte URL-safe random)
  • get_current_user() FastAPI dependency — reads HttpOnly cookie,
    validates the session token against auth_sessions, returns User
  • get_current_user_optional() — same but returns None on no/invalid cookie
  • set_session_cookie() / clear_session_cookie() — response helpers

Design decisions (locked in Phase 5 planning):
  • Server-side session cookies, NOT JWT
  • bcrypt password hashing
  • HttpOnly + SameSite=Lax cookie
  • Secure=False for localhost dev; toggle via env in any future prod
  • 30-day expiration with sliding renewal on each authenticated request
  • Cookie name: 'cassia_session'

Auth tables (created by db/auth_migrations.py):
  users (existing, gains: password_hash, username, invite_code_used, is_admin)
  auth_sessions (new): token, user_id, created_at, expires_at, last_seen_at

This module does NOT touch the database directly — it delegates to
db/auth_queries.py for all CRUD. That keeps the auth flow easy to test
and the SQL contained in one place.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request, Response, HTTPException, status
from passlib.context import CryptContext
from pydantic import BaseModel

from db.auth_queries import (
    get_user_by_id,
    get_auth_session_by_token,
    touch_auth_session,
)

# ── Configuration (from .env) ──────────────────────────────

COOKIE_NAME           = "cassia_session"
COOKIE_PATH           = "/"
COOKIE_SAMESITE       = "lax"
COOKIE_SECURE_DEFAULT = False   # set via env in prod

# Sliding renewal window — every authenticated request bumps last_seen_at
# but we only extend expires_at if more than this many minutes have passed
# since the last touch. Keeps writes manageable.
TOUCH_DEBOUNCE_MINUTES = 5

_SESSION_LIFETIME_DAYS = int(os.getenv("SESSION_LIFETIME_DAYS", "30"))
_COOKIE_SECURE         = os.getenv("COOKIE_SECURE", "false").lower() == "true"

# ── Password hashing ───────────────────────────────────────

# passlib's bcrypt scheme is well-tested. Default rounds (12) takes ~250ms
# on modern hardware — appropriate for human-typed passwords.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Hash a plaintext password. Returns the bcrypt hash string."""
    if not plain:
        raise ValueError("Password cannot be empty")
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time verify of a plaintext password against a stored hash."""
    if not plain or not hashed:
        return False
    try:
        return _pwd_context.verify(plain, hashed)
    except Exception:
        # Malformed hash, mismatched scheme, etc. — never raise on bad input
        return False


# ── Session tokens ─────────────────────────────────────────

def generate_session_token() -> str:
    """
    Generate a cryptographically random URL-safe session token.

    32 bytes → 43-char base64 string. Stored in auth_sessions.token and
    in the user's cookie. The cookie value is the entire authentication
    credential — no other claim is trusted from the client.
    """
    return secrets.token_urlsafe(32)


def session_lifetime_delta() -> timedelta:
    return timedelta(days=_SESSION_LIFETIME_DAYS)


def expiry_from_now() -> datetime:
    return datetime.now(timezone.utc) + session_lifetime_delta()


# ── User model returned by the dependency ─────────────────

class User(BaseModel):
    """
    Minimal user identity passed to endpoint handlers via Depends.

    Intentionally excludes password_hash and invite_code_used — those are
    audit/security fields and don't belong in request-handler scope.
    """
    user_id:  str
    email:    str
    username: Optional[str] = None
    is_admin: bool          = False


def _user_row_to_model(row: dict) -> User:
    """Translate a users-table row dict to the User model."""
    return User(
        user_id  = row["user_id"],
        email    = row.get("email") or "",
        username = row.get("username"),
        is_admin = bool(row.get("is_admin")),
    )


# ── FastAPI dependencies ──────────────────────────────────

async def get_current_user(request: Request) -> User:
    """
    Required-auth dependency. Reads the session cookie, validates the
    token against auth_sessions, applies sliding renewal, and returns
    the User. Raises 401 on any failure mode.

    Failure modes:
      • No cookie present                 → 401
      • Cookie present but unknown token  → 401
      • Token found but expired           → 401 (session deleted server-side)
      • Token's user_id not found in DB   → 401 (orphaned session)

    Sliding renewal: if the session's last_seen_at is more than
    TOUCH_DEBOUNCE_MINUTES ago, we update last_seen_at and extend
    expires_at. Otherwise we leave the row alone to save writes.
    """
    user = await _resolve_current_user(request)
    if user is None:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Authentication required",
        )
    return user


async def get_current_user_optional(request: Request) -> Optional[User]:
    """
    Optional-auth dependency. Same logic as get_current_user but returns
    None instead of raising. Useful for endpoints that work both
    authenticated and unauthenticated (e.g. /health).
    """
    return await _resolve_current_user(request)


async def _resolve_current_user(request: Request) -> Optional[User]:
    """Shared implementation. Returns User or None — never raises."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None

    sess = get_auth_session_by_token(token)
    if not sess:
        return None

    # Server-side expiry check (defensive — the DB query also filters)
    expires_at = _parse_iso(sess.get("expires_at"))
    if expires_at and expires_at < datetime.now(timezone.utc):
        return None

    user_row = get_user_by_id(sess["user_id"])
    if not user_row:
        return None

    # Sliding renewal — debounced to avoid hammering the DB
    last_seen = _parse_iso(sess.get("last_seen_at"))
    now       = datetime.now(timezone.utc)
    if (last_seen is None
            or (now - last_seen) > timedelta(minutes=TOUCH_DEBOUNCE_MINUTES)):
        new_expiry = expiry_from_now()
        try:
            touch_auth_session(token, new_expiry.isoformat())
        except Exception:
            # Non-fatal — auth still succeeds even if the touch write fails
            pass

    return _user_row_to_model(user_row)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 string; return None on failure."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


# ── Cookie helpers (called by auth_router endpoints) ──────

def set_session_cookie(response: Response, token: str) -> None:
    """
    Write the session token to an HttpOnly cookie on the response.

    Settings (locked in Phase 5 plan):
      HttpOnly    — JS cannot read the cookie (XSS defense)
      SameSite=Lax — sent on same-origin and top-level GETs (CSRF defense)
      Secure       — set via COOKIE_SECURE env (False for localhost)
      Path=/       — sent on every endpoint
      max-age      — 30 days by default (SESSION_LIFETIME_DAYS env)
    """
    response.set_cookie(
        key      = COOKIE_NAME,
        value    = token,
        max_age  = int(session_lifetime_delta().total_seconds()),
        path     = COOKIE_PATH,
        httponly = True,
        secure   = _COOKIE_SECURE,
        samesite = COOKIE_SAMESITE,
    )


def clear_session_cookie(response: Response) -> None:
    """Delete the session cookie by setting an expired value."""
    response.delete_cookie(
        key      = COOKIE_NAME,
        path     = COOKIE_PATH,
        httponly = True,
        secure   = _COOKIE_SECURE,
        samesite = COOKIE_SAMESITE,
    )
