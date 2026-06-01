"""
=============================================================
backfill_session_titles.py — one-shot title fix for old sessions
=============================================================

Scans every session for ones whose title looks AUTO-set (literal "New Chat",
or the truncated first-user-question pattern from earlier behavior), and
regenerates a clean, language-matched LLM title for each.

Skips:
  - Sessions whose title was clearly user-edited (doesn't match either
    auto-pattern).
  - Sessions with no user messages (can't summarize them).

Usage (FROM the app2 root):
    cd "/path/to/app2"
    source venv/bin/activate

    python3 backend/scripts/backfill_session_titles.py            # dry-run (default)
    python3 backend/scripts/backfill_session_titles.py --apply    # actually update

Dry-run prints exactly which sessions are candidates and what would change,
without writing anything. Re-run with --apply once you're satisfied.

Idempotent: re-running with --apply on an already-clean DB does nothing
(no candidates means no LLM calls).
"""

import os
import sys
import argparse
from pathlib import Path

# Make /backend importable when running this script directly
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # → /app2/backend

from dotenv import load_dotenv
load_dotenv()

from langchain_openai import ChatOpenAI

from db.session_store import (
    get_all_sessions,
    get_session_messages,
    update_session_title,
)


# Same prompt the live /chat endpoint uses, kept in sync intentionally.
TITLE_GEN_PROMPT = (
    "Generate a brief, descriptive title for this accounting chat conversation.\n"
    "Rules:\n"
    "- 3 to 6 words\n"
    "- Use the SAME language as the user's question (English or Korean)\n"
    "- Capture the topic, not the user's exact phrasing\n"
    "- No quotation marks, no trailing punctuation\n"
    "- Examples: Q1 2026 Net Income, Revenue by Service Line, "
    "IRS Late Deposit Penalty, 직원 급여 원천징수, AR Aging Over 60 Days\n\n"
    "User question: {question}\n"
    "Assistant answer (first 300 chars): {answer_preview}\n\n"
    "Title:"
)


def _looks_auto_set(title: str, first_user_msg: str) -> bool:
    """
    Heuristic for "this title was auto-generated, not user-edited."
    True if:
      - empty / missing
      - literal "New Chat" (the POST /sessions default)
      - exactly the first user message truncated to 80 chars
        (the pre-v2.9.1 auto behavior)
    """
    if not title:
        return True
    if title == "New Chat":
        return True
    if first_user_msg and title == first_user_msg[:80]:
        return True
    return False


def _generate_title(llm: ChatOpenAI, question: str, answer: str) -> str | None:
    """Run the LLM and sanitize. Returns None on any failure or unusable output."""
    try:
        prompt = TITLE_GEN_PROMPT.format(
            question=question[:500],
            answer_preview=(answer or "")[:300],
        )
        resp = llm.invoke(prompt)
        title = (resp.content or "").strip().strip('"\'`').strip().rstrip(".!?,;: ")
        if not title or len(title) > 80:
            return None
        return title
    except Exception as e:
        print(f"  ✗ LLM call failed: {e}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Actually update titles (default: dry-run only)")
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        print("❌ OPENAI_API_KEY not set in .env")
        return 1

    sessions = get_all_sessions()
    print(f"Scanning {len(sessions)} session(s)…\n")

    candidates = []           # list of (session_dict, first_user_msg, first_asst_msg)
    skipped_user_edited = 0
    skipped_no_user_msg = 0

    for s in sessions:
        sid   = s["session_id"]
        title = s.get("title") or ""
        try:
            msgs = get_session_messages(sid)
        except Exception as e:
            print(f"  ✗ {sid[:8]}  (could not read messages: {e})")
            continue

        first_user = next((m for m in msgs if m.get("role") == "user"), None)
        first_asst = next((m for m in msgs if m.get("role") == "assistant"), None)

        if not first_user:
            skipped_no_user_msg += 1
            continue

        user_content = first_user.get("content", "")
        if not _looks_auto_set(title, user_content):
            skipped_user_edited += 1
            continue

        candidates.append((
            s,
            user_content,
            first_asst.get("content", "") if first_asst else "",
        ))
        print(f"  ✓ {sid[:8]}  '{title[:60]}'  → candidate")

    print(f"\nSummary:")
    print(f"  candidates:           {len(candidates)}")
    print(f"  skipped (user-edit):  {skipped_user_edited}")
    print(f"  skipped (no message): {skipped_no_user_msg}")
    print(f"  total scanned:        {len(sessions)}\n")

    if not candidates:
        print("Nothing to do.")
        return 0

    if not args.apply:
        print("(Dry-run. Re-run with --apply to update these titles.)")
        return 0

    print("Generating titles via LLM…\n")
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
    )

    ok, fail = 0, 0
    for sess, user_msg, asst_msg in candidates:
        sid = sess["session_id"]
        new_title = _generate_title(llm, user_msg, asst_msg)
        if not new_title:
            print(f"  ✗ {sid[:8]}  (LLM returned nothing usable)")
            fail += 1
            continue
        try:
            update_session_title(sid, new_title)
            old = (sess.get("title") or "")[:50]
            print(f"  ✓ {sid[:8]}  '{old}' → '{new_title}'")
            ok += 1
        except Exception as e:
            print(f"  ✗ {sid[:8]}  update failed: {e}")
            fail += 1

    print(f"\nDone. {ok} retitled, {fail} failed.")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
