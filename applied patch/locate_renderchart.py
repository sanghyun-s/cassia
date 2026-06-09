#!/usr/bin/env python3
"""
RENDERCHART LOCATOR  (read-only)

Dumps the full renderChart function from backend/static/index.html — including
the part that builds the Plotly traces and layout (axis types) — which the
earlier locator cut off. This is where the empty "Jan 2000-Jan 2001" axis on
the vendor bar charts (P3/P7) is coming from.

Run from the app2 project root:

    python3 locate_renderchart.py

Paste the ENTIRE output back.
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
    print("ERROR: backend/static/index.html not found. Run from the app2 root.")
    sys.exit(1)

with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()
n = len(lines)

# find the start of renderChart
start = None
for i, line in enumerate(lines):
    if "function renderChart(" in line:
        start = i
        break

print("=" * 70)
print(f"FILE        : {os.path.abspath(path)}")
print(f"TOTAL LINES : {n}")
print("=" * 70)

if start is None:
    print("renderChart not found.")
    sys.exit(1)

# print from renderChart until the next top-level `function ` (col 0) after it,
# or 170 lines, whichever comes first
end = min(n, start + 170)
for j in range(start + 1, min(n, start + 170)):
    if lines[j].startswith("function ") and j > start + 2:
        end = j
        break

print(f"\n----- renderChart  (lines {start + 1}-{end}) -----")
for j in range(start, end):
    print(f"{j + 1:5d}  {lines[j].rstrip()}")

print("\n=== END ===")
