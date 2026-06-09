#!/usr/bin/env python3
"""
ARCHIVE ALL CORE SAVES  —  clean slate before the Demo Sims.

Sets archived_at on every currently-active save in outputs/coreckoner.db so
that Sim 4's Core Recall can only match the fresh saves created by Sims 1-3,
instead of the ~46 junk/old/prior-sim saves currently polluting recall.

Safety:
  • Writes a timestamped .bak of coreckoner.db before any change.
  • REVERSIBLE — only sets archived_at; restore the .bak (or un-archive) to undo.
  • Idempotent — re-running archives only newly-active saves; no-ops if none.
  • Asks for explicit confirmation before writing.

IMPORTANT: run with the server STOPPED (you already closed it), from the
app2 project root:

    python3 archive_core_saves.py
"""
import os
import sys
import shutil
import sqlite3
from datetime import datetime, timezone


def find_db():
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (
        "outputs/coreckoner.db",
        "coreckoner.db",
        os.path.join(here, "outputs", "coreckoner.db"),
    ):
        if os.path.isfile(p):
            return p
    return None


def main():
    path = find_db()
    if not path:
        print("ERROR: outputs/coreckoner.db not found. Run from the app2 root.")
        return 1

    con = sqlite3.connect(path)
    try:
        total = con.execute("SELECT COUNT(*) FROM core_saves").fetchone()[0]
        active = con.execute(
            "SELECT COUNT(*) FROM core_saves WHERE archived_at IS NULL"
        ).fetchone()[0]
    except Exception as e:
        print(f"ERROR reading core_saves: {e}")
        con.close()
        return 1
    con.close()

    print(f"Core saves: {total} total, {active} active (not archived).")
    if active == 0:
        print("Nothing to archive — Core is already a clean slate.")
        return 0

    print(f"\nThis archives all {active} active saves (sets archived_at).")
    print("Reversible: a .bak backup is written first; restore it to undo.\n")
    resp = input("Type 'archive' to proceed (anything else aborts): ").strip().lower()
    if resp != "archive":
        print("Aborted — no change made.")
        return 0

    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    bak = f"{path}.pre-archive-{ts}.bak"
    shutil.copy2(path, bak)
    print(f"Backup written: {bak}")

    con = sqlite3.connect(path)
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        "UPDATE core_saves SET archived_at = ? WHERE archived_at IS NULL",
        (now,),
    )
    con.commit()
    remaining = con.execute(
        "SELECT COUNT(*) FROM core_saves WHERE archived_at IS NULL"
    ).fetchone()[0]
    con.close()

    print(f"Archived {active} saves. Active remaining: {remaining}.")
    print("\nNext:")
    print("  1. Restart the server.")
    print("  2. Open My Core — the saves column should be empty.")
    print("  3. Run a recall prompt (e.g. 'recall what I saved about AR') —")
    print("     the old junk should no longer surface.")
    print(f"\nTo undo everything: copy {os.path.basename(bak)} back over coreckoner.db.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
