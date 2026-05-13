"""
=============================================================
SESSION DB — per-session SQLite database manager
=============================================================

Each session owns one SQLite file at outputs/sessions/{session_id}.db.
User CSV/Excel uploads land here as ordinary tables. The SQL pipeline
ATTACH-es this file at query time so user data is queryable alongside
the demo accounting.db.

Public API:
  session_db_path(session_id)   -> Path
  list_session_tables(session_id) -> list[str]
  write_dataframe(session_id, df, suggested_table) -> str   # actual table name used
  drop_tables(session_id, table_names) -> None
  delete_session_db(session_id) -> bool
"""

import sqlite3
from pathlib import Path

import pandas as pd

from uploads.schema_utils import sanitize_identifier


PROJECT_ROOT  = Path(__file__).parent.parent.parent
SESSIONS_DIR  = PROJECT_ROOT / "outputs" / "sessions"


def session_db_path(session_id: str) -> Path:
    """Return the file path for this session's SQLite DB (file may not exist yet)."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    # Sanitize the session_id just to be safe — UUIDs are already filesystem-safe
    # but defense in depth costs nothing.
    safe = sanitize_identifier(session_id.replace("-", "_"), fallback="session")
    return SESSIONS_DIR / f"{safe}.db"


def _connect(session_id: str) -> sqlite3.Connection:
    """Open (or create) the session DB."""
    conn = sqlite3.connect(str(session_db_path(session_id)))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def list_session_tables(session_id: str) -> list[str]:
    """Return all user-table names in this session's DB."""
    path = session_db_path(session_id)
    if not path.exists():
        return []
    conn = _connect(session_id)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def _unique_table_name(existing: set[str], suggested: str) -> str:
    """
    If `suggested` is already used, append _2, _3, ... until we find a free name.
    """
    if suggested not in existing:
        return suggested
    i = 2
    while f"{suggested}_{i}" in existing:
        i += 1
    return f"{suggested}_{i}"


def write_dataframe(
    session_id:      str,
    df:              pd.DataFrame,
    suggested_table: str,
) -> str:
    """
    Write a DataFrame into this session's DB.

    - If `suggested_table` already exists, auto-suffix _2, _3, ...
    - Column names are sanitized to SQLite-safe identifiers, matching what
      the preview returned, so the UI's column list stays accurate.
    - Returns the actual table name written.
    """
    # 1. Resolve the final table name (with collision handling)
    existing = set(list_session_tables(session_id))
    final_name = _unique_table_name(existing, suggested_table)

    # 2. Sanitize column names exactly the way preview does, so what the
    #    user saw in preview matches what they can query.
    rename_map = {col: sanitize_identifier(str(col), fallback="col") for col in df.columns}

    # If two original columns sanitize to the same name (e.g. "Amount" and "amount"),
    # disambiguate with numeric suffixes.
    seen: dict[str, int] = {}
    final_rename: dict[str, str] = {}
    for orig, sane in rename_map.items():
        if sane not in seen:
            seen[sane] = 1
            final_rename[orig] = sane
        else:
            seen[sane] += 1
            final_rename[orig] = f"{sane}_{seen[sane]}"

    df_clean = df.rename(columns=final_rename)

    # 3. Write to SQLite. if_exists='fail' is paranoia — we already resolved
    #    the unique name above — but it guards against races.
    conn = _connect(session_id)
    try:
        df_clean.to_sql(final_name, conn, if_exists="fail", index=False)
        conn.commit()
    finally:
        conn.close()

    return final_name


def drop_tables(session_id: str, table_names: list[str]) -> None:
    """
    Drop the given tables from the session DB.
    Silently ignores tables that don't exist (idempotent delete).
    """
    path = session_db_path(session_id)
    if not path.exists():
        return
    conn = _connect(session_id)
    try:
        for name in table_names:
            # Sanitize again at the boundary — never interpolate raw strings into DDL.
            safe = sanitize_identifier(name, fallback="t")
            try:
                conn.execute(f'DROP TABLE IF EXISTS "{safe}"')
            except sqlite3.Error as e:
                # One bad drop shouldn't block the rest
                print(f"[session_db] drop_tables: failed to drop {safe}: {e}")
        conn.commit()
    finally:
        conn.close()


def delete_session_db(session_id: str) -> bool:
    """
    Delete the entire session DB file.
    Used when a session is removed. Returns True if a file was deleted.
    """
    path = session_db_path(session_id)
    if not path.exists():
        return False
    try:
        path.unlink()
        # Also remove WAL/SHM sidecars if they exist
        for suffix in ("-wal", "-shm"):
            sidecar = path.with_name(path.name + suffix)
            if sidecar.exists():
                sidecar.unlink()
        return True
    except OSError as e:
        print(f"[session_db] delete_session_db failed for {session_id}: {e}")
        return False
