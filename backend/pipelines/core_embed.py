"""
=============================================================
CORE EMBED — embedding helper for core_saves (Phase 4d)
=============================================================

A tiny module with two jobs:
  1. embed_text(text)              → list[float]  (calls OpenAI)
  2. cosine_similarity(a, b)       → float in [-1, 1]

Used by:
  - main.py at save time (embed-on-save for new core_saves)
  - core_recall_pipeline.py at query time (embed the question, score saves)
  - scripts/backfill_save_embeddings.py (one-time fill for pre-4d saves)

Why this lives in its own file: both the pipeline AND main.py call into
embedding, so factoring it here avoids a circular import and lets a future
backfill script reuse the same code path.
"""

import os
import math
from typing import Optional, List

from langchain_openai import OpenAIEmbeddings

# Same model used by the IRS RAG pipeline — no new dependency, and saves
# embedded with the same model means cross-comparison stays meaningful if
# we ever want to unify.
EMBEDDING_MODEL = "text-embedding-3-small"

# Module-level singleton so we don't reconstruct the client on every call.
_embedder: Optional[OpenAIEmbeddings] = None


def _get_embedder() -> OpenAIEmbeddings:
    global _embedder
    if _embedder is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set; cannot embed core saves.")
        _embedder = OpenAIEmbeddings(
            model=EMBEDDING_MODEL,
            openai_api_key=api_key,
        )
    return _embedder


def embed_text(text: str) -> List[float]:
    """
    Embed a single piece of text. Returns a 1536-dim float vector.
    Trims very long input — text-embedding-3-small handles ~8K tokens, but
    saved messages are typically much shorter, so a hard cap is a safety net.
    """
    if not text or not text.strip():
        raise ValueError("Cannot embed empty text")

    # Soft cap: ~24K chars is well under the model's 8192-token limit
    # but protects against runaway inputs.
    clipped = text[:24000]
    return _get_embedder().embed_query(clipped)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """
    Pure-Python cosine similarity. No numpy dependency — keeps this module
    cheap and portable. Returns a float in [-1, 1]; higher = more similar.
    """
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        return 0.0

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot    += x * y
        norm_a += x * x
        norm_b += y * y

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
