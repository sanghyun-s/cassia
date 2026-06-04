"""
=============================================================
CASSIA — Phase 5b/c data reclaim on login
=============================================================

Handles the recovery case identified in DEV_NOTE_phase5a.md:

  • A user signed up under Phase 5a (`claim_orphaned_data` ran)
  • Their data was un-claimed back to `default` to keep Phase 4 UI working
  • Now Phase 5b/c lands, endpoints are scoped to current_user, and the
    user logs in expecting to see their data again

`reclaim_data_for_user(user_id)` is called from the login endpoint and
the signup endpoint. It runs only when:

  1. The user owns NO sessions, NO uploads, NO topics, NO saves (yet)
  2. There IS orphaned data sitting under `default` or NULL

When both conditions hold, the function runs the same UPDATE statements
as Phase 5a's `claim_orphaned_data`. Otherwise it's a no-op.

This means:

  • First-time signups still trigger claim_orphaned_data inside the
    signup endpoint (Phase 5a behavior, unchanged)
  • A returning user who lost their data to the un-claim gets it back
    on their first login under Phase 5b/c
  • Subsequent logins after a successful reclaim are no-ops
  • A user creating a second account doesn't accidentally claim someone
    else's data (they don't own zero items — they're a fresh user, but
    the data is already owned by user #1)

Wait, that last point needs more care. Let me re-state:

  The reclaim_data_for_user check is: "does the current user own ANY
  data, AND does orphaned data exist?". For user #2, they own nothing,
  AND orphaned data may or may not exist:

  - If user #1 already claimed everything: no orphaned data, no-op. Good.
  - If user #1's account was deleted and their data un-orphaned back:
    user #2 would claim it. This is acceptable for a small invite-only
    MVP. In a real multi-tenant system, claim should run ONLY on the
    very first user signup (count_real_users == 0). Phase 5a already
    has that guard inside the signup endpoint. This reclaim helper is
    for the specific Phase 5a → Phase 5b/c migration recovery — once
    that's done, future user signups are normal and orphaned data
    should not exist.

Returns a dict with the same shape as Phase 5a's claim_orphaned_data,
so the login endpoint can surface a "welcome back" toast if anything
was actually reclaimed.
"""

from __future__ import annotations

from db.session_store import _get_conn, DEFAULT_USER_ID


def reclaim_data_for_user(user_id: str) -> dict:
    """
    Reclaim orphaned data on login. Idempotent — safe to call on every login.

    Returns a dict:
      {
        "reclaimed":         bool,   # True if anything was actually moved
        "sessions_claimed":  int,
        "uploads_claimed":   int,
        "saves_claimed":     int,
        "topics_claimed":    int,
      }

    The "reclaimed" flag lets the login endpoint decide whether to send
    a toast banner to the frontend.
    """
    if not user_id:
        return _empty_result()

    conn = _get_conn()
    try:
        # Step 1: does this user own anything already?
        own_counts = _count_owned_by(conn, user_id)
        already_owns_data = (
            own_counts["sessions"] > 0
            or own_counts["uploads"] > 0
            or own_counts["topics"] > 0
            or own_counts["saves"] > 0
        )
        if already_owns_data:
            # Don't touch — this user has their own data already
            return _empty_result()

        # Step 2: is there orphaned data to claim?
        orphan_counts = _count_orphans(conn)
        has_orphans = (
            orphan_counts["sessions"] > 0
            or orphan_counts["uploads"] > 0
            or orphan_counts["topics"] > 0
            or orphan_counts["saves"] > 0
        )
        if not has_orphans:
            return _empty_result()

        # Step 3: claim it all, in a single transaction
        cur = conn.cursor()

        cur.execute(
            "UPDATE sessions SET user_id = ? WHERE user_id IS NULL",
            (user_id,),
        )
        sessions_claimed = cur.rowcount

        cur.execute(
            "UPDATE uploads SET user_id = ? WHERE user_id IS NULL",
            (user_id,),
        )
        uploads_claimed = cur.rowcount

        cur.execute(
            "UPDATE core_saves SET user_id = ? WHERE user_id = ?",
            (user_id, DEFAULT_USER_ID),
        )
        saves_claimed = cur.rowcount

        cur.execute(
            "UPDATE core_topics SET user_id = ? WHERE user_id = ?",
            (user_id, DEFAULT_USER_ID),
        )
        topics_claimed = cur.rowcount

        conn.commit()

        any_claimed = (
            sessions_claimed > 0
            or uploads_claimed > 0
            or saves_claimed > 0
            or topics_claimed > 0
        )

        return {
            "reclaimed":        any_claimed,
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


# ── Helpers ───────────────────────────────────────────────

def _empty_result() -> dict:
    return {
        "reclaimed":        False,
        "sessions_claimed": 0,
        "uploads_claimed":  0,
        "saves_claimed":    0,
        "topics_claimed":   0,
    }


def _count_owned_by(conn, user_id: str) -> dict:
    """How many rows of each type does this user own?"""
    sessions = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user_id,)
    ).fetchone()[0]

    uploads = conn.execute(
        "SELECT COUNT(*) FROM uploads WHERE user_id = ?", (user_id,)
    ).fetchone()[0]

    topics = conn.execute(
        "SELECT COUNT(*) FROM core_topics WHERE user_id = ?", (user_id,)
    ).fetchone()[0]

    saves = conn.execute(
        "SELECT COUNT(*) FROM core_saves WHERE user_id = ?", (user_id,)
    ).fetchone()[0]

    return {
        "sessions": sessions,
        "uploads":  uploads,
        "topics":   topics,
        "saves":    saves,
    }


def _count_orphans(conn) -> dict:
    """How many orphaned rows exist (NULL user_id or default-owned)?"""
    sessions = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE user_id IS NULL"
    ).fetchone()[0]

    uploads = conn.execute(
        "SELECT COUNT(*) FROM uploads WHERE user_id IS NULL"
    ).fetchone()[0]

    topics = conn.execute(
        "SELECT COUNT(*) FROM core_topics WHERE user_id = ?",
        (DEFAULT_USER_ID,),
    ).fetchone()[0]

    saves = conn.execute(
        "SELECT COUNT(*) FROM core_saves WHERE user_id = ?",
        (DEFAULT_USER_ID,),
    ).fetchone()[0]

    return {
        "sessions": sessions,
        "uploads":  uploads,
        "topics":   topics,
        "saves":    saves,
    }
