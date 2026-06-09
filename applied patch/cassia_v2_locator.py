#!/usr/bin/env python3
"""
CASSIA stabilization v2 — locator script.

Read-only scan of backend/ to find the five file:line locations we
need to patch for the v2 stabilization plan:

  Priority 1 — Chart-spec construction
  Priority 2a — SQL "no uploaded data" stub emission point
  Priority 2b — BOTH-route synthesizer (prompt + composition)
  Priority 3 — RAG "not found in docs" message string
  Priority 4 — Core Recall handler (for timeout wrapping)

The script does NOT modify any files. It prints file:line:content for
each match so the patches can be written surgically. Paste the output
back when done.

Run from app2/ project root:
    python3 cassia_v2_locator.py
"""

import re
import sys
from pathlib import Path


PROJECT_ROOT = Path.cwd()
BACKEND_DIR  = PROJECT_ROOT / "backend"

# Each target: (display_name, description, list of regex patterns)
TARGETS = [
    (
        "PRIORITY 3 — RAG 'not found in docs' message",
        "The literal user-visible string we'll reword for action-orientation",
        [
            r"I couldn'?t find that in the available documents",
            r"couldn'?t find.{0,30}available documents",
            r"Not found in docs",
        ],
    ),
    (
        "PRIORITY 2a — SQL 'no uploaded data' stub emission",
        "Where 'SELECT \"No uploaded data in this session\"' is generated",
        [
            r"No uploaded data in this session",
            r"No uploaded data",
            r"this data is not in the uploaded files",
        ],
    ),
    (
        "PRIORITY 2b — BOTH-route synthesizer",
        "Function/prompt that composes the final answer from SQL + RAG",
        [
            r"def\s+\w*synth\w*\s*\(",
            r'route\s*==\s*["\']BOTH["\']',
            r'["\']BOTH["\']\s*:',
            r"both_pipeline",
            r"both_synth",
            r"compose_both",
            r"combine_results",
            r"synthesize_response",
            r"sql_result.{0,80}rag_result",
            r"rag_result.{0,80}sql_result",
        ],
    ),
    (
        "PRIORITY 1 — Chart-spec construction",
        "Where SQL result columns become chart series",
        [
            r"def\s+\w*chart\w*\s*\(",
            r"def\s+\w*plot\w*\s*\(",
            r"def\s+build_chart",
            r"chart_spec\s*=",
            r'["\']chart_spec["\']',
            r"is_numeric_dtype",
            r"select_dtypes\(.{0,40}number",
            r"plotly\b|go\.Figure|go\.Bar|go\.Scatter|go\.Pie",
        ],
    ),
    (
        "PRIORITY 4 — Core Recall handler",
        "The recall pipeline + embedding-call site (for timeout wrapping)",
        [
            r"def\s+\w*recall\w*\s*\(",
            r'route\s*==\s*["\']CORE_RECALL["\']',
            r'["\']CORE_RECALL["\']\s*:',
            r"/core/recall",
            r"recall_pipeline",
            r"def\s+search_saves",
            r"def\s+semantic_search",
            r"core_saves.{0,40}similar",
            r"similar.{0,40}core_saves",
        ],
    ),
]


def scan_file(path: Path, patterns):
    """Return [(line_no, line_text, matched_pattern), ...] for this file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        for pat in patterns:
            if re.search(pat, line):
                hits.append((i, line, pat))
                break  # one match per line, even if multiple patterns hit
    return hits


def walk_py(root: Path):
    """Yield all .py files under root, skipping caches/venvs/dotdirs."""
    skip = {
        "__pycache__", "venv", ".venv", "env", ".env",
        "node_modules", ".git", "build", "dist",
        ".pytest_cache", ".mypy_cache",
    }
    for p in root.rglob("*.py"):
        if any(part in skip or part.startswith(".") for part in p.parts):
            continue
        yield p


def main():
    print("=" * 72)
    print("  CASSIA stabilization v2 — locator")
    print("=" * 72)
    print()
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Scanning:     {BACKEND_DIR}")
    print()

    if not BACKEND_DIR.exists():
        print(f"ERROR: backend/ not found at {BACKEND_DIR}")
        print("       Run this from the app2/ project root.")
        return 1

    all_py = list(walk_py(BACKEND_DIR))
    print(f"Files scanned: {len(all_py)}")
    print()

    overall = {}

    for name, desc, patterns in TARGETS:
        print("=" * 72)
        print(f"  {name}")
        print(f"  {desc}")
        print("-" * 72)
        target_hit_count = 0
        for path in all_py:
            hits = scan_file(path, patterns)
            if not hits:
                continue
            rel = path.relative_to(PROJECT_ROOT)
            print()
            print(f"  📄 {rel}")
            for ln, txt, _pat in hits:
                display = txt.rstrip()
                if len(display) > 96:
                    display = display[:93] + "..."
                stripped = display.lstrip()
                indent = len(display) - len(stripped)
                indent_marker = "·" * min(indent // 2, 8)
                print(f"      line {ln:>4}:  {indent_marker}{stripped}")
                target_hit_count += 1
        if target_hit_count == 0:
            print("  ⚠ No matches found.")
        overall[name] = target_hit_count
        print()

    # Summary
    print("=" * 72)
    print("  SUMMARY")
    print("=" * 72)
    for name, count in overall.items():
        marker = "✓" if count > 0 else "⚠"
        short = name.split(" — ")[0]
        print(f"  {marker} {short}: {count} hit(s)")
    print()

    missing = [n for n, c in overall.items() if c == 0]
    if missing:
        print("  ⚠ One or more targets had no matches. Possible causes:")
        print("    - Codebase uses unfamiliar function names")
        print("    - Patterns are too narrow")
        print("    - String is constructed dynamically (concatenation/format)")
        print("    Paste this output anyway — I can suggest follow-up searches.")
        print()

    print("Next step: paste this entire output back. I'll write the four")
    print("patch packages (sequence 3 → 1 → 2 → 4) against the actual")
    print("file:line locations.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
