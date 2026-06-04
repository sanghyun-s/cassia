"""
=============================================================
WIPE user_uploads — Pass 3 / Phase 5c one-time migration
=============================================================

WHY THIS EXISTS
---------------
Pre-Pass-3 vectors in the `user_uploads` ChromaDB collection have NO
`user_id` field in their metadata. After Pass 3, RAG retrieval requires
BOTH `session_id` AND `user_id` in the where-filter — so those orphan
vectors become invisible to queries but still occupy storage. The
`uploads` rows in coreckoner.db that reference them also become stale
(the UI would show files that produce no retrieval results).

This script cleans both layers atomically:

  1. Drops the `user_uploads` ChromaDB collection entirely (all vectors
     gone; collection auto-recreates on next upload).
  2. Deletes every `uploads` row with `target='rag'` (the sidebar will
     correctly show "no PDFs" for previously-uploaded sessions).

NOT TOUCHED
-----------
- `irs_pub15` ChromaDB collection — globally readable reference content
  (IRS Pub 15 / 15-T / 15-B). Unaffected.
- CSV / Excel uploads (`target='sql'`) — these live in session SQLite
  DBs, not ChromaDB. Unaffected.
- Sessions, messages, core saves, core topics, users, auth_sessions —
  all untouched.

USAGE
-----
Run from the app2/ project root after stopping the server:

    cd "/path/to/app2"
    source venv/bin/activate
    python3 backend/scripts/wipe_user_uploads.py

The script shows you what it's about to remove and waits for an
explicit `wipe` confirmation before doing anything.

AFTER RUNNING
-------------
Restart the server, log back in, and re-upload any PDFs you want
available for RAG. From this point forward, all PDF chunks carry
`user_id` metadata and are properly isolated per user.
"""

from pathlib import Path
import sqlite3
import sys

import chromadb

# Resolve project root (app2/) regardless of where we're invoked from.
PROJECT_ROOT = Path(__file__).parent.parent.parent
CHROMA_DIR   = PROJECT_ROOT / "outputs" / "chroma_db"
DB_PATH      = PROJECT_ROOT / "outputs" / "coreckoner.db"

COLLECTION_NAME = "user_uploads"


def main() -> int:
    print("=" * 64)
    print("  CASSIA — wipe user_uploads (Pass 3 / Phase 5c migration)")
    print("=" * 64)
    print()
    print(f"  ChromaDB path : {CHROMA_DIR}")
    print(f"  Database path : {DB_PATH}")
    print()

    if not CHROMA_DIR.exists():
        print(f"✗  ChromaDB directory missing: {CHROMA_DIR}")
        return 1
    if not DB_PATH.exists():
        print(f"✗  Database file missing: {DB_PATH}")
        return 1

    # ── Pre-count what we'd remove ─────────────────────────────────
    rag_row_count = 0
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM uploads WHERE target = 'rag'")
        rag_row_count = cur.fetchone()[0]
        conn.close()
    except Exception as e:
        print(f"!  Could not pre-count uploads rows: {e}")

    chroma_collection_present = False
    chroma_client = None
    try:
        chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        existing = [c.name for c in chroma_client.list_collections()]
        chroma_collection_present = COLLECTION_NAME in existing
    except Exception as e:
        print(f"!  Could not inspect ChromaDB collections: {e}")

    print("This will permanently:")
    if chroma_collection_present:
        print(f"  - Drop the '{COLLECTION_NAME}' ChromaDB collection  (PRESENT)")
    else:
        print(f"  - Drop the '{COLLECTION_NAME}' ChromaDB collection  (not present — will skip)")
    print(f"  - Delete {rag_row_count} row(s) from uploads WHERE target='rag'")
    print()
    print("NOT touched: irs_pub15 collection, CSV/Excel uploads, sessions,")
    print("             messages, core saves, core topics, users, auth sessions.")
    print()

    if rag_row_count == 0 and not chroma_collection_present:
        print("Nothing to do — already clean. Exiting.")
        return 0

    confirm = input("Type 'wipe' to proceed (anything else cancels): ").strip()
    if confirm != "wipe":
        print("Cancelled. No changes made.")
        return 0

    print()
    print("Wiping ...")

    # ── 1. Drop ChromaDB collection ───────────────────────────────
    if chroma_collection_present and chroma_client is not None:
        try:
            chroma_client.delete_collection(COLLECTION_NAME)
            print(f"  ✓ Dropped '{COLLECTION_NAME}' collection")
        except Exception as e:
            print(f"  ✗ Failed to drop collection: {e}")
            # Don't bail — still attempt the DB cleanup so we don't end
            # up half-done with no obvious recovery path.

    # ── 2. Delete uploads rows ────────────────────────────────────
    if rag_row_count > 0:
        try:
            conn = sqlite3.connect(str(DB_PATH))
            cur  = conn.cursor()
            cur.execute("DELETE FROM uploads WHERE target = 'rag'")
            deleted = cur.rowcount
            conn.commit()
            conn.close()
            print(f"  ✓ Deleted {deleted} uploads row(s) with target='rag'")
        except Exception as e:
            print(f"  ✗ Failed to delete uploads rows: {e}")

    print()
    print("Done. Next steps:")
    print("  1. Restart the server")
    print("  2. Log in to the chat UI")
    print("  3. Re-upload any PDFs you want available for RAG")
    print()
    print("All new uploads will carry user_id in their vector metadata.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
