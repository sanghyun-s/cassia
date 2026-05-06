"""
=============================================================
QUERY ROUTER — Classify: RAG vs Text-to-SQL
=============================================================

The brain of the hybrid system. Every user question passes
through here first. The router decides:

  → SQL   for structured/numeric questions
          "How much do we owe Oracle?"
          "What's AP aging over 60 days?"
          "Total revenue Jan–Mar 2026?"

  → RAG   for document/policy questions
          "What's the withholding rule for bonuses?"
          "How should we handle W-4 exempt claims?"
          "What does Publication 15 say about tips?"

  → BOTH  for hybrid questions
          "What's our overdue balance and what's the IRS
           late payment penalty?"

Two strategies available:
  1. LLM-based   (more accurate, costs ~$0.001 per route)
  2. Keyword     (free, instant, less accurate — fallback)
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


# ── Prompt for LLM-based routing ──────────────────────────
ROUTER_PROMPT = PromptTemplate(
    template="""You are a query classifier for an accounting AI chatbot.

The chatbot has two data sources:
1. SQL DATABASE — structured accounting data:
   - accounts_payable, accounts_receivable, revenue, general_ledger
   - balance_sheet, profit_loss, chart_of_accounts (7 tables total)

2. VECTOR DATABASE (RAG) — unstructured documents:
   - IRS Pub 15, Pub 15-T (withholding methods), Pub 15-B (fringe benefits)

{history_block}Classify the question below into exactly one of:
- "sql"  → needs exact numbers from the database
- "rag"  → needs explanation from policy documents
- "both" → needs data AND policy context

If the question is a follow-up that refers to prior turns (e.g. "those",
"the first one", "그 중에서", "show me top 3"), classify based on what the
prior turn was about. A follow-up to a SQL result is still "sql".

Question: {question}

Reply with ONLY one word: sql, rag, or both""",
    input_variables=["question", "history_block"],
)


def route_with_keywords(question: str) -> RouteDecision:
    """
    Fast keyword-based routing — no API call needed.
    Used as fallback if LLM routing fails.
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


def route_with_llm(question: str, llm: ChatOpenAI, history: str = "") -> RouteDecision:
    """
    LLM-based routing — more accurate, understands context.
    Primary routing strategy.

    If `history` is non-empty, it's injected into the prompt so the
    classifier can resolve follow-up references like "those" or "the top 3".
    """
    history_block = ""
    if history:
        history_block = f"PRIOR CONVERSATION (most recent last):\n{history}\n\n"

    prompt = ROUTER_PROMPT.format(question=question, history_block=history_block)
    response = llm.invoke(prompt)
    decision = response.content.strip().lower()

    # Parse response — handle any LLM verbosity
    if "both" in decision:
        return RouteDecision.BOTH
    elif "rag" in decision:
        return RouteDecision.RAG
    elif "sql" in decision:
        return RouteDecision.SQL
    else:
        # Fallback to keyword if LLM gives unexpected output
        return route_with_keywords(question)


def classify_question(question: str, llm: ChatOpenAI = None, history: str = "") -> dict:
    """
    Main routing function called by FastAPI.
    Returns route decision + explanation for transparency.

    Args:
        question: The user's current question
        llm: ChatOpenAI instance (if None, falls back to keyword routing)
        history: Formatted prior conversation context (last N turns).
                 Empty string for first turn or when memory is disabled.
    """
    if llm:
        decision = route_with_llm(question, llm, history=history)
        method = "llm"
    else:
        decision = route_with_keywords(question)
        method = "keyword"

    explanations = {
        RouteDecision.SQL: "Question asks for specific numbers, amounts, or data from accounting records.",
        RouteDecision.RAG: "Question asks about policies, regulations, or document content.",
        RouteDecision.BOTH: "Question requires both financial data and policy context.",
    }

    return {
        "route": decision,
        "method": method,
        "explanation": explanations[decision],
    }