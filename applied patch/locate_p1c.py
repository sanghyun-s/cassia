#!/usr/bin/env python3
"""
P1c LOCATOR  (read-only — modifies nothing)

Finds the frontend chart-column selector (the P1b helper `_p1SelectChartColumns`
and its `_P1_*` constants) in backend/static/index.html, plus wherever numeric
detection happens (parseFloat / Number / isNaN). This is where date strings like
"2026-03-27" get mis-read as the number 2026 and plotted as the chart measure.

Run from the app2 project root:

    python3 locate_p1c.py

Paste the ENTIRE output back into the chat.
"""
import os
import sys

CANDIDATES = [
    "backend/static/index.html",
    "static/index.html",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend", "static", "index.html"),
]
path = next((p for p in CANDIDATES if os.path.isfile(p)), None)
if not path:
    print("ERROR: could not find backend/static/index.html. Run from the app2 root.")
    sys.exit(1)

with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

n = len(lines)
print("=" * 70)
print(f"FILE        : {os.path.abspath(path)}")
print(f"TOTAL LINES : {n}")
print("=" * 70)

# --- compact index: numeric-detection tokens + P1 anchors -------------------
INDEX_TOKENS = [
    "_p1SelectChartColumns", "_P1_PREFERRED", "_P1_AVOID",
    "parseFloat", "Number(", "isNaN", "isNumeric", "typeof",
]
print("\n----- TOKEN INDEX (lineno: line) -----")
for i, line in enumerate(lines):
    for t in INDEX_TOKENS:
        if t in line:
            print(f"{i + 1:5d}: {line.rstrip()[:140]}")
            break

# --- full windows around the P1b helper / constants -------------------------
P1_ANCHORS = ["_p1SelectChartColumns", "_P1_PREFERRED", "_P1_AVOID"]
hits = [i for i, line in enumerate(lines) if any(a in line for a in P1_ANCHORS)]

PAD = 35
windows = []
for i in sorted(set(hits)):
    lo, hi = max(0, i - PAD), min(n, i + PAD + 1)
    if windows and lo <= windows[-1][1]:
        windows[-1][1] = max(windows[-1][1], hi)
    else:
        windows.append([lo, hi])

print("\n----- HELPER / CONSTANTS CONTEXT -----")
if not windows:
    print("(no P1b anchors found — the helper may be named differently)")
for lo, hi in windows:
    print(f"\n......... lines {lo + 1}-{hi} .........")
    for j in range(lo, hi):
        print(f"{j + 1:5d}  {lines[j].rstrip()}")

print("\n=== END OF LOCATOR OUTPUT ===")
