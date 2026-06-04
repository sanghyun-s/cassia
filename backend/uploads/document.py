"""
=============================================================
DOCUMENT UPLOAD — PDF chunking, embedding, ChromaDB storage
=============================================================

Phase 3 C3:
  - PDFs ingest into a SEPARATE ChromaDB collection called 'user_uploads'.
    The existing 'irs_pub15' collection is untouched and read-only at
    retrieval time.
  - Every chunk is tagged with metadata {session_id, source_file, page}.
  - Session delete cascades to bulk-delete vectors WHERE session_id == ...
  - One PDF delete: WHERE session_id == ... AND source_file == ...

Phase 4b-1:
  - ingest_pdf now also returns a "summary" key: a compact
    {kind:"document", page_count, chunk_count, preview_text} captured from
    the first chunk, so core-saves can be rich without re-reading the PDF.

Phase 5c (Pass 3) — ChromaDB user isolation:
  - ingest_pdf now REQUIRES a `user_id` parameter (no default, no fallback).
    The previous TypeError fallback in upload_router.py has been removed in
    the same commit; calling ingest_pdf without user_id raises immediately.
  - Every chunk's metadata now carries both `session_id` AND `user_id`.
    This is what `rag_pipeline._query_user_uploads()` uses as a hard
    conjunction filter at retrieval time. Defense in depth on top of the
    API-layer ownership checks added in Pass 2.
  - Delete functions are UNCHANGED. They already filter by session_id,
    which is transitively user-safe because Pass 2 verifies session
    ownership before any delete endpoint reaches this module.
  - The IRS Pub 15 collection is NOT touched here. It remains globally
    readable reference content.
"""

import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma

PROJECT_ROOT = Path(__file__).parent.parent.parent
CHROMA_DIR   = PROJECT_ROOT / "outputs" / "chroma_db"

# Match constants from rag/phase1_ingest.py exactly so chunks behave
# the same as the IRS docs do.
CHUNK_SIZE    = 1000
CHUNK_OVERLAP = 200
EMBEDDING_MODEL = "text-embedding-3-small"

# IRS docs live in 'irs_pub15' — DO NOT WRITE THERE. User PDFs go here.
USER_COLLECTION_NAME = "user_uploads"

# How many characters of the first chunk to capture for the core-save summary.
SUMMARY_PREVIEW_CHARS = 200

# Same boilerplate stripper as phase1_ingest.py so chunks read cleanly.
_BOILERPLATE_PATTERNS = [
    r"Page \d+ of \d+",
    r"Fileid:\s*\S+",
    r"\d{1,2}:\d{2}\s*-\s*\d{1,2}-[A-Za-z]{3}-\d{4}",
    r"The type and rule above prints on all proofs.*",
    r"including departmental reproduction.*",
]

def _clean_text(text: str) -> str:
    for pat in _BOILERPLATE_PATTERNS:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _get_embeddings() -> OpenAIEmbeddings:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in environment")
    return OpenAIEmbeddings(model=EMBEDDING_MODEL, openai_api_key=api_key)


def _get_user_vectorstore() -> Chroma:
    """
    Open (or create) the 'user_uploads' collection.
    Idempotent — safe to call repeatedly.
    """
    return Chroma(
        collection_name=USER_COLLECTION_NAME,
        embedding_function=_get_embeddings(),
        persist_directory=str(CHROMA_DIR),
    )


# ── Public API ─────────────────────────────────────────────

