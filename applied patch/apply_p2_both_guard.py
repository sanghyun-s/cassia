#!/usr/bin/env python3
"""
Stabilization v2 — Priority 2: BOTH-route SQL-unusable guard.

Modifies the BOTH-route synthesis block in backend/main.py to detect
unusable SQL results (canned stubs + execution errors) and shield the
synthesizer from them.

Background
----------
The original BOTH synthesis prompt unconditionally passed the
sql_result "answer" text to the synthesizer LLM. When that text was a
canned stub ("No uploaded data...") or an execution error ("only one
SQL statement can be executed", "no such column: status", "SELECTs to
the left and right of UNION..."), the synthesizer faithfully repeated
it in the final answer — producing apologetic technical-error language
in client-facing responses. Phase 6 Sims 2, 4, 5, and 8 all exhibited
variants of this.

Post-patch behavior
-------------------
The BOTH branch now detects 11 patterns of unusable SQL output and
switches to a RAG-only synthesis prompt with explicit instructions:
  - do not claim "there is no uploaded data"
  - do not quote technical SQL error text
  - either answer from policy content if sufficient, or briefly note
    that structured data wasn't retrievable and ask the user to
    specify the table, amount, or comparison target

The normal BOTH-route path (when SQL succeeded) is unchanged.
No router changes. No SQL pipeline changes. No RAG pipeline changes.

Safety
------
- Backs up main.py with timestamped suffix
- Idempotent (looks for '_sql_unusable_patterns' marker)
- Pattern uniqueness check before write

Run from app2/ project root:
    python3 apply_p2_both_guard.py
"""

import shutil
import sys
from pathlib import Path
from datetime import datetime


PROJECT_ROOT = Path.cwd()
FILE_PATH    = PROJECT_ROOT / "backend" / "main.py"


# ── OLD block (the existing BOTH branch, exactly as in main.py) ────
# Raw string so backslashes in the f-strings stay literal for matching.
OLD_BLOCK = r'''            if route == "both":
                sql_ans = sql_result.get("answer", "")
                rag_ans = rag_result.get("answer", "")
                merge   = llm.invoke(
                    f"Combine these two answers into one clear response:\n\n"
                    f"DATA ANSWER: {sql_ans}\n"
                    f"POLICY ANSWER: {rag_ans}\n\n"
                    f"Write a unified 3-5 sentence answer addressing both numbers and policy context."
                )
                final_answer  = merge.content.strip()
                response_type = "answer"'''


# ── NEW block (with stub/error detection + conditional merge) ──────
NEW_BLOCK = r'''            if route == "both":
                sql_ans = sql_result.get("answer", "")
                rag_ans = rag_result.get("answer", "")

                # v2 stabilization: detect SQL stubs/errors so they're
                # not passed to the synthesizer as evidence
                _sql_lower = str(sql_ans).lower()
                _sql_unusable_patterns = (
                    "no uploaded data",
                    "this data is not in the uploaded files",
                    "this data isn't in the demo tables",
                    "execution failed",
                    "only one sql statement",
                    "no such column",
                    "no such table",
                    "selects to the left and right of union",
                    "syntax error",
                    "the query execution failed",
                    "the query could not be executed",
                )
                sql_unusable = (
                    not sql_ans
                    or any(p in _sql_lower for p in _sql_unusable_patterns)
                )

                if sql_unusable:
                    # SQL portion failed or returned a stub — synthesize
                    # from RAG alone with explicit instruction not to leak
                    # technical error text or claim no data exists
                    merge = llm.invoke(
                        f"Answer the user's question below using only the "
                        f"policy/guidance content provided. The structured-"
                        f"data retrieval for this question failed or returned "
                        f"no usable result. Do NOT claim 'there is no uploaded "
                        f"data' or quote any technical SQL error text — just "
                        f"answer from the policy content if it's sufficient, "
                        f"or briefly acknowledge you couldn't form a reliable "
                        f"data query and ask the user to specify the table, "
                        f"amount, or comparison target.\n\n"
                        f"Question: {question}\n\n"
                        f"POLICY ANSWER: {rag_ans}\n\n"
                        f"Write a unified 3-5 sentence answer."
                    )
                else:
                    merge = llm.invoke(
                        f"Combine these two answers into one clear response:\n\n"
                        f"DATA ANSWER: {sql_ans}\n"
                        f"POLICY ANSWER: {rag_ans}\n\n"
                        f"Write a unified 3-5 sentence answer addressing both numbers and policy context."
                    )
                final_answer  = merge.content.strip()
                response_type = "answer"'''


