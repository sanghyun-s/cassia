"""
=============================================================
CASSIA — Phase 5a auth router
=============================================================

FastAPI router with four endpoints:

  POST /auth/signup  — create a new user (invite code required)
  POST /auth/login   — exchange credentials for a session cookie
  POST /auth/logout  — delete the current session, clear the cookie
  GET  /auth/me      — return the current user (or 401)

Wiring: add `app.include_router(auth_router)` in main.py.

Locked design decisions:
  • Signup requires SIGNUP_INVITE_CODE from .env — invite-only MVP.
  • Login accepts EITHER email OR username (single 'identifier' field).
  • Lookup is case-insensitive for both email and username.
  • First real signup (when count_real_users() returned 0 before this
    user was created) automatically claims all orphaned demo data.
  • Username is OPTIONAL at signup; email is REQUIRED.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from auth import (
    User,
    clear_session_cookie,
    expiry_from_now,
    generate_session_token,
    get_current_user,
    hash_password,
    set_session_cookie,
    verify_password,
    COOKIE_NAME,
)
from db.auth_queries import (
    claim_orphaned_data,
    count_real_users,
    create_auth_session,
    create_user,
    delete_auth_session,
    find_user_by_identifier,
    get_user_by_email,
    get_user_by_username,
)


router = APIRouter(prefix="/auth", tags=["auth"])


# ── Configuration ─────────────────────────────────────────

_SIGNUP_INVITE_CODE = os.getenv("SIGNUP_INVITE_CODE", "")


# ── Request / response models ─────────────────────────────

# Validation rules:
#   email: standard shape, 5-254 chars
#   username: 3-30 chars, alphanumeric + . _ -  (no whitespace, no @)
#   password: at least 8 chars (no upper limit — bcrypt handles long inputs)
#   invite_code: any non-empty string

_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,30}$")
_EMAIL_RE    = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class SignupRequest(BaseModel):
    email:       str             = Field(..., min_length=5, max_length=254)
    password:    str             = Field(..., min_length=8, max_length=200)
    invite_code: str             = Field(..., min_length=1, max_length=200)
    username:    Optional[str]   = None


class LoginRequest(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=254)
    password:   str = Field(..., min_length=1, max_length=200)


class AuthMeResponse(BaseModel):
    user_id:  str
    email:    str
    username: Optional[str] = None
    is_admin: bool          = False


class SignupResponse(BaseModel):
    status:           str
    user_id:          str
    email:            str
    username:         Optional[str] = None
    claimed_summary:  Optional[dict] = None   # set only on the first signup


class LoginResponse(BaseModel):
    status:   str
    user_id:  str
    email:    str
    username: Optional[str] = None


class LogoutResponse(BaseModel):
    status: str


# ── Helpers ───────────────────────────────────────────────

def _validate_email(value: str) -> str:
    """Trim + lowercase-friendly shape check. Raises 400 on invalid."""
    email = (value or "").strip()
    if not _EMAIL_RE.match(email):
        raise HTTPException(
            status_code = status.HTTP_400_BAD_REQUEST,
            detail      = "Email format is not valid",
        )
    return email


def _validate_username(value: Optional[str]) -> Optional[str]:
    """
    Username is optional. If present, must match the regex.
    Returns the cleaned value or None.
    """
    if value is None:
        return None
    u = value.strip()
    if not u:
        return None
    if not _USERNAME_RE.match(u):
        raise HTTPException(
            status_code = status.HTTP_400_BAD_REQUEST,
            detail      = "Username must be 3–30 characters: letters, digits, dot, underscore, hyphen",
        )
    return u


def _check_invite_code(provided: str) -> None:
    """Compare against env. Raises 403 on mismatch or missing env."""
    if not _SIGNUP_INVITE_CODE:
        # Misconfigured server — refuse to allow signup at all rather than
        # silently letting everyone through.
        raise HTTPException(
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE,
            detail      = "Signup is disabled (server not configured)",
        )
    if not provided or provided.strip() != _SIGNUP_INVITE_CODE:
        raise HTTPException(
            status_code = status.HTTP_403_FORBIDDEN,
            detail      = "Invalid invite code",
        )


def _check_email_available(email: str) -> None:
    """Raises 409 if email already in use."""
    if get_user_by_email(email):
        raise HTTPException(
            status_code = status.HTTP_409_CONFLICT,
            detail      = "Email is already registered",
        )


def _check_username_available(username: Optional[str]) -> None:
    """Raises 409 if username already in use. No-op if username is None."""
    if username is None:
        return
    if get_user_by_username(username):
        raise HTTPException(
            status_code = status.HTTP_409_CONFLICT,
            detail      = "Username is already taken",
        )


# ── Endpoints ─────────────────────────────────────────────

@router.post("/signup", response_model=SignupResponse)
def signup(body: SignupRequest, response: Response):
    """
    Create a new user account. Requires the invite code.

    Flow:
      1. Validate invite code, email shape, username shape (if provided)
      2. Confirm email/username are not already taken
      3. Hash password, create user row
      4. If this is the FIRST real user, claim all orphaned demo data
      5. Create an auth session, set the cookie, return the user
    """
    _check_invite_code(body.invite_code)

    email    = _validate_email(body.email)
    username = _validate_username(body.username)

    _check_email_available(email)
    _check_username_available(username)

    # Detect "first real signup" BEFORE we create the user.
    was_first_signup = (count_real_users() == 0)

    password_hash_value = hash_password(body.password)

    try:
        user_id = create_user(
            email            = email,
            password_hash    = password_hash_value,
            username         = username,
            invite_code_used = body.invite_code.strip(),
        )
    except Exception as e:
        # Most likely an integrity error from a race condition (someone
        # else just took the email/username). Surface a clean conflict.
        msg = str(e).lower()
        if "unique" in msg or "constraint" in msg:
            raise HTTPException(
                status_code = status.HTTP_409_CONFLICT,
                detail      = "Email or username is already taken",
            )
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail      = f"Could not create account: {e}",
        )

    # First-signup data claim
    claimed_summary = None
    if was_first_signup:
        try:
            claimed_summary = claim_orphaned_data(user_id)
        except Exception as e:
            # Non-fatal — log and continue. The user account exists; they
            # just won't auto-inherit the demo data. Can be re-run manually.
            print(f"[auth_router] claim_orphaned_data failed: {e}")

    # Issue a session immediately (don't make the user log in after signup)
    token = generate_session_token()
    create_auth_session(user_id, token, expiry_from_now().isoformat())
    set_session_cookie(response, token)

    return SignupResponse(
        status          = "created",
        user_id         = user_id,
        email           = email,
        username        = username,
        claimed_summary = claimed_summary,
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, response: Response):
    """
    Authenticate with email-OR-username + password.

    Returns the same 401 message for unknown account and wrong password
    (intentional — prevents email enumeration).
    """
    user_row = find_user_by_identifier(body.identifier)
    if not user_row:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Invalid email/username or password",
        )

    if not user_row.get("password_hash"):
        # The 'default' user has no password — refuse without leaking that fact.
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Invalid email/username or password",
        )

    if not verify_password(body.password, user_row["password_hash"]):
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Invalid email/username or password",
        )

    # Successful login — issue a fresh session
    token = generate_session_token()
    create_auth_session(user_row["user_id"], token, expiry_from_now().isoformat())
    set_session_cookie(response, token)

    return LoginResponse(
        status   = "ok",
        user_id  = user_row["user_id"],
        email    = user_row.get("email") or "",
        username = user_row.get("username"),
    )


@router.post("/logout", response_model=LogoutResponse)
def logout(request: Request, response: Response):
    """
    Delete the current session server-side and clear the cookie.

    Idempotent — calling logout when not logged in still succeeds with
    a clean cookie state. No 401 here.
    """
    token = request.cookies.get(COOKIE_NAME)
    if token:
        try:
            delete_auth_session(token)
        except Exception:
            pass  # we still clear the cookie regardless

    clear_session_cookie(response)
    return LogoutResponse(status="logged_out")


@router.get("/me", response_model=AuthMeResponse)
def me(current_user: User = Depends(get_current_user)):
    """
    Return the currently authenticated user. 401 if not logged in.

    This is the frontend's "am I logged in?" probe. On 200, render the
    chat UI. On 401, render the login screen.
    """
    return AuthMeResponse(
        user_id  = current_user.user_id,
        email    = current_user.email,
        username = current_user.username,
        is_admin = current_user.is_admin,
    )
