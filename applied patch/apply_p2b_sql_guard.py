#!/usr/bin/env python3
"""
P2b APPLIER — SQL-only route SQL-unusable guard

Mirrors the existing P2 BOTH-route guard into the `elif route == "sql":`
branch of /chat in backend/main.py. When the SQL pipeline returns a stub or
leaks a raw execution error (e.g. Phase 6 Sim 4 / Image 4 Oracle UNION
"no such column"), the SQL-only route surfaced that raw text to the user.
This patch replaces it with a clean fallback.

Safety properties:
  • Makes a timestamped .bak before touching anything.
  • Idempotent — detects the P2b marker and no-ops on re-run.
  • Uniqueness-checked — refuses to apply unless the target appears exactly once.
  • All-or-nothing — after writing, it py_compiles main.py; if compilation
    fails for ANY reason, it restores the backup and exits non-zero.

Run from the app2 project root:

    python3 apply_p2b_sql_guard.py
"""
import os
import sys
import shutil
import py_compile
from datetime import datetime

MARKER = "_p2b_unusable_patterns"

# ---- exact target (must match main.py byte-for-byte, appears exactly once) --
OLD = (
    '            elif route == "sql":\n'
    '                final_answer = sql_result.get("answer", "No answer generated.")'
)

# ---- replacement block (12-space elif, 16-space body) ----------------------
NEW = "\n".join([
    '            elif route == "sql":',
    '                # P2b stabilization: guard the SQL-only route the same way',
    '                # the BOTH route is guarded. If the SQL pipeline returned a',
    '                # stub or leaked an execution error, replace it with a clean',
    '                # fallback instead of surfacing raw SQLite text to the user',
    '                # (Phase 6 Sim 4 / Image 4 Oracle UNION "no such column").',
    '                _sql_only_ans   = sql_result.get("answer", "")',
    '                _sql_only_lower = str(_sql_only_ans).lower()',
    '                _p2b_unusable_patterns = (',
    '                    "no uploaded data",',
    '                    "this data is not in the uploaded files",',
    "                    \"this data isn't in the demo tables\",",
    '                    "execution failed",',
    '                    "only one sql statement",',
    '                    "no such column",',
    '                    "no such table",',
    '                    "selects to the left and right of union",',
    '                    "syntax error",',
    '                    "the query execution failed",',
    '                    "the query could not be executed",',
    '                )',
    '                _p2b_unusable = (',
    '                    not _sql_only_ans',
    '                    or any(p in _sql_only_lower for p in _p2b_unusable_patterns)',
    '                )',
    '                if _p2b_unusable:',
    '                    final_answer = (',
    "                        \"I couldn't form a reliable data query. Could you \"",
    '                        "specify which table, amount, or comparison target "',
    "                        \"you'd like me to look at?\"",
    '                    )',
    '                    response_type = "answer"',
    '                else:',
    '                    final_answer = sql_result.get("answer", "No answer generated.")',
])


def find_main_py():
    candidates = [
        "backend/main.py",
        "main.py",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend", "main.py"),
    ]
    return next((p for p in candidates if os.path.isfile(p)), None)


def main():
    path = find_main_py()
    if not path:
        print("ERROR: could not find backend/main.py.")
        print("Run this from the app2 project root (folder containing 'backend/').")
        return 1

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    # idempotence
    if MARKER in src:
        print("Already applied — found P2b marker in main.py. No change made.")
        return 0

    # uniqueness
    count = src.count(OLD)
    if count == 0:
        print("ERROR: target SQL-only branch not found. main.py may have changed.")
        print("Expected to find exactly this block once:\n")
        print(OLD)
        return 1
    if count > 1:
        print(f"ERROR: target block found {count} times — expected exactly 1.")
        print("Aborting to avoid an ambiguous edit.")
        return 1

    # backup
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    bak = f"{path}.pre-p2b-{ts}.bak"
    shutil.copy2(path, bak)
    print(f"Backup written: {bak}")

    # apply
    patched = src.replace(OLD, NEW, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(patched)

    # verify it still compiles; restore on any failure
    try:
        py_compile.compile(path, doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, path)
        print("ERROR: patched main.py failed to compile — backup restored.")
        print(str(e))
        return 1

    print("P2b applied and main.py compiles cleanly.")
    print("SQL-only route now falls back gracefully when SQL is unusable.")
    print("\nRestart the server to pick it up:")
    print('  pkill -9 -f "backend/main.py" 2>/dev/null ; true')
    print("  lsof -ti:8002 | xargs kill -9 2>/dev/null ; true")
    print("  python3 backend/main.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
