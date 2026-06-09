#!/usr/bin/env python3
"""
CORE HEALTH CHECK  (read-only — modifies nothing)

Audits the *active* (non-archived) saves in outputs/coreckoner.db and flags:
  • JUNK — saves whose content is an error, a stub, or a recall non-answer
    (the stuff that shouldn't have been saved and pollutes recall)
  • DUPLICATES — the same answer saved more than once

Run anytime (server can be up or down), from the app2 project root:

    python3 core_health.py

Use it as a periodic hygiene check: if it reports junk, open My Core and
archive those saves; going forward, just don't save error/stub messages.
"""
import os
import re
import sqlite3
from collections import defaultdict

# Substrings that mark a save as junk (lowercased match against content).
JUNK_PATTERNS = [
    "i couldn't find",
    "i could not find",
    "i have related saves but",
    "no uploaded data",
    "is no uploaded data",
    "execution failed",
    "only one sql statement",
    "no records related to",
    "is not available in the provided data",
    "this data is not in the uploaded files",
    "isn't in the demo tables",
    "no such column",
    "no such table",
    "syntax error",
]
SHORT_LEN = 40  # very short content is almost always a test save


def find_db():
    here = os.path.dirname(os.path.abspath(__file__))
    for p in ("outputs/coreckoner.db", "coreckoner.db",
              os.path.join(here, "outputs", "coreckoner.db")):
        if os.path.isfile(p):
            return p
    return None


def norm(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())[:120]


def main():
    path = find_db()
    if not path:
        print("ERROR: outputs/coreckoner.db not found. Run from the app2 root.")
        return 1

    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT save_id, title, content FROM core_saves "
        "WHERE archived_at IS NULL ORDER BY created_at"
    ).fetchall()
    archived = con.execute(
        "SELECT COUNT(*) FROM core_saves WHERE archived_at IS NOT NULL"
    ).fetchone()[0]
    con.close()

    print("=" * 64)
    print(f"CORE HEALTH CHECK — {len(rows)} active saves "
          f"({archived} archived, ignored)")
    print("=" * 64)

    if not rows:
        print("\n✓ Core is clean — no active saves. Nothing to audit.")
        return 0

    junk = []
    clean = []
    for sid, title, content in rows:
        c = (content or "").lower()
        reason = None
        if len(c.strip()) < SHORT_LEN:
            reason = "very short / likely a test save"
        else:
            for p in JUNK_PATTERNS:
                if p in c:
                    reason = f'matches junk pattern: "{p}"'
                    break
        if reason:
            junk.append((sid, title, reason))
        else:
            clean.append((sid, title, content))

    # duplicate detection among the non-junk saves
    groups = defaultdict(list)
    for sid, title, content in clean:
        groups[norm(content)].append((sid, title))
    dupes = {k: v for k, v in groups.items() if len(v) > 1}

    print(f"\n  JUNK / shouldn't-be-saved: {len(junk)}")
    for sid, title, reason in junk:
        print(f"    ⚠ {sid}  [{reason}]")
        print(f"        {(title or '')[:80]}")

    print(f"\n  DUPLICATE answers: {len(dupes)} cluster(s)")
    for _, members in dupes.items():
        print(f"    ⚠ {len(members)} copies:")
        for sid, title in members:
            print(f"        {sid}  {(title or '')[:70]}")

    healthy = len(clean) - sum(len(v) for v in dupes.values())
    print(f"\n  Looks like real, unique findings: ~{max(healthy, 0)}")
    print("\n" + "-" * 64)
    if junk or dupes:
        print("Recommendation: open My Core and archive the flagged items,")
        print("or re-run archive_core_saves.py for a full reset.")
    else:
        print("✓ No junk or duplicates detected. Core looks healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
