"""
=============================================================
UPLOAD ROUTER — /uploads endpoints  (Phase 5b/c)
=============================================================

Endpoints:
  POST   /sessions/{session_id}/uploads/preview     inspect a file
  POST   /sessions/{session_id}/uploads/ingest      persist a file
  GET    /sessions/{session_id}/uploads             list uploads
  DELETE /uploads/{upload_id}                       remove an upload

Phase 5b/c changes (this version):
  - Every endpoint requires current_user via get_current_user dependency
  - Session ownership is verified before any preview/ingest/list
  - DELETE verifies the upload itself belongs to the caller
  - create_upload() now receives user_id (stored on the row for future
    per-user filtering in Pass 3)
  - PDF ingest gets user_id passed through to ingest_pdf() — Pass 3 will
    use it for ChromaDB vector metadata. For now ingest_pdf signature
    stays compatible; the kwarg is forward-looking and ignored if
    document.py hasn't been updated yet.
"""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status

from auth import User, get_current_user
from db.session_store import (
    create_upload,
    list_uploads,
    get_upload,
    delete_upload_record,
    session_belongs_to_user,
    upload_belongs_to_user,
)
from uploads.tabular    import preview_csv, preview_xlsx, ingest_csv, ingest_xlsx
from uploads.session_db import drop_tables
from uploads.document   import preview_pdf, ingest_pdf, delete_upload_vectors


router = APIRouter(tags=["uploads"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024   # 50 MB


def _detect_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".csv":           return "csv"
    if ext in (".xlsx", ".xls"): return "xlsx"
    if ext == ".pdf":            return "pdf"
    if ext in (".txt", ".md"):   return "txt"
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


def _assert_session_owned_by(session_id: str, user_id: str) -> None:
    """Same helper as in main.py — 404 (not 403) to avoid leaking existence."""
    if not session_belongs_to_user(session_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )


# ── PREVIEW ────────────────────────────────────────────────

@router.post("/sessions/{session_id}/uploads/preview")
async def preview_upload(
    session_id:   str,
    file:         UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    _assert_session_owned_by(session_id, current_user.user_id)
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
    session_id:   str,
    file:         UploadFile = File(...),
    metadata:     str = Form(default=""),
    current_user: User = Depends(get_current_user),
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
    """
    _assert_session_owned_by(session_id, current_user.user_id)
    file_bytes = await _read_validated(file)
    file_type  = _detect_file_type(file.filename)

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
            user_id      = current_user.user_id,
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
            user_id      = current_user.user_id,
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

    # ── PDF ──
    if file_type == "pdf":
        try:
            # Pass user_id through. document.ingest_pdf() may not yet
            # consume it (Pass 3 work) — try with the kwarg first,
            # fall back to the Phase 5a signature if not supported.
            try:
                result = ingest_pdf(
                    file_bytes, file.filename, session_id,
                    user_id=current_user.user_id,
                )
            except TypeError:
                # ingest_pdf hasn't been updated for Pass 3 yet — use
                # the existing signature. The upload_id row still gets
                # user_id, so per-user filtering at the DB layer works.
                result = ingest_pdf(file_bytes, file.filename, session_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"PDF ingest failed: {e}")

        upload_id = create_upload(
            session_id   = session_id,
            user_id      = current_user.user_id,
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
async def list_session_uploads(
    session_id:   str,
    current_user: User = Depends(get_current_user),
):
    _assert_session_owned_by(session_id, current_user.user_id)
    uploads = list_uploads(session_id)
    return {"session_id": session_id, "uploads": uploads, "count": len(uploads)}


# ── DELETE ─────────────────────────────────────────────────

@router.delete("/uploads/{upload_id}")
async def delete_upload(
    upload_id:    str,
    current_user: User = Depends(get_current_user),
):
    """
    Remove an upload:
      - verify caller owns the upload (404 otherwise)
      - 'sql' target → drop tables from session DB
      - 'rag' target → remove vectors from ChromaDB
      - delete the uploads row
    """
    if not upload_belongs_to_user(upload_id, current_user.user_id):
        raise HTTPException(status_code=404, detail=f"Upload {upload_id} not found")

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
