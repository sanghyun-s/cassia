#!/usr/bin/env python3
"""
PATCH: ROUTER TABLE-AWARENESS  (backend/routers/query_router.py)

Problem
-------
The router is PDF-aware (it biases data questions toward RAG when a PDF is in
the session) but it is NOT aware of uploaded DATA TABLES. So with a PDF present,
"show the Q1 forecast from the file I uploaded" routes to RAG -> "not found in
docs", even though the forecast table is fully queryable once it reaches SQL.

Fix (contained to query_router.py)
-----------------------------------
1. Add _get_session_table_names() — mirrors the existing PDF helper but pulls
   table names for uploads with target=='sql'.
2. route_with_llm() also lists those tables in the prompt and tells the
   classifier: show/plot/compare a forecast/table from an uploaded file -> 'sql'.
   Explicit precedence: a PDF's narrative/policy stays 'rag'; tabular/forecast
   questions go 'sql'.
3. classify_question() fetches the table names and passes them through.

Safety: backs up the file, requires each anchor to be unique, is idempotent
(re-running is a no-op), syntax-checks the result, and auto-restores on any
failure. Modifies only this one file. Reversible via the printed .bak path.

Run from the app2 project root:
    python3 apply_router_table_awareness.py
"""
import os
import sys
import time
import shutil
import py_compile

SENTINEL = "_get_session_table_names"

CANDIDATES = [
    "backend/routers/query_router.py",
    "routers/query_router.py",
    "query_router.py",
]

# ── Edit 1: add the table-name helper right after the PDF helper ──
OLD_1 = (
    "    except Exception as e:\n"
    '        print(f"[query_router] could not fetch session uploads: {e}")\n'
    "        return []\n"
)
NEW_1 = OLD_1 + (
    "\n\n"
    "def _get_session_table_names(session_id: str) -> list:\n"
    '    """Return names of queryable uploaded TABLES in this session (target=\'sql\').\n'
    "\n"
    "    Mirrors _get_session_pdf_filenames so the router knows there is\n"
    "    structured uploaded data to query, not only PDF documents.\n"
    '    """\n'
    "    if not session_id:\n"
    "        return []\n"
    "    try:\n"
    "        from db.session_store import list_uploads\n"
    "        uploads = list_uploads(session_id)\n"
    "        names = []\n"
    "        for u in uploads:\n"
    '            if u.get("target") == "sql":\n'
    '                names.extend(u.get("table_names") or [])\n'
    "        return names\n"
    "    except Exception as e:\n"
    '        print(f"[query_router] could not fetch session tables: {e}")\n'
    "        return []\n"
)

# ── Edit 2: route_with_llm signature — add table_names param ──
OLD_2 = (
    "def route_with_llm(question: str, llm: ChatOpenAI, history: str = \"\",\n"
    "                   pdf_filenames: list = None) -> RouteDecision:"
)
NEW_2 = (
    "def route_with_llm(question: str, llm: ChatOpenAI, history: str = \"\",\n"
    "                   pdf_filenames: list = None,\n"
    "                   table_names: list = None) -> RouteDecision:"
)

# ── Edit 3: uploads_block — append the data-table clause ──
OLD_3 = (
    "    uploads_block = \"\"\n"
    "    if pdf_filenames:\n"
    "        files_str = \", \".join(pdf_filenames)\n"
    "        uploads_block = (\n"
    "            f\"IMPORTANT — this session has uploaded PDF document(s): {files_str}.\\n\"\n"
    "            f\"Questions that could be answered by those documents should be \"\n"
    "            f\"classified as 'rag' or 'both', EVEN IF they mention numbers, totals, \"\n"
    "            f\"or amounts. A question about figures inside an uploaded PDF is still 'rag'.\\n\\n\"\n"
    "        )\n"
)
NEW_3 = (
    "    uploads_block = \"\"\n"
    "    if pdf_filenames:\n"
    "        files_str = \", \".join(pdf_filenames)\n"
    "        uploads_block += (\n"
    "            f\"IMPORTANT — this session has uploaded PDF document(s): {files_str}.\\n\"\n"
    "            f\"Questions that could be answered by those documents should be \"\n"
    "            f\"classified as 'rag' or 'both', EVEN IF they mention numbers, totals, \"\n"
    "            f\"or amounts. A question about figures inside an uploaded PDF is still 'rag'.\\n\\n\"\n"
    "        )\n"
    "    if table_names:\n"
    "        tables_str = \", \".join(table_names)\n"
    "        uploads_block += (\n"
    "            f\"IMPORTANT — this session also has uploaded DATA TABLE(s), queryable \"\n"
    "            f\"as structured data: {tables_str}.\\n\"\n"
    "            f\"A request to show, list, plot, chart, or compare rows, figures, \"\n"
    "            f\"amounts, or a forecast/projection FROM an uploaded file, spreadsheet, \"\n"
    "            f\"or CSV is 'sql' (or 'both' if it also needs policy/PDF context).\\n\"\n"
    "            f\"PRECEDENCE when both a PDF and a data table are uploaded: a question \"\n"
    "            f\"about a document's narrative, policy, or wording is 'rag'; a question \"\n"
    "            f\"that shows, plots, or compares tabular figures or a forecast is 'sql'.\\n\\n\"\n"
    "        )\n"
)

