#!/usr/bin/env python3
"""
PATCH P1d  —  chart layout isolation + explicit x-axis type
============================================================
Fixes: P3 / P7 (vendor bar charts) render EMPTY with a default
"Jan 2000 - Jan 2001" date axis after P1c made P2/P6 real date charts.

ROOT CAUSE
----------
renderChart builds its layout with a SHALLOW spread:

    let layout = { ...PLOTLY_LAYOUT, title: {...} };

A shallow spread copies the top level but SHARES the nested `xaxis`
object with the global PLOTLY_LAYOUT. Plotly.newPlot mutates the layout
it receives IN PLACE, writing `xaxis.type = 'date'` when it sees date
values. Because xaxis is shared, that 'date' type leaks onto the global
object and onto the NEXT chart. A following vendor chart (text x-values)
then inherits type='date', can't parse the vendor names as dates, and
falls back to Plotly's empty default range -> "Jan 2000 - Jan 2001".

FIX
---
1) Deep-clone the layout so every chart owns its xaxis/yaxis objects
   (eliminates the cross-chart leak  =  the actual root cause).
2) Explicitly set xaxis.type ('date' if the labels look like dates,
   else 'category') so axis type is deterministic instead of guessed.

P2/P6 (date labels) -> 'date' axis (unchanged, still correct).
P3/P7 (vendor labels) -> 'category' axis (bars render again).

SAFE: frontend-only, backed up, idempotent, self-restoring on failure.
Run from the app2 project root:

    python3 apply_p1d_chart_axis_isolation.py
"""
import os
import re
import sys
import shutil
import datetime

CANDIDATES = [
    "backend/static/index.html",
    "static/index.html",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend", "static", "index.html"),
]

# ---- exact strings from the live file (verified against locate_renderchart.py) ----
OLD_LAYOUT = (
    "let layout  = { ...PLOTLY_LAYOUT, title: { text: question.slice(0,60), "
    "font: { color: '#8b949e', size: 12 } } };"
)
NEW_LAYOUT = (
    "let layout  = JSON.parse(JSON.stringify(PLOTLY_LAYOUT));\n"
    "  layout.title = { text: question.slice(0,60), font: { color: '#8b949e', size: 12 } };\n"
    "  const _p1LooksDate = s => /^\\d{4}-\\d{1,2}-\\d{1,2}/.test(String(s == null ? '' : s).trim());\n"
    "  const _p1xIsDate = labels.length > 0 && (labels.filter(_p1LooksDate).length / labels.length) > 0.6;"
)

OLD_TIMER = (
    "  setTimeout(() => {\n"
    "    try {\n"
    "      Plotly.newPlot(divId, traces, layout, {"
)
NEW_TIMER = (
    "  if (chartType !== 'pie') {\n"
    "    layout.xaxis = Object.assign({}, layout.xaxis, { type: _p1xIsDate ? 'date' : 'category' });\n"
    "  }\n"
    "\n"
    "  setTimeout(() => {\n"
    "    try {\n"
    "      Plotly.newPlot(divId, traces, layout, {"
)

ALREADY = "JSON.parse(JSON.stringify(PLOTLY_LAYOUT))"


def fail(msg, path=None, backup=None):
    print("\n*** ABORTED — no changes kept ***")
    print("    " + msg)
    if path and backup and os.path.isfile(backup):
        shutil.copy2(backup, path)
        print(f"    restored original from {backup}")
    sys.exit(1)


def main():
    path = next((p for p in CANDIDATES if os.path.isfile(p)), None)
    if not path:
        fail("backend/static/index.html not found. Run from the app2 root.")
    path = os.path.abspath(path)
    print(f"target: {path}")

    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    # idempotency
    if ALREADY in src:
        print("Already patched (deep-cloned layout present). Nothing to do.")
        return

    # pre-conditions: each anchor must exist exactly once
    if src.count(OLD_LAYOUT) != 1:
        fail(f"layout-init line found {src.count(OLD_LAYOUT)}x (expected 1). File differs from expected.")
    if src.count(OLD_TIMER) != 1:
        fail(f"Plotly setTimeout block found {src.count(OLD_TIMER)}x (expected 1). File differs from expected.")

    # backup
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = f"{path}.pre-p1d-{ts}.bak"
    shutil.copy2(path, backup)
    print(f"backup : {backup}")

    # apply
    out = src.replace(OLD_LAYOUT, NEW_LAYOUT, 1)
    out = out.replace(OLD_TIMER, NEW_TIMER, 1)

    # post-conditions
    checks = {
        "deep-clone present": ALREADY in out,
        "_p1xIsDate present": "_p1xIsDate" in out,
        "explicit xaxis.type present": "layout.xaxis = Object.assign({}, layout.xaxis, { type: _p1xIsDate" in out,
        "old shallow layout gone": OLD_LAYOUT not in out,
        "Plotly.newPlot still present": "Plotly.newPlot(divId, traces, layout," in out,
    }
    # balanced braces/parens in the file shouldn't change net-zero from our edits
    for name, ok in checks.items():
        if not ok:
            fail(f"post-check failed: {name}", path, backup)

    with open(path, "w", encoding="utf-8") as f:
        f.write(out)

    print("\nOK — P1d applied.")
    for name in checks:
        print(f"  [ok] {name}")
    print("\nNext:")
    print("  1) restart the server:  python3 backend/main.py")
    print("  2) HARD-refresh the browser (Cmd+Shift+R)")
    print("  3) re-run Sim 2 — all four charts (P2,P3,P6,P7) should render.")
    print(f"\nRevert if needed:\n  cp \"{backup}\" \"{path}\"")


if __name__ == "__main__":
    main()
