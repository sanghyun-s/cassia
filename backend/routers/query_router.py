"""
=============================================================
QUERY ROUTER — Classify: SQL / RAG / BOTH / CORE_RECALL
=============================================================

The brain of the hybrid system. Every user question passes
through here first. The router decides:

  → SQL          structured/numeric questions
  → RAG          policy / document questions
  → BOTH         hybrid (numbers + policy)
  → CORE_RECALL  pulls from the user's saved "core" knowledge base
                 (Phase 4d — works even in a brand-new session)

Two strategies available:
  1. LLM-based   (more accurate, costs ~$0.001 per route)
  2. Keyword     (free, instant, less accurate — fallback)

Phase 4 warm-up:
  - classify_question() accepts session_id so the LLM knows about
    uploaded PDFs (biases toward RAG/BOTH).

Phase 4d:
  - Added CORE_RECALL as a fourth route.
  - Trigger-phrase detection runs BEFORE the LLM: explicit phrases like
    "what did I save", "from my core", "recall my…" force core_recall
    deterministically (no LLM call for these).
  - For non-trigger questions, the LLM is told core_recall exists and may
    pick it. main.py wraps the pipeline with a fall-through safety net,
    so a wrong core_recall guess still produces a useful answer.
"""

import os
import re
from enum import Enum
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from dotenv import load_dotenv

load_dotenv()


class RouteDecision(str, Enum):
    SQL = "sql"
    RAG = "rag"
    BOTH = "both"
    CORE_RECALL = "core_recall"   # Phase 4d


# ── Keywords for fast fallback routing ────────────────────
SQL_KEYWORDS = [
    "how much", "total", "sum", "count", "balance", "owe",
    "aging", "overdue", "outstanding", "paid", "revenue",
    "invoice", "vendor", "amount", "january", "february",
    "march", "april", "quarter", "q1", "q2", "q3", "q4",
    "days", "oldest", "highest", "lowest", "average", "avg",
    "expense", "category", "breakdown", "list", "show me",
    "what is our", "what are our", "how many invoices",
]

RAG_KEYWORDS = [
    "what does", "policy", "rule", "regulation", "irs",
    "publication", "withholding", "w-4", "w4", "form",
    "requirement", "how should", "what is the", "define",
    "explain", "tax", "exempt", "supplemental", "wage",
    "deposit schedule", "penalty", "compliance", "filing",
]

# ── Phase 4d: explicit triggers that force core_recall ────
# Conservative on purpose. Each pattern is a phrase a user would only
# plausibly type if they actually mean to query their saved core.
CORE_RECALL_TRIGGERS = [
    r"\bwhat did i save\b",
    r"\bwhat have i saved\b",
    r"\bfrom my (core|saves?|saved|notes?|knowledge base)\b",
    r"\bin my (core|saves?|saved|notes?|knowledge base)\b",
    r"\b(recall|pull up|pull|find|look up) (my|the) saved\b",
    r"\bsaved (answer|answers|item|items|notes?|data)\b",
    r"\b(my|the) (saved|core) (answer|answers|notes?|data|content)\b",
    r"\bdid i save (anything|something)\b",
    r"\bcheck my (core|saves?|saved|knowledge base)\b",
]
_CORE_RECALL_PATTERN = re.compile("|".join(CORE_RECALL_TRIGGERS), re.IGNORECASE)


def _matches_core_recall_trigger(question: str) -> bool:
    """Deterministic trigger detection — runs before any LLM call."""
    return bool(_CORE_RECALL_PATTERN.search(question or ""))


# ── Prompt for LLM-based routing ──────────────────────────
ROUTER_PROMPT = PromptTemplate(
    template="""You are a query classifier for an accounting AI chatbot.

The chatbot has THREE knowledge sources:
1. SQL DATABASE — structured accounting data:
   - accounts_payable, accounts_receivable, revenue, general_ledger
   - balance_sheet, profit_loss, chart_of_accounts (7 tables total)

2. VECTOR DATABASE (RAG) — unstructured documents:
   - IRS Pub 15, Pub 15-T (withholding methods), Pub 15-B (fringe benefits)
   - PLUS any PDF documents the user has uploaded to this session

3. CORE — the user's personal saved knowledge base. The user has previously
   committed specific answers or uploads to their "core" via a Save button.
   These persist across sessions. Pick CORE_RECALL when the user is clearly
   asking about something they saved before — phrases like "what did I
   save", "from my notes", "the answer I saved about X", "recall my…".
   For NORMAL questions about live data or live documents, do NOT pick
   core_recall — they should go to sql / rag / both as usual.

{history_block}{uploads_block}Classify the question below into exactly one of:
- "sql"           → needs exact numbers from the database
- "rag"           → needs explanation from policy documents OR uploaded PDFs
- "both"          → needs data AND policy/document context
- "core_recall"   → user is explicitly asking about their previously-saved content

If the question is a follow-up that refers to prior turns (e.g. "those",
"the first one", "그 중에서", "show me top 3"), classify based on what the
prior turn was about. A follow-up to a SQL result is still "sql".

Question: {question}

Reply with ONLY one word: sql, rag, both, or core_recall""",
    input_variables=["question", "history_block", "uploads_block"],
)


def _get_session_pdf_filenames(session_id: str) -> list:
    """Return list of PDF filenames uploaded to this session (target='rag')."""
    if not session_id:
        return []
    try:
        from db.session_store import list_uploads
        uploads = list_uploads(session_id)
        return [u["filename"] for u in uploads if u.get("target") == "rag"]
    except Exception as e:
        print(f"[query_router] could not fetch session uploads: {e}")
        return []


