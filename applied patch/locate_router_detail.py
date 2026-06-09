#!/usr/bin/env python3
"""
ROUTER-PATCH LOCATOR  (read-only — modifies nothing)

Dumps the exact code needed to make the query router aware of uploaded data
TABLES, so a data/forecast question on an uploaded CSV routes to SQL instead of
RAG when a PDF is also present in the session.

Run from the app2 project root:

    python3 locate_router_detail.py

Then paste the ENTIRE output back.
"""
import os


def find_base():
    for cand in ("backend", "."):
        if os.path.isdir(os.path.join(cand, "routers")):
            return cand
    return "backend"


def dump(path, start=None, end=None, label=None):
    if not os.path.isfile(path):
        print(f"\n\n##### MISSING: {path} #####")
        return
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    n = len(lines)
    a = 1 if start is None else max(1, start)
    b = n if end is None else min(n, end)
    print(f"\n\n################## {label or path}  (lines {a}-{b} of {n}) ##################")
    for i in range(a, b + 1):
        print(f"{i:5d}: {lines[i - 1].rstrip()}")


def main():
    base = find_base()
    print("=" * 72)
    print(f"BASE: {os.path.abspath(base)}")
    print("=" * 72)

    # 1) the patch target — full router
    dump(os.path.join(base, "routers", "query_router.py"), label="query_router.py (FULL)")

    # 2) how uploads are listed (need the dict shape: target / filename / table_names)
    dump(os.path.join(base, "db", "session_store.py"), 480, 530,
         "session_store.py (uploads-listing region)")

    # 3) reference: confirm SQL pipeline already attaches + schemas uploaded tables
    dump(os.path.join(base, "pipelines", "sql_pipeline.py"), 282, 380,
         "sql_pipeline.py (user-tables schema + run assembly)")

    print("\n=== END ===")


if __name__ == "__main__":
    main()
