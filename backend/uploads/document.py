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


def ingest_pdf(file_bytes: bytes, filename: str, session_id: str) -> dict:
    """
    Parse PDF → chunk → embed → write to user_uploads collection.
    Every chunk tagged with metadata {session_id, source_file, page}.

    Returns: {filename, chunk_count, page_count, summary}
    Raises on any failure — caller wraps with HTTPException.
    """
    if not session_id:
        raise ValueError("session_id is required to ingest a PDF")
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
