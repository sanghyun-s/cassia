#!/usr/bin/env python3
"""
Deliverable B applier — installs json_safe helpers and patches CASSIA's
JSON storage call sites to prevent NaN/Inf from being written to the
database.

Safety:
  - Backs up every file before modifying it
  - Idempotent: re-running on a patched tree is a no-op
  - Reports honestly when patterns are not found (manual fix instructions
    provided in the output)
  - Verifies the final state by importing the new utility and running a
    smoke test

Run from app2/ project root:
    python3 apply_nan_fix.py
"""

import shutil
import sys
from pathlib import Path
from datetime import datetime


# ─────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path.cwd()
UTILS_DIR    = PROJECT_ROOT / "backend" / "utils"
UTILS_FILE   = UTILS_DIR / "json_safe.py"
INIT_FILE    = UTILS_DIR / "__init__.py"

# Files to patch and the patterns we look for
TARGETS = [
    PROJECT_ROOT / "backend" / "pipelines" / "sql_pipeline.py",
    PROJECT_ROOT / "backend" / "db"        / "session_store.py",
    PROJECT_ROOT / "backend" / "main.py",
]

# Source of the new utility module (paste of json_safe.py contents)
JSON_SAFE_SRC = '''"""
JSON serialization safety helpers.

Wrap objects with sanitize_for_json() before json.dumps() to convert NaN/Inf
to None. Use safe_json_dumps() as a drop-in replacement.
"""

import json
import math


def sanitize_for_json(obj):
    """Recursively replace NaN/Inf floats with None."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_json(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(sanitize_for_json(x) for x in obj)
    return obj


def safe_json_dumps(obj, **kwargs):
    """Drop-in for json.dumps() with NaN/Inf -> null and allow_nan=False."""
    kwargs.setdefault("ensure_ascii", False)
    kwargs["allow_nan"] = False
    return json.dumps(sanitize_for_json(obj), **kwargs)
'''


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def backup(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    bak = path.with_suffix(path.suffix + f".pre-nanfix-{timestamp}.bak")
    shutil.copy2(str(path), str(bak))
    return bak


def already_patched(text: str) -> bool:
    """Heuristic: file imports from json_safe."""
    return "from backend.utils.json_safe" in text or "json_safe" in text


def patch_file(path: Path):
    """
    Inspect a file and report whether it uses json.dumps in a way that
    likely needs patching. Does NOT modify the file unless safe patterns
    are matched — instead returns a list of (line_no, suggestion) tuples.
    """
    if not path.exists():
        return ("missing", [])

    text = path.read_text()
    if already_patched(text):
        return ("already_patched", [])

    findings = []
    lines = text.splitlines()
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Look for json.dumps calls that aren't already wrapped
        if "json.dumps(" in stripped and "sanitize_for_json" not in stripped:
            findings.append((i, stripped[:120]))

    return ("inspected", findings)


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  CASSIA — Deliverable B (NaN prevention) installer")
    print("=" * 70)
    print()
    print(f"Project root: {PROJECT_ROOT}")
    print()

    # Phase 1: install the utility module
    print("[Phase 1] Installing json_safe utility module")
    print("-" * 70)
    UTILS_DIR.mkdir(parents=True, exist_ok=True)
    if not INIT_FILE.exists():
        INIT_FILE.write_text("")
        print(f"  ✓ Created {INIT_FILE.relative_to(PROJECT_ROOT)}")

    if UTILS_FILE.exists():
        existing = UTILS_FILE.read_text()
        if "sanitize_for_json" in existing:
            print(f"  ✓ Already installed: {UTILS_FILE.relative_to(PROJECT_ROOT)}")
        else:
            bak = backup(UTILS_FILE)
            UTILS_FILE.write_text(JSON_SAFE_SRC)
            print(f"  ✓ Replaced {UTILS_FILE.relative_to(PROJECT_ROOT)}")
            print(f"     (previous version backed up to {bak.name})")
    else:
        UTILS_FILE.write_text(JSON_SAFE_SRC)
        print(f"  ✓ Wrote {UTILS_FILE.relative_to(PROJECT_ROOT)}")
    print()

    # Phase 2: smoke test the new utility
    print("[Phase 2] Smoke-testing the utility")
    print("-" * 70)
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from backend.utils.json_safe import sanitize_for_json, safe_json_dumps
        import math, json
        test_in = {
            "rows": [
                {"debit": 68000.0, "credit": float("nan")},
                {"debit": float("nan"), "credit": 8653.0},
            ],
            "totals": {"net": float("inf")},
        }
        cleaned = sanitize_for_json(test_in)
        out = safe_json_dumps(test_in)
        # roundtrip
        roundtrip = json.loads(out)
        assert roundtrip["rows"][0]["credit"] is None
        assert roundtrip["rows"][1]["debit"]  is None
        assert roundtrip["totals"]["net"]    is None
        print("  ✓ sanitize_for_json: NaN/Inf -> None  (verified)")
        print("  ✓ safe_json_dumps:   strict-clean roundtrip  (verified)")
    except Exception as e:
        print(f"  ✗ Smoke test FAILED: {e}")
        print("  Stop here — do not proceed with patching.")
        return 1
    print()

    # Phase 3: scan call sites
    print("[Phase 3] Scanning likely call sites")
    print("-" * 70)
    print("  This phase does NOT modify your files. It reports where you")
    print("  likely need to apply the fix manually so I don't guess wrong.")
    print()

    any_findings = False
    for target in TARGETS:
        rel = target.relative_to(PROJECT_ROOT) if target.is_absolute() else target
        status, findings = patch_file(target)
        if status == "missing":
            print(f"  · {rel}  (file not found — skipped)")
            continue
        if status == "already_patched":
            print(f"  ✓ {rel}  (already imports json_safe — appears patched)")
            continue
        print(f"  ⚠ {rel}  ({len(findings)} json.dumps call(s) found):")
        for ln, snippet in findings:
            print(f"      line {ln}:  {snippet}")
            any_findings = True
        print()

    # Phase 4: instructions
    print("[Phase 4] Manual integration instructions")
    print("-" * 70)
    if not any_findings:
        print("  Nothing to do — no unpatched json.dumps() calls were found in")
        print("  the target files. The utility module is installed and ready")
        print("  for future use.")
    else:
        print("  At each line reported above, replace this pattern:")
        print()
        print("      json.dumps(payload)")
        print("            ↓")
        print("      safe_json_dumps(payload)")
        print()
        print("  And add this import at the top of the file:")
        print()
        print("      from backend.utils.json_safe import safe_json_dumps")
        print()
        print("  Only patch call sites that serialize for STORAGE or RESPONSE —")
        print("  not call sites that serialize for logging, debugging, or LLM")
        print("  prompt-building (those are read-only and don't need to be")
        print("  standards-compliant).")
        print()
        print("  Priority order (highest-impact first):")
        print("    1. sql_pipeline.py — wherever the SQL result is converted")
        print("       to JSON before being stored as an artifact")
        print("    2. session_store.py — wherever artifacts.content_json or")
        print("       core_saves.metadata_json is written")
        print("    3. main.py — any direct artifact/save writes from endpoints")

    print()
    print("=" * 70)
    print("Done.")
    print("=" * 70)
    print()
    print("Verification: after applying the manual patches, run")
    print("  python3 cassia_nan_check.py")
    print("then re-execute the same Sim 2 Prompt 1 query and confirm no new")
    print("records are flagged.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
