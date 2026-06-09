#!/usr/bin/env python3
"""
Deliverable B — Step 2: Patch the 5 storage call sites.

Patches identified by the Step 1 scanner:
  backend/db/session_store.py    (4 sites)
  backend/main.py                (1 site)

Each file is:
  1. Backed up with a timestamp suffix
  2. Updated to import safe_json_dumps from backend.utils.json_safe
  3. Updated to replace json.dumps(...) with safe_json_dumps(...) at
     the specific storage call sites

The applier is idempotent — re-running on patched files is a no-op.
Run from app2/ project root.
"""

import shutil
import sys
from pathlib import Path
from datetime import datetime


PROJECT_ROOT = Path.cwd()
IMPORT_LINE  = "from backend.utils.json_safe import safe_json_dumps"

# Each entry: (relative_path, [(old_pattern, new_pattern), ...])
PATCHES = {
    "backend/db/session_store.py": [
        # Site 1 (line 385): artifact content_json — CRITICAL
        (
            "content_json = json.dumps(content, ensure_ascii=False)",
            "content_json = safe_json_dumps(content)",
        ),
        # Site 2 (line 463): upload summary_json — defensive
        (
            "else json.dumps(summary_json, ensure_ascii=False))",
            "else safe_json_dumps(summary_json))",
        ),
        # Site 3 (line 474): table_names list — defensive
        (
            "json.dumps(table_names) if table_names else None,",
            "safe_json_dumps(table_names) if table_names else None,",
        ),
        # Site 4 (line 729): save metadata_json — CRITICAL
        (
            "else json.dumps(metadata_json, ensure_ascii=False))",
            "else safe_json_dumps(metadata_json))",
        ),
    ],
    "backend/main.py": [
        # Site 5 (line 319): embedding vector — defensive
        (
            "vstr = json.dumps(vec)",
            "vstr = safe_json_dumps(vec)",
        ),
    ],
}


def backup(path: Path) -> Path:
    ts  = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    bak = path.with_suffix(path.suffix + f".pre-nanfix-step2-{ts}.bak")
    shutil.copy2(str(path), str(bak))
    return bak


def add_import(content: str) -> tuple[str, bool]:
    """Insert IMPORT_LINE after the first 'import json' line.

    Returns (new_content, was_added).
    """
    if IMPORT_LINE in content:
        return content, False

    lines = content.split("\n")
    insert_at = None

    # Strategy 1: place right after 'import json'
    for i, line in enumerate(lines):
        if line.strip() == "import json":
            insert_at = i + 1
            break

    # Strategy 2: place after the last top-level import in the first 50 lines
    if insert_at is None:
        last_import = -1
        for i, line in enumerate(lines[:50]):
            stripped = line.strip()
            if (stripped.startswith("import ") or stripped.startswith("from ")) \
                    and not line.startswith(" "):
                last_import = i
        if last_import >= 0:
            insert_at = last_import + 1

    if insert_at is None:
        # Strategy 3: place at line 1 (after any shebang/docstring is fragile;
        # punt and let the user fix it manually)
        return content, False

    lines.insert(insert_at, IMPORT_LINE)
    return "\n".join(lines), True


def patch_file(rel_path: str, replacements: list) -> dict:
    """Patch one file. Returns a result dict."""
    path = PROJECT_ROOT / rel_path
    result = {
        "path":          rel_path,
        "exists":        path.exists(),
        "backup":        None,
        "import_added":  False,
        "already_done":  0,
        "patched":       0,
        "ambiguous":     [],
        "not_found":     [],
    }

    if not path.exists():
        return result

    content = path.read_text()

    # Classify each replacement
    pending = []
    for old, new in replacements:
        already_has_new = new in content
        has_old         = old in content
        if already_has_new and not has_old:
            result["already_done"] += 1
        elif has_old:
            count = content.count(old)
            if count == 1:
                pending.append((old, new))
            else:
                result["ambiguous"].append((old, count))
        else:
            result["not_found"].append(old)

    needs_import = any(IMPORT_LINE not in content for _ in [None]) \
                   and (pending or result["already_done"] > 0) \
                   and IMPORT_LINE not in content

    if not pending and not needs_import:
        return result

    # Back up before any writes
    result["backup"] = backup(path).name

    if needs_import:
        content, added = add_import(content)
        result["import_added"] = added

    for old, new in pending:
        content = content.replace(old, new, 1)
        result["patched"] += 1

    path.write_text(content)
    return result


def smoke_test_import():
    """Verify backend.utils.json_safe is importable from PROJECT_ROOT."""
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from backend.utils.json_safe import safe_json_dumps  # noqa: F401
        return True, None
    except Exception as e:
        return False, str(e)


def main():
    print("=" * 70)
    print("  Deliverable B — Step 2: patch storage call sites")
    print("=" * 70)
    print()
    print(f"Project root: {PROJECT_ROOT}")
    print()

    # Pre-flight
    print("[Pre-flight] Verifying json_safe utility is importable")
    print("-" * 70)
    ok, err = smoke_test_import()
    if not ok:
        print(f"  ✗ Cannot import backend.utils.json_safe — {err}")
        print("    Run apply_nan_fix.py (Step 1) first to install the utility.")
        return 1
    print("  ✓ backend.utils.json_safe imports cleanly")
    print()

    # Apply patches
    print("[Patching]")
    print("-" * 70)
    any_writes = False
    any_problems = False
    for rel_path, replacements in PATCHES.items():
        print(f"\n{rel_path}")
        result = patch_file(rel_path, replacements)

        if not result["exists"]:
            print(f"  ⚠ File not found — skipping")
            any_problems = True
            continue

        if result["backup"]:
            print(f"  Backed up to: {result['backup']}")
            any_writes = True

        if result["import_added"]:
            print(f"  + Added import: {IMPORT_LINE}")
        elif result["patched"] > 0 or result["already_done"] > 0:
            print(f"  · Import already present")

        if result["patched"]:
            print(f"  ✓ Applied {result['patched']} patch(es)")
        if result["already_done"]:
            print(f"  · {result['already_done']} site(s) already patched (skipped)")
        if result["ambiguous"]:
            any_problems = True
            print(f"  ⚠ {len(result['ambiguous'])} ambiguous pattern(s):")
            for old, count in result["ambiguous"]:
                print(f"      appears {count} times — manual fix needed:")
                print(f"      {old[:80]}")
        if result["not_found"]:
            any_problems = True
            print(f"  ⚠ {len(result['not_found'])} expected pattern(s) not found:")
            for old in result["not_found"]:
                print(f"      {old[:80]}")
            print(f"      (file may have been edited since Step 1's scan)")

    print()
    print("=" * 70)
    if any_problems:
        print("Done with warnings — review the output above.")
    elif any_writes:
        print("Done. All patches applied cleanly.")
    else:
        print("Done. No changes needed — everything was already patched.")
    print("=" * 70)
    print()

    print("Verification — please run these in order:")
    print()
    print("  1. Confirm the patch didn't break Python import paths:")
    print("       python3 -c 'from backend.utils.json_safe import safe_json_dumps; print(\"ok\")'")
    print()
    print("  2. Re-run the diagnostic to confirm zero stored NaN:")
    print("       python3 ~/Downloads/cassia_nan_check.py")
    print()
    print("  3. Start the server and run a single new GL query to test the patch:")
    print('       Prompt: "Show me the first 5 rows of the general ledger."')
    print("     Then re-run cassia_nan_check.py — should still report 0 NaN.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
