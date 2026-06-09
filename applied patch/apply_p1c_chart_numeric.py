#!/usr/bin/env python3
"""
P1c APPLIER — fix the date-as-number chart bug in backend/static/index.html.

Root cause: chart column classification used `!isNaN(parseFloat(v))`, and
parseFloat("2026-03-27") === 2026, so date columns (week_ending, pay_date, etc.)
were treated as the numeric measure and the chart plotted the YEAR.

Fix: introduce `_p1IsNumericVal(v)` (numeric only if the WHOLE value is a number,
via Number()), and use it in both classification spots — `_p1SelectChartColumns`
and `renderChart`. Frontend-only; touches no database and no Core data.

Safety: backup + idempotent + anchor/count checks + post-condition verify
(auto-restores the backup if the edit doesn't land cleanly).

Run from the app2 project root (server can be stopped):

    python3 apply_p1c_chart_numeric.py
"""
import os
import sys
import shutil
from datetime import datetime

MARKER = "_p1IsNumericVal"
ANCHOR = "const _P1_PREFERRED_MEASURE_COLS = new Set(["
OLD_PAT = "!isNaN(parseFloat(v))"
NEW_PAT = "_p1IsNumericVal(v)"

HELPER = (
    "// P1c stabilization: a value is numeric only if the WHOLE value parses as a\n"
    "// number. Date strings like \"2026-03-27\" stay labels (x-axis) instead of\n"
    "// being read as the number 2026 and plotted as the chart measure.\n"
    "function _p1IsNumericVal(v) {\n"
    "  if (v === null || v === undefined || v === '') return false;\n"
    "  const s = String(v).trim();\n"
    "  return s !== '' && !isNaN(Number(s));\n"
    "}\n\n"
)


def find_html():
    here = os.path.dirname(os.path.abspath(__file__))
    for p in ("backend/static/index.html", "static/index.html",
              os.path.join(here, "backend", "static", "index.html")):
        if os.path.isfile(p):
            return p
    return None


def main():
    path = find_html()
    if not path:
        print("ERROR: backend/static/index.html not found. Run from the app2 root.")
        return 1

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    if MARKER in src:
        print("Already applied — P1c marker present in index.html. No change made.")
        return 0

    if src.count(ANCHOR) != 1:
        print(f"ERROR: insert anchor found {src.count(ANCHOR)} times (expected 1). Aborting.")
        return 1

    npat = src.count(OLD_PAT)
    if npat != 2:
        print(f"ERROR: '{OLD_PAT}' found {npat} times (expected 2). index.html may have changed.")
        return 1

    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    bak = f"{path}.pre-p1c-{ts}.bak"
    shutil.copy2(path, bak)
    print(f"Backup written: {bak}")

    patched = src.replace(OLD_PAT, NEW_PAT)            # both classification filters
    patched = patched.replace(ANCHOR, HELPER + ANCHOR, 1)  # insert helper once

    with open(path, "w", encoding="utf-8") as f:
        f.write(patched)

    # NEW_PAT appears in both classification call sites AND the helper's own
    # signature `function _p1IsNumericVal(v)`, so expect >= 2 (was 0 before).
    ok = (
        MARKER in patched
        and patched.count(NEW_PAT) >= 2
        and patched.count(OLD_PAT) == 0
        and patched.count(ANCHOR) == 1
    )
    if not ok:
        shutil.copy2(bak, path)
        print("ERROR: post-conditions failed — backup restored, no change kept.")
        return 1

    print("P1c applied: date columns are now treated as labels, not measures.")
    print("\nNext:")
    print("  1. Restart the server:  python3 backend/main.py")
    print("  2. HARD-REFRESH the browser (Cmd+Shift+R) to load the new index.html")
    print("  3. Re-run a date-keyed chart (e.g. the bank-statement line) — it should")
    print("     now plot real dollar values, not a flat 2026.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
