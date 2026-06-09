#!/usr/bin/env python3
"""
Hot-fix for the Step 2 patch — corrects the import path style.

Background
----------
Step 2 inserted this import in main.py and session_store.py:
    from backend.utils.json_safe import safe_json_dumps

That syntax requires Python to see 'backend' as a package. It works when
the project is launched with 'python3 -m backend.main' (proper module
mode) or with PYTHONPATH set to the project root.

CASSIA's actual entry point is 'python3 backend/main.py', which adds
'backend/' itself to sys.path — so 'utils/' is visible directly but
'backend/' is invisible as a package name.

This script corrects the import to:
    from utils.json_safe import safe_json_dumps

which matches the import style the rest of the codebase already uses
(e.g. 'from db.session_store import ...').

Safety
------
- Backs up each file before modifying
- Idempotent: re-running on already-fixed files is a no-op
- Verifies only the import line changes; nothing else
"""

import shutil
import sys
from pathlib import Path
from datetime import datetime


PROJECT_ROOT = Path.cwd()
OLD_IMPORT   = "from backend.utils.json_safe import safe_json_dumps"
NEW_IMPORT   = "from utils.json_safe import safe_json_dumps"

TARGETS = [
    "backend/db/session_store.py",
    "backend/main.py",
]


def backup(path: Path) -> Path:
    ts  = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    bak = path.with_suffix(path.suffix + f".pre-importfix-{ts}.bak")
    shutil.copy2(str(path), str(bak))
    return bak


def main():
    print("=" * 70)
    print("  Step 2 import path hot-fix")
    print("=" * 70)
    print()
    print(f"Project root: {PROJECT_ROOT}")
    print()
    print(f"Replacing:  {OLD_IMPORT}")
    print(f"With:       {NEW_IMPORT}")
    print()

    any_change = False
    any_problem = False

    for rel in TARGETS:
        path = PROJECT_ROOT / rel
        if not path.exists():
            print(f"  ✗ {rel}  (file not found — skipped)")
            any_problem = True
            continue

        text = path.read_text()

        has_old = OLD_IMPORT in text
        has_new = NEW_IMPORT in text

        if has_new and not has_old:
            print(f"  · {rel}  (already fixed)")
            continue
        if not has_old:
            print(f"  ⚠ {rel}  (expected old import not found)")
            print(f"     The file may have a different import style.")
            print(f"     Paste lines 1-50 of {rel} and I'll write a precise patch.")
            any_problem = True
            continue
        if text.count(OLD_IMPORT) > 1:
            print(f"  ⚠ {rel}  (old import appears multiple times — ambiguous)")
            any_problem = True
            continue

        bak = backup(path)
        text = text.replace(OLD_IMPORT, NEW_IMPORT)
        path.write_text(text)
        print(f"  ✓ {rel}  fixed  (backup: {bak.name})")
        any_change = True

    print()
    print("=" * 70)
    if any_problem:
        print("Done with warnings — review output above.")
    elif any_change:
        print("Done. Import paths corrected.")
    else:
        print("Done. No changes needed.")
    print("=" * 70)
    print()
    print("Try starting the server again:")
    print("    python3 backend/main.py")
    print()
    print("If you get a NEW import error (different message), copy the")
    print("full traceback and paste it back — we'll trace the next layer.")
    print()
    return 0 if not any_problem else 1


if __name__ == "__main__":
    sys.exit(main())
