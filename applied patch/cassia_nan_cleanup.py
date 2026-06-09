#!/usr/bin/env python3
"""
CASSIA NaN cleanup — sanitizes the records with NaN/Inf in stored JSON.

Replaces NaN/Inf with null (None) in:
  - core_saves.metadata_json / embedding_json / content
  - artifacts.content_json
  - uploads.summary_json

Safety:
  - Creates a timestamped backup of coreckoner.db before any writes
  - Idempotent — re-running on a clean DB does nothing
  - Verifies the result with allow_nan=False after writing
  - Requires explicit 'clean' confirmation before proceeding

Run from app2/ project root:
    python3 cassia_nan_cleanup.py
"""

import sqlite3
import json
import math
import shutil
import sys
from pathlib import Path
from datetime import datetime


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def sanitize(obj):
    """Recursively replace NaN/Inf floats with None."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, list):
        return [sanitize(x) for x in obj]
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    return obj


def has_nan_or_inf(obj):
    """True if obj contains any NaN or Inf at any depth."""
    if isinstance(obj, float):
        return math.isnan(obj) or math.isinf(obj)
    if isinstance(obj, list):
        return any(has_nan_or_inf(x) for x in obj)
    if isinstance(obj, dict):
        return any(has_nan_or_inf(v) for v in obj.values())
    return False


def find_bad_records(cur):
    """Return list of (table, id_col, record_id, json_col) for records containing NaN/Inf."""
    bad = []
    targets = [
        ("core_saves", "save_id",     ["metadata_json", "embedding_json", "content"]),
        ("artifacts",  "artifact_id", ["content_json"]),
        ("uploads",    "upload_id",   ["summary_json"]),
    ]
    for table, id_col, json_cols in targets:
        for col in json_cols:
            try:
                rows = cur.execute(
                    f"SELECT {id_col}, {col} FROM {table} WHERE {col} IS NOT NULL"
                ).fetchall()
            except sqlite3.OperationalError:
                continue  # column doesn't exist in this table; skip
            for rid, val in rows:
                try:
                    parsed = json.loads(val)
                except Exception:
                    continue
                if has_nan_or_inf(parsed):
                    bad.append((table, id_col, rid, col))
    return bad


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  CASSIA — NaN cleanup")
    print("=" * 70)
    print()

    db_path = Path("outputs/coreckoner.db")
    if not db_path.exists():
        print(f"✗ Database not found at {db_path.absolute()}")
        print("  Run this script from the app2/ project root.")
        return 1

    print(f"Database: {db_path.absolute()}")
    print()

    # ── Phase 1: scan ───────────────────────────────────────────
    conn = sqlite3.connect(str(db_path))
    cur  = conn.cursor()

    print("Scanning for records with NaN/Inf values ...")
    bad = find_bad_records(cur)

    if not bad:
        print("  ✓ No bad records found. Database is already clean.")
        conn.close()
        return 0

    print(f"  Found {len(bad)} record(s) requiring cleanup:")
    for table, _id_col, rid, col in bad:
        print(f"    - {table}.{col}  id={rid[:24]}...")
    print()

    # ── Phase 2: confirm ────────────────────────────────────────
    print("This will:")
    print("  1. Back up coreckoner.db with a timestamp suffix")
    print("  2. Replace NaN/Inf with null in the records listed above")
    print("  3. Verify no NaN/Inf remains after cleanup")
    print()
    confirm = input("Type 'clean' to proceed (anything else aborts): ").strip()
    if confirm != "clean":
        print("Aborted — no changes made.")
        conn.close()
        return 1
    print()

    # ── Phase 3: backup ─────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    bak_path  = db_path.with_suffix(
        db_path.suffix + f".pre-nan-cleanup-{timestamp}.bak"
    )
    print(f"Backing up to: {bak_path.name}")
    conn.close()  # release lock before copy
    shutil.copy2(str(db_path), str(bak_path))
    print(f"  ✓ Backup created ({bak_path.stat().st_size:,} bytes)")
    print()

    # ── Phase 4: sanitize and write ─────────────────────────────
    print("Sanitizing records ...")
    conn = sqlite3.connect(str(db_path))
    cur  = conn.cursor()

    for table, id_col, rid, col in bad:
        val = cur.execute(
            f"SELECT {col} FROM {table} WHERE {id_col} = ?", (rid,)
        ).fetchone()[0]
        parsed  = json.loads(val)
        cleaned = sanitize(parsed)
        # strict serialization — fails loudly if anything is still NaN
        cleaned_str = json.dumps(cleaned, allow_nan=False, ensure_ascii=False)
        cur.execute(
            f"UPDATE {table} SET {col} = ? WHERE {id_col} = ?",
            (cleaned_str, rid),
        )
        print(f"  ✓ {table}.{col}  id={rid[:24]}...  cleaned")

    conn.commit()
    print()

    # ── Phase 5: verify ─────────────────────────────────────────
    print("Verifying cleanup ...")
    remaining = find_bad_records(cur)
    conn.close()

    if remaining:
        print(f"  ✗ {len(remaining)} record(s) still contain NaN/Inf:")
        for table, _id_col, rid, col in remaining:
            print(f"    - {table}.{col}  id={rid[:24]}...")
        print()
        print(f"  This shouldn't happen. To restore: cp {bak_path.name} coreckoner.db")
        return 1

    print(f"  ✓ All {len(bad)} record(s) cleaned successfully")
    print()
    print("Done. Next steps:")
    print("  1. Reload your browser tab — My Core should now load cleanly")
    print("  2. The 'Payroll tax exposure' save and its source session should both restore")
    print("  3. Server does not need a restart, but a restart won't hurt")
    print()
    print(f"Backup retained at: {bak_path.name}")
    print("  Safe to delete after verifying everything works in the UI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
