"""
=============================================================
CORE RECALL PIPELINE — query the user's saved core (Phase 4d)
=============================================================

Given a question, this pipeline:
  1. Embeds the question via core_embed.embed_text
  2. Loads every active core_save with an embedding for the current user
  3. Scores each save by cosine similarity against the question
  4. Keeps saves above SIMILARITY_THRESHOLD
  5. If anything qualifies → asks the LLM to compose a grounded answer
     citing the saved items (title + date) it drew from.
  6. If nothing qualifies → returns a 'core_not_found' response so the
     caller can fall through to SQL/RAG with a visible "no match" banner.

Returns the same shape as run_rag_pipeline / run_sql_pipeline so main.py
can plug it in alongside the existing pipelines without special casing.
"""

from typing import Optional, List, Dict, Any

from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate

from db.session_store import list_saves, get_save, DEFAULT_USER_ID
from pipelines.core_embed import embed_text, cosine_similarity

# Tuning knobs — generous on the demo end. With small save counts the
# threshold matters more than top-k.
SIMILARITY_THRESHOLD = 0.35   # below this, treated as "no relevant save"
TOP_K_FINAL          = 5      # max saves passed to the LLM


CORE_RECALL_PROMPT = PromptTemplate(
    template="""You are a helpful assistant answering from the user's
personal saved knowledge base ("core"). The user has previously saved
specific answers and uploads they care about. Use ONLY the saved items
below to answer the question.

Each item is shown with its saved title and the date the user saved it.
Cite the title(s) you draw from in your answer, naturally — e.g.
"From your saved 'Q1 Net Income' (saved May 26)…".

If the saved items don't actually answer the question, say so plainly:
"I have related saves but nothing that directly answers this." Do not
make up facts that aren't in the saved items.

--------- SAVED ITEMS ---------
{context}
-------------------------------

Question: {question}

Answer:""",
    input_variables=["context", "question"],
)


def _format_context(scored_saves: List[Dict[str, Any]]) -> str:
    """Compose the context block fed to the LLM."""
    lines = []
    for s in scored_saves:
        title = s.get("title") or "(untitled)"
        kind  = s.get("kind", "message")
        date  = (s.get("created_at") or "")[:10]   # YYYY-MM-DD
        score = s.get("_score", 0.0)
        body  = (s.get("content") or "").strip()
        lines.append(
            f"[{kind.upper()} · '{title}' · saved {date} · relevance {score:.2f}]\n{body}"
        )
    return "\n\n".join(lines)


def _load_scored_saves(user_id: str, question_vec: List[float]) -> List[Dict[str, Any]]:
    """
    Pull all active saves for the user, attach their embeddings via get_save,
    score each by cosine similarity to the question vector, return sorted
    list with score attached as _score.

    Saves with no embedding (pre-4d or backfill not run yet) are skipped
    with a console note — they simply won't be findable until embedded.
    """
    # list_saves returns light rows without embedding_json. get_save returns
    # the full row including embedding. We need the embeddings, so we
    # hydrate via get_save per item. With small N this is fine; for very
    # large cores a single bulk SQL would be the optimization.
    lite = list_saves(user_id)
    if not lite:
        return []

    scored: List[Dict[str, Any]] = []
    skipped_no_embedding = 0

    for row in lite:
        full = get_save(row["save_id"])
        if not full:
            continue
        emb_json = full.get("embedding_json")
        if not emb_json:
            skipped_no_embedding += 1
            continue
        # embedding_json was stored as JSON text → parse to list[float]
        try:
            import json
            vec = json.loads(emb_json)
            if not isinstance(vec, list):
                continue
        except Exception:
            continue

        score = cosine_similarity(question_vec, vec)
        full["_score"] = score
        scored.append(full)

    if skipped_no_embedding:
        print(f"[core_recall] {skipped_no_embedding} save(s) skipped (no embedding — "
              f"run scripts/backfill_save_embeddings.py)")

    scored.sort(key=lambda s: s["_score"], reverse=True)
    return scored


def run_core_recall_pipeline(
    question: str,
    llm:      ChatOpenAI,
    user_id:  Optional[str] = None,
) -> dict:
    """
    Full core-recall pipeline.

    Returns dict with:
      pipeline       — "core_recall"
      response_type  — "answer" | "core_not_found"
      answer         — the LLM's grounded answer, OR a friendly fallthrough message
      sources        — list of {title, date, kind, score} for the saves used
      matched        — bool — whether ANY save cleared the threshold
      sql/raw_data/columns/chart_hint — empty/none (consistent with rag pipeline shape)
    """
    user_id = user_id or DEFAULT_USER_ID

    # Embed the question
    try:
        q_vec = embed_text(question)
    except Exception as e:
        print(f"[core_recall] embedding failed: {e}")
        return {
            "pipeline":      "core_recall",
            "response_type": "core_not_found",
            "matched":       False,
            "answer":        "I couldn't search your saved core right now (embedding error).",
            "sources":       [],
            "chart_hint":    "none",
            "sql":           None,
            "raw_data":      [],
            "columns":       [],
        }

    scored = _load_scored_saves(user_id, q_vec)

    # Filter by threshold and cap
    kept = [s for s in scored if s["_score"] >= SIMILARITY_THRESHOLD][:TOP_K_FINAL]

    if not kept:
        # Caller (main.py) will see matched=False and fall through to the
        # normal pipeline, optionally surfacing a "no recall match" banner.
        best = scored[0]["_score"] if scored else 0.0
        return {
            "pipeline":      "core_recall",
            "response_type": "core_not_found",
            "matched":       False,
            "answer":        (
                "I didn't find anything in your saved core that matches this question "
                f"(best relevance {best:.2f}, threshold {SIMILARITY_THRESHOLD})."
            ),
            "sources":       [],
            "chart_hint":    "none",
            "sql":           None,
            "raw_data":      [],
            "columns":       [],
        }

    # Compose grounded answer
    context = _format_context(kept)
    prompt  = CORE_RECALL_PROMPT.format(context=context, question=question)
    answer  = llm.invoke(prompt).content.strip()

    sources = [
        {
            "title": s.get("title") or "(untitled)",
            "date":  (s.get("created_at") or "")[:10],
            "kind":  s.get("kind", "message"),
            "score": round(s["_score"], 3),
            "save_id": s.get("save_id"),
        }
        for s in kept
    ]

    return {
        "pipeline":      "core_recall",
        "response_type": "answer",
        "matched":       True,
        "answer":        answer,
        "sources":       sources,
        "chart_hint":    "none",
        "sql":           None,
        "raw_data":      [],
        "columns":       [],
    }
