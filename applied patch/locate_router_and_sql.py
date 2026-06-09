#!/usr/bin/env python3
"""
ARCHITECTURE LOCATOR  (read-only — modifies nothing)

Maps two things so we can fix them surgically:
  (1) why a data query on an uploaded CSV gets routed to RAG ("not found in docs")
  (2) why an actual-vs-forecast comparison fails as a cross-database query

It lists the Python files, then greps a curated set of high-signal terms
(router decisions, SQL prompt/schema assembly, upload-DB attach) and prints
file:line:content for each match.

Run from the app2 project root:

    python3 locate_router_and_sql.py

Then paste the ENTIRE output back.
"""
import os
import re

ROOT = os.getcwd()
SKIP = ("/venv", "/.git", "/__pycache__", "/node_modules", "/chroma_db", "/outputs", "/demo_uploads")

# curated, high-signal terms grouped by concern
GROUPS = {
    "ROUTER / route decision": [
        "CORE_RECALL", "core_recall", "route ==", "route =", "== 'sql'", '== "sql"',
        "== 'rag'", '== "rag"', "== 'both'", '== "both"', "classify", "router",
        "def route", "intent", "RAG", "decide",
    ],
    "UPLOAD TABLE / CROSS-DB ATTACH": [
        "ATTACH", "user_data", "session_db", "session.db", "sessions/", "to_sql",
        "register", "uploaded", "PRAGMA table_info", "CREATE TABLE",
    ],
    "SQL PROMPT / SCHEMA TEXT": [
        "generate_sql", "text_to_sql", "text-to-sql", "schema", "SCHEMA",
        "system_prompt", "SYSTEM_PROMPT", "You are", "schema_str", "table_schema",
    ],
}

PER_FILE_CAP = 35  # lines per file per group


def py_files():
    out = []
    for dp, dn, fn in os.walk(ROOT):
        if any(s in (dp + "/") for s in SKIP):
            dn[:] = []
            continue
        for f in fn:
            if f.endswith(".py"):
                full = os.path.join(dp, f)
                if os.path.abspath(full) == os.path.abspath(__file__):
                    continue  # skip this locator script itself
                out.append(full)
    return sorted(out)


def main():
    files = py_files()
    print("=" * 72)
    print(f"ROOT: {ROOT}")
    print(f"PYTHON FILES ({len(files)}):")
    for f in files:
        print("  " + os.path.relpath(f, ROOT))
    print("=" * 72)

    # cache file contents
    contents = {}
    for f in files:
        try:
            contents[f] = open(f, encoding="utf-8", errors="replace").read().splitlines()
        except Exception as e:
            contents[f] = [f"(could not read: {e})"]

    for group, terms in GROUPS.items():
        rx = re.compile("|".join(re.escape(t) for t in terms))
        print(f"\n\n########################## {group} ##########################")
        for f in files:
            lines = contents[f]
            hits = [(i + 1, ln.rstrip()) for i, ln in enumerate(lines) if rx.search(ln)]
            if not hits:
                continue
            rel = os.path.relpath(f, ROOT)
            print(f"\n--- {rel}  ({len(hits)} hit(s)) ---")
            for ln_no, ln in hits[:PER_FILE_CAP]:
                s = ln.strip()
                print(f"{ln_no:5d}: {s[:150]}")
            if len(hits) > PER_FILE_CAP:
                print(f"   ... (+{len(hits) - PER_FILE_CAP} more in this file)")

    print("\n=== END ===")


if __name__ == "__main__":
    main()
