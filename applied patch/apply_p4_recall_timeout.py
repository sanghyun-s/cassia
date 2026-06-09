#!/usr/bin/env python3
"""
Stabilization v2 — Priority 4: Core Recall timeout wrap.

Wraps the run_core_recall_pipeline call at the Core Recall route in
backend/main.py with a 30-second hard timeout (via
concurrent.futures.ThreadPoolExecutor). On timeout or unexpected
error, returns a controlled user-visible message instead of letting
the request hang.

Background
----------
Phase 6 Sim 3 P3 ("Recall what I saved about Q1 net income") hung for
~5 minutes with no progress indicator and no error. Root cause was
almost certainly the embedding API call inside the recall pipeline
hanging without a client timeout. A retry with reworded prompt
eventually worked, but the hang itself is the UX risk — especially
for Demo Sim 4 which uses three consecutive Core Recall prompts
(P5, P6, P7) in the most important sim of the demo set.

Post-patch behavior
-------------------
- Normal recall completes in ~1-2 seconds (no behavior change)
- If recall takes >30 seconds:
    "Searching your saved work is taking longer than expected.
     Please try rephrasing your question, or try again in a moment."
- If any other exception fires inside the recall:
    "I couldn't search your saved work right now.
     Please try again in a moment."
- matched=True on both fallbacks means the message becomes the final
  answer (instead of falling through to a fresh live pipeline that
  could ALSO be slow)

Safety
------
- Backs up main.py with timestamped suffix
- Idempotent (looks for the "_cf.TimeoutError" marker)
- Pattern uniqueness check
- Inline at the call site; no module-level state, no new imports
  outside the recall handler (concurrent.futures is stdlib)

Run from app2/ project root:
    python3 apply_p4_recall_timeout.py
"""

import shutil
import sys
from pathlib import Path
from datetime import datetime


PROJECT_ROOT = Path.cwd()
FILE_PATH    = PROJECT_ROOT / "backend" / "main.py"


OLD_BLOCK = '''        if route == "core_recall":
            core_attempted = True
            core_result    = run_core_recall_pipeline(
                question, llm, user_id=current_user.user_id
            )'''


NEW_BLOCK = '''        if route == "core_recall":
            core_attempted = True

            # v2 stabilization: hard timeout on Core Recall to prevent
            # hangs like Sim 3's 5-minute embedding wait. On timeout or
            # unexpected error, return a controlled user-visible message
            # (matched=True so the message becomes the final answer).
            import concurrent.futures as _cf
            try:
                with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
                    _future = _ex.submit(
                        run_core_recall_pipeline, question, llm,
                        user_id=current_user.user_id,
                    )
                    core_result = _future.result(timeout=30.0)
            except _cf.TimeoutError:
                print("[core_recall] timeout after 30s — returning fallback")
                core_result = {
                    "pipeline":      "core_recall",
                    "response_type": "answer",
                    "matched":       True,
                    "answer":        (
                        "Searching your saved work is taking longer than "
                        "expected. Please try rephrasing your question, or "
                        "try again in a moment."
                    ),
                    "sources":    [],
                    "chart_hint": "none",
                    "sql":        None,
                    "raw_data":   [],
                    "columns":    [],
                }
            except Exception as _e:
                print(f"[core_recall] error: {_e}")
                core_result = {
                    "pipeline":      "core_recall",
                    "response_type": "answer",
                    "matched":       True,
                    "answer":        (
                        "I couldn't search your saved work right now. "
                        "Please try again in a moment."
                    ),
                    "sources":    [],
                    "chart_hint": "none",
                    "sql":        None,
                    "raw_data":   [],
                    "columns":    [],
                }'''


def backup(path: Path) -> Path:
    ts  = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    bak = path.with_suffix(path.suffix + f".pre-p4-recall-{ts}.bak")
    shutil.copy2(str(path), str(bak))
    return bak


def main():
    print("=" * 72)
    print("  Stabilization v2 — Priority 4: Core Recall timeout wrap")
    print("=" * 72)
    print()
    print(f"File: {FILE_PATH}")
    print()

    if not FILE_PATH.exists():
        print(f"file not found at {FILE_PATH}")
        return 1

    text = FILE_PATH.read_text()

    # Idempotence
    if "_cf.TimeoutError" in text and "concurrent.futures as _cf" in text:
        print("  Already patched (timeout wrap markers present).")
        return 0

    # Pre-flight pattern check
    if OLD_BLOCK not in text:
        print("  Expected Core Recall call site not found.")
        print("  main.py may have been edited since the locator ran.")
        print()
        print("  Expected first few lines of the block:")
        for line in OLD_BLOCK.split("\n")[:5]:
            print(f"      {line[:90]}")
        return 1

    if text.count(OLD_BLOCK) > 1:
        print("  Core Recall call site found multiple times (ambiguous).")
        return 1

    # Back up
    bak = backup(FILE_PATH)
    print(f"Backed up to: {bak.name}")
    print()

    # Apply
    new_text = text.replace(OLD_BLOCK, NEW_BLOCK, 1)
    FILE_PATH.write_text(new_text)
    print("  Wrapped Core Recall call with 30s hard timeout")
    print("  Added inline fallback for timeout + unexpected errors")
    print()
    print("Applied successfully.")
    print()
    print("Verification:")
    print()
    print("  1. Syntax check (must pass before restart):")
    print("       python3 -m py_compile backend/main.py")
    print()
    print("  2. Restart server:")
    print("       lsof -ti:8002 | xargs kill -9 2>/dev/null ; true")
    print("       python3 backend/main.py")
    print()
    print("  3. Verify normal Core Recall still works:")
    print("       Run any normal recall, like:")
    print("         Recall what I saved about overdue AR")
    print("       Expected: normal answer in ~1-2 seconds, no change in UI")
    print()
    print("  4. Optional - timeout sanity check:")
    print("       Temporarily edit timeout=30.0 to timeout=0.1 in main.py,")
    print("       restart, run a recall query. Expected: the 'taking longer")
    print("       than expected' message. Restore 30.0 afterward.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
