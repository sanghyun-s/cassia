"""
=============================================================
UPLOAD ROUTER — /uploads endpoints  (Phase 3 C3 + 4b-1)
=============================================================

Endpoints:
  POST   /sessions/{session_id}/uploads/preview     inspect a file
  POST   /sessions/{session_id}/uploads/ingest      persist a file
  GET    /sessions/{session_id}/uploads             list uploads
  DELETE /uploads/{upload_id}                       remove an upload

Phase 3 C3:
  - PDF preview + ingest live; DELETE handles 'rag' target (ChromaDB)

Phase 4b-1:
  - Each create_upload() now stores the summary captured at ingest
    (summary_json) so core-saves can be rich without re-reading files.
"""

import json
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, status

from db.session_store import (
    get_session,
    create_upload,
    list_uploads,
    get_upload,
    delete_upload_record,
)
from uploads.tabular    import preview_csv, preview_xlsx, ingest_csv, ingest_xlsx
from uploads.session_db import drop_tables
from uploads.document   import preview_pdf, ingest_pdf, delete_upload_vectors


router = APIRouter(tags=["uploads"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024   # 50 MB


def _detect_file_type(filename: str) -> str:
    """Return 'csv' | 'xlsx' | 'pdf' | 'txt' | 'unknown' based on extension."""
    ext = Path(filename).suffix.lower()
    if ext == ".csv":
        return "csv"
    if ext in (".xlsx", ".xls"):
        return "xlsx"
    if ext == ".pdf":
        return "pdf"
    if ext in (".txt", ".md"):
        return "txt"
    return "unknown"


async def _read_validated(file: UploadFile) -> bytes:
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload is missing a filename.",
        )
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {MAX_UPLOAD_BYTES // (1024*1024)} MB limit.",
        )
    return file_bytes


def _require_session(session_id: str) -> None:
    if not get_session(session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )


# ── PREVIEW ────────────────────────────────────────────────

@router.post("/sessions/{session_id}/uploads/preview")
async def preview_upload(session_id: str, file: UploadFile = File(...)):
    """Inspect an uploaded file without persisting anything."""
    _require_session(session_id)
    file_bytes = await _read_validated(file)
    file_type  = _detect_file_type(file.filename)

    if file_type == "csv":
        try:
            return preview_csv(file_bytes, file.filename)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    if file_type == "xlsx":
        try:
            return preview_xlsx(file_bytes, file.filename)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    if file_type == "pdf":
        try:
            return preview_pdf(file_bytes, file.filename)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"PDF preview failed: {e}")

    if file_type == "txt":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="TXT preview not yet implemented.",
        )

    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail=f"Unsupported file type. Got '{Path(file.filename).suffix}'. "
               f"Supported: .csv, .xlsx, .xls, .pdf.",
    )


# ── INGEST ─────────────────────────────────────────────────

@router.post("/sessions/{session_id}/uploads/ingest")
async def ingest_upload(
    session_id: str,
    file: UploadFile = File(...),
    metadata: str = Form(default=""),
):
    """
    Persist an uploaded file into the session's SQLite DB (tabular) or
    ChromaDB 'user_uploads' collection (PDF).

    `metadata` is an optional JSON string. Shape:
      {
        "table_name": "custom_name"       // CSV only
        "table_names": {                  // Excel only
          "Sheet1": "custom_name",
          ...
        }
      }
    Missing keys fall back to the auto-suggested name.
    """
    _require_session(session_id)
    file_bytes = await _read_validated(file)
    file_type  = _detect_file_type(file.filename)

    # Parse metadata if provided
    meta: dict = {}
    if metadata:
        try:
            meta = json.loads(metadata)
            if not isinstance(meta, dict):
                raise ValueError("metadata must be a JSON object")
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid metadata JSON: {e}",
            )

    # ── CSV ──
    if file_type == "csv":
        override = meta.get("table_name")
        try:
            result = ingest_csv(session_id, file_bytes, file.filename, override)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ingest failed: {e}")

        upload_id = create_upload(
            session_id   = session_id,
            filename     = file.filename,
            file_type    = "csv",
            target       = "sql",
            table_names  = result["tables_created"],
            row_count    = result["total_rows"],
            summary_json = result.get("summary"),
        )
        return {
            "upload_id":  upload_id,
            "session_id": session_id,
            "filename":   file.filename,
            "file_type":  "csv",
            **result,
        }

    # ── Excel ──
    if file_type == "xlsx":
        overrides = meta.get("table_names") or {}
        if not isinstance(overrides, dict):
            raise HTTPException(
                status_code=400,
                detail="metadata.table_names must be an object mapping sheet name to table name.",
            )
        try:
            result = ingest_xlsx(session_id, file_bytes, file.filename, overrides)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ingest failed: {e}")

        upload_id = create_upload(
            session_id   = session_id,
            filename     = file.filename,
            file_type    = "xlsx",
            target       = "sql",
            table_names  = result["tables_created"],
            row_count    = result["total_rows"],
            summary_json = result.get("summary"),
        )
        return {
            "upload_id":  upload_id,
            "session_id": session_id,
            "filename":   file.filename,
            "file_type":  "xlsx",
            **result,
        }

    # ── PDF ──  (Phase 3 C3)
    if file_type == "pdf":
        try:
            result = ingest_pdf(file_bytes, file.filename, session_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"PDF ingest failed: {e}")

        upload_id = create_upload(
            session_id   = session_id,
            filename     = file.filename,
            file_type    = "pdf",
            target       = "rag",
            table_names  = [],
            chunk_count  = result.get("chunk_count", 0),
            summary_json = result.get("summary"),
        )
        return {
            "upload_id":   upload_id,
            "session_id":  session_id,
            "filename":    file.filename,
            "file_type":   "pdf",
            "page_count":  result.get("page_count", 0),
            "chunk_count": result.get("chunk_count", 0),
        }

    if file_type == "txt":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="TXT ingest not yet implemented.",
        )

    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail=f"Unsupported file type. Got '{Path(file.filename).suffix}'.",
    )


# ── LIST ───────────────────────────────────────────────────

@router.get("/sessions/{session_id}/uploads")
async def list_session_uploads(session_id: str):
    """Return all uploads for a session, newest first."""
    _require_session(session_id)
    uploads = list_uploads(session_id)
    return {"session_id": session_id, "uploads": uploads, "count": len(uploads)}


# ── DELETE ─────────────────────────────────────────────────

@router.delete("/uploads/{upload_id}")
async def delete_upload(upload_id: str):
    """
    Remove an upload:
      - 'sql' target → drop the tables from the session DB
      - 'rag' target → remove vectors from ChromaDB user_uploads collection
      - delete the uploads row
    """
    upload = get_upload(upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail=f"Upload {upload_id} not found")

    target     = upload.get("target", "sql")
    session_id = upload.get("session_id", "")
    filename   = upload.get("filename", "")

    if target == "sql":
        tables = upload.get("table_names") or []
        if tables:
            try:
                drop_tables(session_id, tables)
            except Exception as e:
                print(f"[upload_router] drop_tables failed for {upload_id}: {e}")

    elif target == "rag":
        try:
            n = delete_upload_vectors(session_id, filename)
            if n:
                print(f"[upload_router] removed {n} vectors for {filename}")
        except Exception as e:
            print(f"[upload_router] delete_upload_vectors failed for {upload_id}: {e}")

    deleted = delete_upload_record(upload_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete upload record")

    return {"status": "deleted", "upload_id": upload_id}
