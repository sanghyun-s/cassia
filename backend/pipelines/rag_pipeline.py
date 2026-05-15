"""
=============================================================
RAG PIPELINE — Dual-collection retrieval
=============================================================

Phase 3 C3:
  - 'irs_pub15' collection = public read-only IRS docs (existing)
  - 'user_uploads' collection = per-session user PDFs (new)
  - Retrieval queries BOTH, filters user_uploads by session_id, merges
    by raw similarity score, returns top-k overall.
  - Backwards compatible: if no session_id passed, only IRS docs are used.
"""

from pathlib import Path
from typing import Optional, List
import os

from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import Chroma
from langchain.prompts import PromptTemplate
from langchain.schema import Document

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Match the collection names used elsewhere in the codebase
IRS_COLLECTION  = "irs_pub15"
USER_COLLECTION = "user_uploads"
EMBEDDING_MODEL = "text-embedding-3-small"

TOP_K_PER_COLLECTION = 4   # pull from each
TOP_K_FINAL          = 4   # then truncate combined list to this many

RAG_PROMPT = PromptTemplate(
    template="""You are a helpful tax and accounting assistant.
Use ONLY the following excerpts to answer the question.
Some excerpts may come from IRS publications (public), others from
documents the user uploaded into this session. Treat both as valid
context; prefer the source most relevant to the question.

If the answer is not in the excerpts, say "I couldn't find that in the available documents."
Always cite the source document and page number when present.

--------- EXCERPTS ---------
{context}
----------------------------

Question: {question}

Answer (be specific, cite document + page where available):""",
    input_variables=["context", "question"],
)

_NOT_FOUND_PHRASES = [
    "couldn't find",
    "cannot find",
    "not found in",
    "not in publication",
    "not in the available",
    "no information",
    "not covered",
]


def _get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=EMBEDDING_MODEL,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
    )


def _open_collection(name: str, chroma_dir: Path) -> Chroma:
    return Chroma(
        collection_name=name,
        embedding_function=_get_embeddings(),
        persist_directory=str(chroma_dir),
    )


def _format_context(docs: List[Document]) -> str:
    """Compose the context block fed to the LLM."""
    lines = []
    for d in docs:
        src  = d.metadata.get("source_doc") or d.metadata.get("source_file") or "(unknown)"
        page = d.metadata.get("page_display") or d.metadata.get("page") or "?"
        lines.append(f"[{src}, page {page}] {d.page_content}")
    return "\n\n".join(lines)


def _retrieve(
    question:   str,
    chroma_dir: Path,
    session_id: Optional[str],
) -> List[Document]:
    """
    Query both collections, return merged top-k by similarity score.

    Note on scoring: similarity_search_with_score returns a *distance*
    (lower = more similar) in Chroma. We invert to a score where higher
    is better, then sort descending.
    """
    if not chroma_dir.exists():
        raise FileNotFoundError(
            f"ChromaDB not found at {chroma_dir}. Run rag/phase1_ingest.py first."
        )

    combined: List[tuple] = []   # list of (score, Document)

    # ── IRS public collection (read-only, always included) ─────────
    try:
        irs_vs = _open_collection(IRS_COLLECTION, chroma_dir)
        irs_results = irs_vs.similarity_search_with_score(
            question, k=TOP_K_PER_COLLECTION
        )
        for doc, dist in irs_results:
            # Mark provenance so the prompt can show it
            doc.metadata.setdefault("source_type", "irs")
            combined.append((-float(dist), doc))   # negate so higher = better
    except Exception as e:
        print(f"[rag_pipeline] IRS collection query failed: {e}")

    # ── User uploads collection (filtered by session_id) ───────────
    if session_id:
        try:
            user_vs = _open_collection(USER_COLLECTION, chroma_dir)
            user_results = user_vs.similarity_search_with_score(
                question,
                k      = TOP_K_PER_COLLECTION,
                filter = {"session_id": session_id},   # security boundary
            )
            for doc, dist in user_results:
                doc.metadata.setdefault("source_type", "user")
                combined.append((-float(dist), doc))
        except Exception as e:
            # Common case: the user_uploads collection doesn't exist yet
            # (no PDFs ever uploaded). Silent skip.
            print(f"[rag_pipeline] user_uploads query skipped: {e}")

    # Sort by score descending and take the top-k overall
    combined.sort(key=lambda t: t[0], reverse=True)
    return [doc for _, doc in combined[:TOP_K_FINAL]]


def run_rag_pipeline(
    question:   str,
    llm:        ChatOpenAI,
    chroma_dir: Path,
    session_id: Optional[str] = None,
) -> dict:
    """
    Full RAG pipeline with optional session-scoped user uploads.

    Returns dict with: answer, sources, response_type, chart_hint
    """
    docs = _retrieve(question, chroma_dir, session_id)

    if not docs:
        return {
            "pipeline":      "rag",
            "response_type": "rag_not_found",
            "chart_hint":    "none",
            "answer":        "I couldn't find anything relevant in the available documents.",
            "sources":       [],
            "sql":           None,
            "raw_data":      [],
            "columns":       [],
        }

    context = _format_context(docs)
    prompt  = RAG_PROMPT.format(context=context, question=question)
    answer  = llm.invoke(prompt).content.strip()

    # Determine response_type
    answer_lower = answer.lower()
    response_type = "rag_not_found" if any(p in answer_lower for p in _NOT_FOUND_PHRASES) else "answer"

    # Build sources panel — include source_doc so user can tell IRS vs uploaded
    sources = []
    for doc in docs:
        page    = doc.metadata.get("page_display") or doc.metadata.get("page", "?")
        src     = doc.metadata.get("source_doc") or doc.metadata.get("source_file") or "?"
        preview = doc.page_content[:150].replace("\n", " ")
        sources.append({"page": page, "preview": preview, "source": src})

    return {
        "pipeline":      "rag",
        "response_type": response_type,
        "chart_hint":    "none",
        "answer":        answer,
        "sources":       sources,
        "sql":           None,
        "raw_data":      [],
        "columns":       [],
    }
