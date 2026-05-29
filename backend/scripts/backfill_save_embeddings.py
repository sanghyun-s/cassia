"""
=============================================================
backfill_save_embeddings.py — one-time fill for pre-4d saves
=============================================================

For every active core_save that has no embedding_json yet, embed its
content via OpenAI and cache the vector. Idempotent — running it twice
is safe; already-embedded saves are skipped.

Usage (FROM the app2 root, not from backend/):
    cd "/path/to/app2"
    source venv/bin/activate
    python3 backend/scripts/backfill_save_embeddings.py
"""

import json
import sys
from pathlib import Path

# Make `db.session_store` and `pipelines.core_embed` importable when
# running this script directly from /backend/scripts/.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # → /app2/backend

from dotenv import load_dotenv
load_dotenv()

from db.session_store import (
    DEFAULT_USER_ID,
    list_saves_needing_embedding,
    update_save_embedding,
)
from pipelines.core_embed import embed_text


def main() -> int:
    pending = list_saves_needing_embedding(DEFAULT_USER_ID)
    if not pending:
        print("✓ All active saves already have embeddings — nothing to do.")
        return 0

    print(f"Found {len(pending)} save(s) needing embeddings. Embedding…")
    ok   = 0
    fail = 0
    for s in pending:
        save_id = s["save_id"]
        title   = (s.get("title") or "")[:60]
        content = s.get("content") or ""
        if not content.strip():
            print(f"  ⚠ {save_id} has empty content — skipping")
            fail += 1
            continue
        try:
            vec  = embed_text(content)
            vstr = json.dumps(vec)
            if update_save_embedding(save_id, vstr):
                print(f"  ✓ {save_id}  ({title})")
                ok += 1
            else:
                print(f"  ⚠ {save_id} update returned False")
                fail += 1
        except Exception as e:
            print(f"  ✗ {save_id} failed: {e}")
            fail += 1

    print(f"\nDone. {ok} embedded, {fail} failed/skipped.")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
