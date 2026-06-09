#!/usr/bin/env python3
"""
P2b LOCATOR  (read-only — modifies nothing)

Purpose: show the /chat route-dispatch region, the existing P2 BOTH-route
guard, and the SQL-only branch in backend/main.py so the P2b applier can be
written to match your exact code on the first run.

Run from the app2 project root:

    python3 locate_p2b.py

Then paste the ENTIRE output back into the chat.
"""
import os
import sys

# --- locate backend/main.py -------------------------------------------------
CANDIDATES = [
    "backend/main.py",
    "main.py",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend", "main.py"),
]
path = next((p for p in CANDIDATES if os.path.isfile(p)), None)
if not path:
    print("ERROR: could not find backend/main.py.")
    print("Run this from the app2 project root (the folder that contains 'backend/').")
    sys.exit(1)

with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

n = len(lines)
print("=" * 70)
print(f"FILE        : {os.path.abspath(path)}")
print(f"TOTAL LINES : {n}")
print("=" * 70)

# --- compact grep index of strong anchors -----------------------------------
ANCHORS = [
    "_sql_unusable",
    "sql_unusable",
    "unusable",
    '"BOTH"',
    "'BOTH'",
    '"SQL"',
    "'SQL'",
    "ChatResponse(",
    "run_rag_pipeline(",
    "run_text_to_sql",
    "text_to_sql",
    "sql_result",
    "sql_error",
    "RAG-only",
    "rag_only",
]
print("\n----- ANCHOR INDEX (lineno: line) -----")
found_any = False
for i, line in enumerate(lines):
    for a in ANCHORS:
        if a in line:
            print(f"{i + 1:5d}: {line.rstrip()}")
            found_any = True
            break
if not found_any:
    print("(no anchors matched)")

# --- full numbered dump of the routing / synthesis region -------------------
# Handover places: ChatResponse before ~380, core recall ~441,
# BOTH synthesis ~530-578, SQL-only branch ~579. 355-625 covers all of it.
LO = max(0, 355 - 1)
HI = min(n, 625)
print(f"\n----- FULL DUMP: lines {LO + 1}-{HI} -----")
for j in range(LO, HI):
    print(f"{j + 1:5d}  {lines[j].rstrip()}")

# --- any _sql_unusable definitions outside that window ----------------------
print("\n----- _sql_unusable / sql_unusable OCCURRENCES OUTSIDE DUMP (±15) -----")
shown = set()
emitted = False
for i, line in enumerate(lines):
    if ("_sql_unusable" in line or "sql_unusable" in line) and not (LO <= i < HI):
        lo, hi = max(0, i - 15), min(n, i + 16)
        if any(k in shown for k in range(lo, hi)):
            continue
        for j in range(lo, hi):
            print(f"{j + 1:5d}  {lines[j].rstrip()}")
            shown.add(j)
        print()
        emitted = True
if not emitted:
    print("(none outside the dump window)")

print("\n=== END OF LOCATOR OUTPUT ===")