def backup(path: Path) -> Path:
    ts  = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    bak = path.with_suffix(path.suffix + f".pre-p2-both-{ts}.bak")
    shutil.copy2(str(path), str(bak))
    return bak


def main():
    print("=" * 72)
    print("  Stabilization v2 — Priority 2: BOTH-route SQL-unusable guard")
    print("=" * 72)
    print()
    print(f"File: {FILE_PATH}")
    print()

    if not FILE_PATH.exists():
        print(f"✗ File not found at {FILE_PATH}")
        print("  Run this from the app2/ project root.")
        return 1

    text = FILE_PATH.read_text()

    # Idempotence
    if "_sql_unusable_patterns" in text:
        print("  ✓ Already patched (_sql_unusable_patterns marker present).")
        return 0

    # Pre-flight pattern check
    if OLD_BLOCK not in text:
        print("  ⚠ Expected BOTH-route synthesis block not found.")
        print("    main.py may have been edited since the locator ran.")
        print()
        print("    First 3 lines of the expected block:")
        for line in OLD_BLOCK.split("\n")[:3]:
            print(f"      {line[:90]}")
        return 1

    if text.count(OLD_BLOCK) > 1:
        print("  ⚠ BOTH-route block found multiple times (ambiguous).")
        print("    Manual inspection needed.")
        return 1

    # Back up
    bak = backup(FILE_PATH)
    print(f"Backed up to: {bak.name}")
    print()

    # Apply
    new_text = text.replace(OLD_BLOCK, NEW_BLOCK, 1)
    FILE_PATH.write_text(new_text)
    print("  ✓ Replaced BOTH-route synthesis block with guarded version")
    print("  ✓ Added stub/error pattern detection (11 patterns)")
    print("  ✓ Added conditional RAG-only synthesis path for unusable SQL")
    print()
    print("Applied successfully.")
    print()
    print("Verification — run these in order:")
    print()
    print("  1. Syntax check:")
    print("       python3 -m py_compile backend/main.py")
    print()
    print("  2. Restart server:")
    print("       lsof -ti:8002 | xargs kill -9 2>/dev/null ; true")
    print("       python3 backend/main.py")
    print()
    print("  3. Test the four failure modes from Phase 6:")
    print()
    print("     a) Sim 2 P3 mode — synthesis question that triggered stub:")
    print("        In a session with general_ledger.csv uploaded, ask:")
    print('          "Show payroll GL entries"')
    print('          "What does IRS Pub 15 say about deposit schedules?"')
    print('          "Based on the books and the IRS rules, what looks')
    print('           wrong or missing in our payroll tax tracking?"')
    print("        → expect: NO 'no uploaded data' language in the final answer")
    print()
    print("     b) Sim 4 P2 mode — UNION/column mismatch:")
    print('          "Find Oracle Corporation invoices or payments in our')
    print('           accounting data — invoice dates, due dates, status"')
    print("        → expect: NO 'no such column' or 'UNION' error text")
    print("          reaches the user. Either a graceful fallback or a")
    print("          request to specify which table to check.")
    print()
    print("     c) Sim 5/8 mode — multi-statement SQL:")
    print('          "Combine the AR collection note, payroll exposure, and')
    print('           Oracle vendor finding into a short client update"')
    print("        → expect: NO 'only one SQL statement' language reaches")
    print("          the user.")
    print()
    print("     d) Regression — normal BOTH route (must still work):")
    print('          "What overdue receivables do we have and what does')
    print('           the IRS say about documenting bad debts?"')
    print("        → expect: existing good behavior preserved — both data")
    print("          and policy content woven into a single answer.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
