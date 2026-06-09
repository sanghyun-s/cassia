#!/usr/bin/env python3
"""
Stabilization v2 — Priority 3: RAG 'not found' message rewording.

Two strings in backend/pipelines/rag_pipeline.py are replaced with an
action-oriented version that tells the user what to do next:

  Line 54:  LLM prompt instruction — what the LLM should say when the
            corpus has only partial info
  Line 230: Code fallback — what gets returned when no excerpts at all

Both updated to:
  "I couldn't find support for that in the currently indexed documents.
   Try uploading a relevant policy, client memo, agency notice, or
   source document — I can search anything you add to the session."

Safety:
  - Backs up rag_pipeline.py with a timestamp suffix
  - Idempotent: re-running on patched file is a no-op
  - Pattern-uniqueness check before write
  - Reports honestly if patterns missing (file may have been edited)

Run from app2/ project root:
    python3 apply_p3_rag_message.py
"""

import shutil
import sys
from pathlib import Path
from datetime import datetime


PROJECT_ROOT = Path.cwd()
FILE_PATH    = PROJECT_ROOT / "backend" / "pipelines" / "rag_pipeline.py"

NEW_MESSAGE = (
    "I couldn't find support for that in the currently indexed documents. "
    "Try uploading a relevant policy, client memo, agency notice, or "
    "source document — I can search anything you add to the session."
)

REPLACEMENTS = [
    # (label, old_substring, new_substring)
    (
        "line ~54  (LLM prompt instruction)",
        "I couldn't find that in the available documents.",
        NEW_MESSAGE,
    ),
    (
        "line ~230 (code fallback)",
        "I couldn't find anything relevant in the available documents.",
        NEW_MESSAGE,
    ),
]


def backup(path: Path) -> Path:
    ts  = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    bak = path.with_suffix(path.suffix + f".pre-p3-rag-msg-{ts}.bak")
    shutil.copy2(str(path), str(bak))
    return bak


def main():
    print("=" * 72)
    print("  Stabilization v2 — Priority 3: RAG 'not found' message")
    print("=" * 72)
    print()
    print(f"File: {FILE_PATH}")
    print()

    if not FILE_PATH.exists():
        print(f"✗ File not found at {FILE_PATH}")
        print("  Run this from the app2/ project root.")
        return 1

    text = FILE_PATH.read_text()

    # Classify each replacement: needs patch / already done / not found
    pending      = []
    already_done = []
    not_found    = []

    for label, old, new in REPLACEMENTS:
        has_old = old in text
        has_new = new in text
        # Note: NEW_MESSAGE is the same for both replacements, so "has_new"
        # alone isn't enough — we check has_old as the authoritative signal
        if has_old and text.count(old) == 1:
            pending.append((label, old, new))
        elif has_old and text.count(old) > 1:
            print(f"  ⚠ {label}: old string appears multiple times — ambiguous")
            return 1
        elif not has_old and has_new:
            already_done.append(label)
        else:
            not_found.append((label, old))

    if not pending and already_done and not not_found:
        print(f"  ✓ All {len(already_done)} site(s) already patched.")
        return 0

    if not_found:
        print(f"  ⚠ {len(not_found)} expected pattern(s) not found:")
        for label, old in not_found:
            print(f"      {label}: '{old[:60]}...'")
        print()
        print("  The file may have been edited since the locator ran.")
        print("  Inspect manually before retrying.")
        return 1

    # Back up before any write
    bak = backup(FILE_PATH)
    print(f"Backed up to: {bak.name}")
    print()

    # Apply replacements
    new_text = text
    for label, old, new in pending:
        new_text = new_text.replace(old, new, 1)
        print(f"  ✓ {label}: replaced")

    if already_done:
        for label in already_done:
            print(f"  · {label}: already patched (skipped)")

    FILE_PATH.write_text(new_text)
    print()
    print(f"Applied {len(pending)} replacement(s).")
    print()
    print("Verification — run these in order:")
    print()
    print("  1. Syntax check (no Python errors after the edit):")
    print("       python3 -m py_compile backend/pipelines/rag_pipeline.py")
    print()
    print("  2. Restart server:")
    print("       lsof -ti:8002 | xargs kill -9 2>/dev/null ; true")
    print("       python3 backend/main.py")
    print()
    print("  3. In the UI, run a question Pub 15 doesn't cover, e.g.:")
    print('       "What does the IRS say about AR recordkeeping?"')
    print()
    print("     Expect orange 'Not found in docs' badge with the new")
    print("     message — should mention uploading a relevant document.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
