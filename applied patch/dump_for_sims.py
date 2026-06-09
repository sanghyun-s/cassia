#!/usr/bin/env python3
"""
DUMP FOR SIMS  (read-only — modifies nothing, opens every DB in mode=ro)

Two purposes:
  1. Show the real accounting data (AR / AP / revenue / payroll / GL, etc.)
     so the 7 mock upload files reference customers/vendors/accounts that
     actually exist — otherwise the cross-reference sim prompts fall flat.
  2. Inventory your Core saves so we can identify the junk saves (saved
     error text / stubs) to archive before Sim 4's recall.

Run from the app2 project root:

    python3 dump_for_sims.py

Then paste the ENTIRE output back into the chat.
"""
import os
import sqlite3

ROOT = os.getcwd()
SKIP_DIRS = ("/venv", "/.git", "/__pycache__", "/node_modules", "/chroma_db")

ACCT_KEYWORDS = (
    "receivable", "payable", "revenue", "payroll", "deposit", "invoice",
    "payment", "customer", "vendor", "ledger", "gl", "journal", "account",
    "transaction", "service", "forecast",
)
ROW_CAP = 25


def find_dbs():
    found = []
    for dp, dn, fn in os.walk(ROOT):
        # prune skip dirs in place so os.walk doesn't descend into them
        dn[:] = [d for d in dn
                 if not any(s.strip("/") == d for s in SKIP_DIRS)]
        if any(s in dp for s in SKIP_DIRS):
            continue
        for f in fn:
            if f.endswith(".db"):
                found.append(os.path.join(dp, f))
    return sorted(found)


def ro_connect(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def list_tables(con):
    cur = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    return [r[0] for r in cur.fetchall()]


def cols(con, table):
    cur = con.execute(f'PRAGMA table_info("{table}")')
    return [r[1] for r in cur.fetchall()]


def count(con, table):
    try:
        return con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    except Exception:
        return "?"


def sample(con, table, limit=ROW_CAP):
    try:
        cur = con.execute(f'SELECT * FROM "{table}" LIMIT {limit}')
        names = [d[0] for d in cur.description]
        rows = cur.fetchall()
        return names, rows
    except Exception as e:
        return None, [f"(could not read: {e})"]


def dump_table(con, table, full=False):
    c = cols(con, table)
    n = count(con, table)
    print(f"\n  TABLE: {table}   (rows: {n})")
    print(f"    columns: {', '.join(c)}")
    names, rows = sample(con, table)
    if names is None:
        print(f"    {rows[0]}")
        return
    if not rows:
        print("    (no rows)")
        return
    print(f"    {' | '.join(names)}")
    for r in rows:
        print("    " + " | ".join("" if v is None else str(v) for v in r))


def main():
    dbs = find_dbs()
    print("=" * 70)
    print(f"PROJECT ROOT : {ROOT}")
    print(f"DB FILES FOUND ({len(dbs)}):")
    for d in dbs:
        print(f"  - {os.path.relpath(d, ROOT)}")
    print("=" * 70)

    for path in dbs:
        rel = os.path.relpath(path, ROOT)
        print(f"\n\n########## DB: {rel} ##########")
        try:
            con = ro_connect(path)
        except Exception as e:
            print(f"  (could not open read-only: {e})")
            continue

        tables = list_tables(con)
        print(f"tables ({len(tables)}): {', '.join(tables) if tables else '(none)'}")

        for t in tables:
            tl = t.lower()

            # Core saves: always dump with content preview + archive flag
            if t == "core_saves":
                print("\n  TABLE: core_saves  (CORE INVENTORY — look for junk to archive)")
                try:
                    cur = con.execute(
                        "SELECT save_id, kind, topic_id, title, "
                        "substr(content,1,110), archived_at, created_at "
                        "FROM core_saves ORDER BY created_at"
                    )
                    for sid, kind, tid, title, preview, arch, created in cur.fetchall():
                        flag = "ARCHIVED" if arch else "active"
                        prev = (preview or "").replace("\n", " ")
                        print(f"    [{flag}] {sid} | kind={kind} | topic={tid} | "
                              f"{created}")
                        print(f"        title  : {title}")
                        print(f"        preview: {prev}")
                except Exception as e:
                    print(f"    (could not read core_saves: {e})")
                continue

            if t == "core_topics":
                print("\n  TABLE: core_topics")
                try:
                    for row in con.execute(
                        "SELECT topic_id, name FROM core_topics ORDER BY name"
                    ):
                        print(f"    {row[0]} | {row[1]}")
                except Exception as e:
                    print(f"    (could not read: {e})")
                continue

            # Accounting-relevant tables: full sample
            if any(k in tl for k in ACCT_KEYWORDS):
                dump_table(con, t)
            else:
                # other tables: schema + count only
                print(f"\n  TABLE: {t}   (rows: {count(con, t)})")
                print(f"    columns: {', '.join(cols(con, t))}")

        con.close()

    print("\n\n=== END OF DUMP ===")


if __name__ == "__main__":
    main()