# ── Edit 4: classify_question — fetch table names and pass them through ──
OLD_4 = (
    "    pdf_filenames = _get_session_pdf_filenames(session_id)\n"
    "\n"
    "    if llm:\n"
    "        decision = route_with_llm(question, llm, history=history,\n"
    "                                  pdf_filenames=pdf_filenames)\n"
    "        method = \"llm\"\n"
)
NEW_4 = (
    "    pdf_filenames = _get_session_pdf_filenames(session_id)\n"
    "    table_names   = _get_session_table_names(session_id)\n"
    "\n"
    "    if llm:\n"
    "        decision = route_with_llm(question, llm, history=history,\n"
    "                                  pdf_filenames=pdf_filenames,\n"
    "                                  table_names=table_names)\n"
    "        method = \"llm\"\n"
)

EDITS = [("table-name helper", OLD_1, NEW_1),
         ("route_with_llm signature", OLD_2, NEW_2),
         ("uploads_block table clause", OLD_3, NEW_3),
         ("classify_question wiring", OLD_4, NEW_4)]


def find_target():
    for p in CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def main():
    path = find_target()
    if not path:
        print("ERROR: could not find query_router.py. Run from the app2 project root.")
        sys.exit(1)
    print(f"Target: {path}")

    text = open(path, encoding="utf-8").read()

    if SENTINEL in text:
        print("Already patched (found _get_session_table_names). No changes made.")
        try:
            py_compile.compile(path, doraise=True)
            print("Existing file compiles cleanly. ✓")
        except py_compile.PyCompileError as e:
            print(f"WARNING: existing file does not compile: {e}")
        sys.exit(0)

    # Pre-flight: every anchor must appear exactly once.
    for name, old, _new in EDITS:
        c = text.count(old)
        if c != 1:
            print(f"ERROR: anchor for '{name}' found {c} times (expected 1). Aborting; "
                  f"no changes made.")
            sys.exit(1)
    print("Pre-flight OK — all 4 anchors unique.")

    ts = time.strftime("%Y%m%d-%H%M%S")
    backup = f"{path}.pre-routertables-{ts}.bak"
    shutil.copy2(path, backup)
    print(f"Backup: {backup}")

    patched = text
    for name, old, new in EDITS:
        patched = patched.replace(old, new, 1)
        print(f"  applied: {name}")

    open(path, "w", encoding="utf-8").write(patched)

    try:
        py_compile.compile(path, doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(backup, path)
        print(f"SYNTAX ERROR after patch — restored original from backup.\n{e}")
        sys.exit(1)

    if SENTINEL not in open(path, encoding="utf-8").read():
        shutil.copy2(backup, path)
        print("Verification failed (sentinel missing) — restored original.")
        sys.exit(1)

    print("\nSUCCESS ✓  Router is now table-aware.")
    print("  • data/forecast questions on uploaded CSVs route to SQL")
    print("  • document/policy questions still route to RAG")
    print(f"\nRevert anytime with:\n  cp \"{backup}\" \"{path}\"")
    print("Then restart the server (python3 backend/main.py) to load the change.")


if __name__ == "__main__":
    main()