def preview_pdf(file_bytes: bytes, filename: str) -> dict:
    """
    Quick PDF inspection without persistence. Returns page count and
    an estimate of how many chunks will be produced on ingest.
    """
    if not file_bytes:
        raise ValueError("Empty PDF bytes")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        loader = PyPDFLoader(tmp_path)
        pages  = loader.load()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    total_chars = sum(len(_clean_text(p.page_content)) for p in pages)
    # Rough estimate: chunks ≈ chars / (chunk_size - overlap)
    est_chunks = max(1, total_chars // max(1, CHUNK_SIZE - CHUNK_OVERLAP))

    return {
        "file_type":        "pdf",
        "filename":         filename,
        "page_count":       len(pages),
        "estimated_chunks": est_chunks,
        "total_chars":      total_chars,
    }


def ingest_pdf(
    file_bytes: bytes,
    filename:   str,
    session_id: str,
    user_id:    str,
) -> dict:
    """
    Parse PDF → chunk → embed → write to user_uploads collection.

    Every chunk is tagged with metadata
      {session_id, user_id, source_file, source_doc, source_type,
       page, page_display}
    so retrieval can apply the per-user, per-session conjunction filter
    enforced by `rag_pipeline._query_user_uploads()`.

    Args:
        file_bytes: raw PDF bytes
        filename:   display name for citations
        session_id: REQUIRED. The chat session this upload belongs to.
        user_id:    REQUIRED. The authenticated user uploading the file.
                    Pass 3 (Phase 5c) made this mandatory — no fallback.

    Returns: {filename, chunk_count, page_count, summary}
    Raises ValueError on any missing required argument or empty PDF.
    """
    if not session_id:
        raise ValueError("session_id is required to ingest a PDF")
    if not user_id:
        raise ValueError("user_id is required to ingest a PDF")
    if not file_bytes:
        raise ValueError("Empty PDF bytes")

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        loader = PyPDFLoader(tmp_path)
        pages  = loader.load()

        if not pages:
            raise ValueError(f"PDF '{filename}' produced no pages")

        # Tag every page first with our metadata + clean the text
        for p in pages:
            p.page_content = _clean_text(p.page_content)
            # PyPDFLoader pages are 0-indexed → convert to 1-indexed for display
            page_zero_indexed = p.metadata.get("page", 0)
            p.metadata = {
                "session_id":   session_id,
                "user_id":      user_id,        # ← Pass 3: vector-level isolation
                "source_file":  filename,
                "source_doc":   filename,        # for citation display
                "source_type":  "user",          # tag so retrieval can filter
                "page":         page_zero_indexed + 1,
                "page_display": page_zero_indexed + 1,
            }

        splitter = RecursiveCharacterTextSplitter(
            chunk_size    = CHUNK_SIZE,
            chunk_overlap = CHUNK_OVERLAP,
            length_function = len,
            separators    = ["\n\n", "\n", ". ", " ", ""],
        )
        chunks = splitter.split_documents(pages)

        if not chunks:
            raise ValueError(f"PDF '{filename}' produced no chunks after splitting")

        vs = _get_user_vectorstore()
        vs.add_documents(chunks)

        # Capture a short preview from the first chunk for core-saves recall.
        preview_text = chunks[0].page_content[:SUMMARY_PREVIEW_CHARS].strip()

        return {
            "filename":    filename,
            "page_count":  len(pages),
            "chunk_count": len(chunks),
            "summary": {
                "kind":         "document",
                "filename":     filename,
                "page_count":   len(pages),
                "chunk_count":  len(chunks),
                "preview_text": preview_text,
            },
        }
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def delete_upload_vectors(session_id: str, filename: str) -> int:
    """
    Delete vectors for ONE uploaded PDF in one session.
    Returns the number of vectors deleted (best effort).

    Session-scoped filter is sufficient — once Pass 2 verifies the
    caller owns the session before this is invoked, the delete is
    transitively user-safe. No user_id filter needed here.
    """
    if not session_id or not filename:
        return 0
    try:
        vs   = _get_user_vectorstore()
        # Filter chunks belonging to this exact (session_id, filename) pair
        got  = vs.get(where={"$and": [
            {"session_id":  session_id},
            {"source_file": filename},
        ]})
        ids  = got.get("ids", [])
        if not ids:
            return 0
        vs.delete(ids=ids)
        return len(ids)
    except Exception as e:
        print(f"[document] delete_upload_vectors error: {e}")
        return 0


def delete_session_vectors(session_id: str) -> int:
    """
    Bulk delete ALL vectors for a session. Used by session-delete cascade.
    Returns the number of vectors deleted (best effort).

    Session-scoped — same rationale as delete_upload_vectors above.
    """
    if not session_id:
        return 0
    try:
        vs   = _get_user_vectorstore()
        got  = vs.get(where={"session_id": session_id})
        ids  = got.get("ids", [])
        if not ids:
            return 0
        vs.delete(ids=ids)
        return len(ids)
    except Exception as e:
        print(f"[document] delete_session_vectors error: {e}")
        return 0