def _get_session_table_names(session_id: str) -> list:
    """Return names of queryable uploaded TABLES in this session (target='sql').

    Mirrors _get_session_pdf_filenames so the router knows there is
    structured uploaded data to query, not only PDF documents.
    """
    if not session_id:
        return []
    try:
        from db.session_store import list_uploads
        uploads = list_uploads(session_id)
        names = []
        for u in uploads:
            if u.get("target") == "sql":
                names.extend(u.get("table_names") or [])
        return names
    except Exception as e:
        print(f"[query_router] could not fetch session tables: {e}")
        return []


def route_with_keywords(question: str) -> RouteDecision:
    """
    Fast keyword-based routing — no API call needed.
    Used as fallback if LLM routing fails.
    Note: trigger-based core_recall detection happens upstream in
    classify_question(), not here.
    """
    q = question.lower()

    sql_score = sum(1 for kw in SQL_KEYWORDS if kw in q)
    rag_score = sum(1 for kw in RAG_KEYWORDS if kw in q)

    if sql_score > 0 and rag_score > 0:
        return RouteDecision.BOTH
    elif sql_score > rag_score:
        return RouteDecision.SQL
    elif rag_score > sql_score:
        return RouteDecision.RAG
    else:
        # Default to SQL for accounting chatbot context
        return RouteDecision.SQL


def route_with_llm(question: str, llm: ChatOpenAI, history: str = "",
                   pdf_filenames: list = None,
                   table_names: list = None) -> RouteDecision:
    """
    LLM-based routing — more accurate, understands context.
    Primary routing strategy.
    """
    history_block = ""
    if history:
        history_block = f"PRIOR CONVERSATION (most recent last):\n{history}\n\n"

    uploads_block = ""
    if pdf_filenames:
        files_str = ", ".join(pdf_filenames)
        uploads_block += (
            f"IMPORTANT — this session has uploaded PDF document(s): {files_str}.\n"
            f"Questions that could be answered by those documents should be "
            f"classified as 'rag' or 'both', EVEN IF they mention numbers, totals, "
            f"or amounts. A question about figures inside an uploaded PDF is still 'rag'.\n\n"
        )
    if table_names:
        tables_str = ", ".join(table_names)
        uploads_block += (
            f"IMPORTANT — this session also has uploaded DATA TABLE(s), queryable "
            f"as structured data: {tables_str}.\n"
            f"A request to show, list, plot, chart, or compare rows, figures, "
            f"amounts, or a forecast/projection FROM an uploaded file, spreadsheet, "
            f"or CSV is 'sql' (or 'both' if it also needs policy/PDF context).\n"
            f"PRECEDENCE when both a PDF and a data table are uploaded: a question "
            f"about a document's narrative, policy, or wording is 'rag'; a question "
            f"that shows, plots, or compares tabular figures or a forecast is 'sql'.\n\n"
        )

    prompt = ROUTER_PROMPT.format(
        question=question,
        history_block=history_block,
        uploads_block=uploads_block,
    )
    response = llm.invoke(prompt)
    decision = response.content.strip().lower()

    # Parse response — handle any LLM verbosity. Order matters: check
    # core_recall before "rag" so "core_recall" doesn't get partial-matched.
    if "core_recall" in decision or "core recall" in decision:
        return RouteDecision.CORE_RECALL
    elif "both" in decision:
        return RouteDecision.BOTH
    elif "rag" in decision:
        return RouteDecision.RAG
    elif "sql" in decision:
        return RouteDecision.SQL
    else:
        # Fallback to keyword if LLM gives unexpected output
        return route_with_keywords(question)


def classify_question(question: str, llm: ChatOpenAI = None, history: str = "",
                      session_id: str = None) -> dict:
    """
    Main routing function called by FastAPI.
    Returns route decision + explanation for transparency.

    Phase 4d routing order:
      1. Explicit trigger phrases → core_recall (deterministic, no LLM call).
      2. Otherwise, LLM picks among sql / rag / both / core_recall (with the
         session's uploaded PDFs as context).
      3. If LLM unavailable → keyword fallback (sql / rag / both only).

    Args:
        question:   The user's current question
        llm:        ChatOpenAI instance (if None, falls back to keyword routing)
        history:    Formatted prior conversation context (last N turns).
        session_id: Current session — used to detect uploaded PDFs and bias
                    routing toward RAG when the question may target them.
    """
    # Step 1: trigger phrases — deterministic, takes precedence
    if _matches_core_recall_trigger(question):
        return {
            "route": RouteDecision.CORE_RECALL,
            "method": "trigger",
            "explanation": "Question explicitly references your saved core.",
        }

    pdf_filenames = _get_session_pdf_filenames(session_id)
    table_names   = _get_session_table_names(session_id)

    if llm:
        decision = route_with_llm(question, llm, history=history,
                                  pdf_filenames=pdf_filenames,
                                  table_names=table_names)
        method = "llm"
    else:
        decision = route_with_keywords(question)
        method = "keyword"

    explanations = {
        RouteDecision.SQL: "Question asks for specific numbers, amounts, or data from accounting records.",
        RouteDecision.RAG: "Question asks about policies, regulations, or document content.",
        RouteDecision.BOTH: "Question requires both financial data and policy context.",
        RouteDecision.CORE_RECALL: "Question seems to ask about previously-saved core content.",
    }

    return {
        "route": decision,
        "method": method,
        "explanation": explanations[decision],
    }
