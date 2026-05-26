"""
=============================================================
CoReckoner — FastAPI Backend  (Phase 4b-2)
=============================================================

Phase 3 C3:
  - run_rag_pipeline() receives session_id so user PDFs are searchable
  - DELETE /sessions/{id} cascade also removes ChromaDB vectors

Phase 4 warm-up:
  - classify_question() receives session_id (router PDF-aware)

Phase 4a:
  - ensure_default_user() on startup; /stats reports core counts

Phase 4b-2 (save button):
  - ChatResponse now carries message_id so a freshly-sent assistant
    message can be saved to core immediately.
  - POST /core/save     — save a message or upload to the user's core
  - GET  /core/saves    — look up saves (for filled-button state)
  Saves go to the default unsorted bucket (no topic at save time);
  topic organisation arrives in 4c.
"""

import os
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI

from routers.query_router import classify_question
from routers.upload_router import router as upload_router
from pipelines.sql_pipeline import run_sql_pipeline, get_db_connection, get_schema
from pipelines.rag_pipeline import run_rag_pipeline

from db.session_store import (
    init_db,
    create_session,
    get_all_sessions,
    get_session,
    get_session_with_messages,
    delete_session,
    save_message,
    save_artifact,
    update_session_title,
    touch_session,
    ensure_default_user,
    count_users,
    count_topics,
    count_saves,
    DEFAULT_USER_ID,
    # Phase 4b-2
    get_session_messages,
    get_message_artifacts,
    get_upload,
    create_save,
    get_save,
    find_save_by_source,
)
from uploads.session_db import delete_session_db
from uploads.document   import delete_session_vectors

load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH      = PROJECT_ROOT / "outputs" / "accounting.db"
CHROMA_DIR   = PROJECT_ROOT / "outputs" / "chroma_db"

# Set on startup by ensure_default_user(). Phase 4 uses this single user
# until real auth lands in 4f.
CURRENT_USER_ID = DEFAULT_USER_ID


@asynccontextmanager
async def lifespan(app: FastAPI):
    global CURRENT_USER_ID
    print("\n" + "═" * 52)
    print("  CoReckoner — Accounting AI Chatbot")
    print("  Phase 4b-2: save button (core saves)")
    print("═" * 52)
    try:
        init_db()
        print("  ✓ coreckoner.db initialised")
    except Exception as e:
        print(f"  ⚠ coreckoner.db init failed: {e}")

    try:
        CURRENT_USER_ID = ensure_default_user()
        print(f"  ✓ default user ensured ({CURRENT_USER_ID})")
    except Exception as e:
        print(f"  ⚠ ensure_default_user failed: {e}")

    if not os.getenv("OPENAI_API_KEY"):
        print("  ❌ OPENAI_API_KEY not found")
    else:
        print("  ✓ OpenAI API key loaded")

    print(f"  {'✓' if DB_PATH.exists() else '⚠'} accounting.db  {'found' if DB_PATH.exists() else 'NOT found'}")
    print(f"  {'✓' if CHROMA_DIR.exists() else '⚠'} chroma_db     {'found' if CHROMA_DIR.exists() else 'NOT found'}")
    print("═" * 52)
    print("  Chat UI:  http://localhost:8002")
    print("  API docs: http://localhost:8002/docs")
    print("═" * 52 + "\n")
    yield
    print("\nShutting down CoReckoner.")


app = FastAPI(
    title="CoReckoner — Accounting AI Chatbot",
    description="Hybrid RAG + Text-to-SQL with persistent sessions, CSV/Excel/PDF uploads",
    version="2.7.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload_router)

static_dir = PROJECT_ROOT / "backend" / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── Models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question:   str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    session_id:        str
    message_id:        Optional[str] = None   # Phase 4b-2: assistant message id
    question:          str
    answer:            str
    pipeline:          str
    response_type:     str
    chart_hint:        str
    route_explanation: str
    sql:               Optional[str]  = None
    raw_data:          Optional[list] = None
    columns:           Optional[list] = None
    sources:           Optional[list] = None
    timestamp:         str


class SessionRenameRequest(BaseModel):
    title: str


class CoreSaveRequest(BaseModel):
    kind:      str                      # 'message' | 'upload'
    source_id: str                      # message_id or upload_id
    note:      Optional[str] = None


def get_llm() -> ChatOpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")
    return ChatOpenAI(model="gpt-4o-mini", temperature=0, openai_api_key=api_key)


def _try_save_message(session_id, role, content, pipeline_used=None) -> str | None:
    try:
        return save_message(session_id, role, content, pipeline_used)
    except Exception as e:
        print(f"[session_store] save_message failed: {e}")
        return None


def _try_save_artifact(message_id, artifact_type, content) -> None:
    if not message_id:
        return
    try:
        save_artifact(message_id, artifact_type, content)
    except Exception as e:
        print(f"[session_store] save_artifact failed ({artifact_type}): {e}")


def _try_touch(session_id) -> None:
    try:
        touch_session(session_id)
    except Exception:
        pass


# ── CHAT ENDPOINT ──────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    timestamp = datetime.now().isoformat()
    llm       = get_llm()

    session_id     = request.session_id
    is_new_session = not session_id

    if session_id:
        try:
            if not get_session(session_id):
                session_id = None
        except Exception:
            session_id = None

    if not session_id:
        try:
            sess       = create_session(title=question[:80])
            session_id = sess["session_id"]
        except Exception:
            import uuid
            session_id = str(uuid.uuid4())

    _try_save_message(session_id, "user", question)
    if is_new_session:
        try:
            update_session_title(session_id, question[:80])
        except Exception:
            pass

    # Phase 4 warm-up: pass session_id so the router knows about uploaded PDFs
    route_result = classify_question(question, llm, session_id=session_id)
    route        = route_result["route"]

    sql_result    = {}
    rag_result    = {}
    final_answer  = ""
    pipeline_used = route
    response_type = "answer"
    chart_hint    = "none"

    try:
        if route in ("sql", "both"):
            sql_result = run_sql_pipeline(question, llm, DB_PATH, session_id=session_id)
            response_type = sql_result.get("response_type", "answer")
            chart_hint    = sql_result.get("chart_hint", "none")

        if route in ("rag", "both"):
            rag_result = run_rag_pipeline(
                question, llm, CHROMA_DIR, session_id=session_id
            )
            if route == "rag":
                response_type = rag_result.get("response_type", "answer")

        if route == "both":
            sql_ans = sql_result.get("answer", "")
            rag_ans = rag_result.get("answer", "")
            merge   = llm.invoke(
                f"Combine these two answers into one clear response:\n\n"
                f"DATA ANSWER: {sql_ans}\n"
                f"POLICY ANSWER: {rag_ans}\n\n"
                f"Write a unified 3-5 sentence answer addressing both numbers and policy context."
            )
            final_answer  = merge.content.strip()
            response_type = "answer"
        elif route == "sql":
            final_answer = sql_result.get("answer", "No answer generated.")
        else:
            final_answer = rag_result.get("answer", "No answer generated.")

    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")

    asst_msg_id = _try_save_message(
        session_id, "assistant", final_answer, pipeline_used
    )

    if asst_msg_id:
        _try_save_artifact(asst_msg_id, "route_explanation", route_result["explanation"])
        _try_save_artifact(asst_msg_id, "response_type", response_type)
        if sql_result.get("sql"):
            _try_save_artifact(asst_msg_id, "sql_query", sql_result["sql"])
        if sql_result.get("raw_data"):
            _try_save_artifact(asst_msg_id, "sql_result", {
                "columns": sql_result.get("columns", []),
                "rows":    sql_result.get("raw_data", []),
            })
        if rag_result.get("sources"):
            _try_save_artifact(asst_msg_id, "citations", rag_result["sources"])
        if chart_hint != "none" and sql_result.get("raw_data"):
            _try_save_artifact(asst_msg_id, "chart_spec", {
                "chart_type": chart_hint,
                "columns":    sql_result.get("columns", []),
                "rows":       sql_result.get("raw_data", []),
                "question":   question,
            })

    _try_touch(session_id)

    return ChatResponse(
        session_id        = session_id,
        message_id        = asst_msg_id,
        question          = question,
        answer            = final_answer,
        pipeline          = pipeline_used,
        response_type     = response_type,
        chart_hint        = chart_hint,
        route_explanation = route_result["explanation"],
        sql               = sql_result.get("sql"),
        raw_data          = sql_result.get("raw_data", []),
        columns           = sql_result.get("columns", []),
        sources           = rag_result.get("sources", []),
        timestamp         = timestamp,
    )


# ── SESSION ENDPOINTS ──────────────────────────────────────

@app.get("/sessions")
async def list_sessions():
    try:
        sessions = get_all_sessions()
        return {"sessions": sessions, "count": len(sessions)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sessions")
async def new_session():
    try:
        return create_session(title="New Chat")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions/{session_id}")
async def get_full_session(session_id: str):
    try:
        session = get_session_with_messages(session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.patch("/sessions/{session_id}")
async def rename_session(session_id: str, body: SessionRenameRequest):
    if not body.title or not body.title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    try:
        existing = get_session(session_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Session not found")
        update_session_title(session_id, body.title.strip())
        return {"session_id": session_id, "title": body.title.strip()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/sessions/{session_id}")
async def remove_session(session_id: str):
    """
    Delete a session and cascade cleanup across three layers:
      1. coreckoner.db rows (sessions + messages + artifacts + uploads — via FK)
      2. Per-session SQLite DB at outputs/sessions/{id}.db
      3. Per-session ChromaDB vectors in 'user_uploads' collection (C3)

    NOTE (Phase 4b): core_saves are intentionally NOT deleted here — saved
    items outlive the session they came from (decoupled storage). Their
    source_session_id may dangle, which is fine.
    """
    try:
        deleted = delete_session(session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")

    # Cascade 1: per-session SQLite DB
    try:
        delete_session_db(session_id)
    except Exception as e:
        print(f"[main] cascade: delete_session_db failed for {session_id}: {e}")

    # Cascade 2: per-session ChromaDB vectors
    try:
        n_deleted = delete_session_vectors(session_id)
        if n_deleted:
            print(f"[main] cascade: deleted {n_deleted} vectors for {session_id}")
    except Exception as e:
        print(f"[main] cascade: delete_session_vectors failed for {session_id}: {e}")

    return {"status": "deleted", "session_id": session_id}


# ── CORE SAVE ENDPOINTS (Phase 4b-2) ───────────────────────

def _build_message_snapshot(message_id: str) -> dict:
    """
    Assemble a rich, immutable snapshot of an assistant message:
    full text + its artifacts (sql, result, citations, chart, route).
    Returns {title, content, metadata, source_session_id} or raises 404.
    """
    # Find the message by scanning sessions is expensive; instead read
    # artifacts directly and the message row via a targeted helper.
    # get_message_artifacts works on message_id; we still need the message
    # row for content + session_id, so fetch via a small query helper.
    from db.session_store import _get_conn  # local import; internal helper
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT message_id, session_id, role, content, pipeline_used FROM messages WHERE message_id=?",
            (message_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Message {message_id} not found")

    msg = dict(row)
    artifacts = get_message_artifacts(message_id)

    # Fold artifacts into a compact metadata dict
    meta: dict = {"pipeline": msg.get("pipeline_used")}
    for a in artifacts:
        meta[a["artifact_type"]] = a.get("content")

    content = msg.get("content", "") or ""
    title   = content[:80].strip() or "(saved message)"

    return {
        "title":             title,
        "content":           content,
        "metadata":          meta,
        "source_session_id": msg.get("session_id"),
    }


def _build_upload_snapshot(upload_id: str) -> dict:
    """
    Assemble a snapshot of an upload from the summary captured at ingest
    (Phase 4b-1). Returns {title, content, metadata, source_session_id}.
    """
    up = get_upload(upload_id)
    if not up:
        raise HTTPException(status_code=404, detail=f"Upload {upload_id} not found")

    filename = up.get("filename", "(file)")
    summary  = up.get("summary")  # dict captured at ingest, or None

    # Build a human-readable content blurb from the summary
    lines = [f"Uploaded file: {filename}"]
    if summary and summary.get("kind") == "tabular":
        for t in summary.get("tables", []):
            cols = ", ".join(t.get("columns", []))
            lines.append(f"Table '{t.get('table_name')}' — {t.get('row_count')} rows.")
            if cols:
                lines.append(f"Columns: {cols}")
    elif summary and summary.get("kind") == "document":
        lines.append(f"{summary.get('page_count', 0)} pages · {summary.get('chunk_count', 0)} chunks.")
        preview = summary.get("preview_text")
        if preview:
            lines.append(f"Preview: {preview}")
    else:
        # No summary (older upload) — fall back to whatever the row has
        if up.get("row_count"):
            lines.append(f"{up['row_count']} rows.")
        if up.get("chunk_count"):
            lines.append(f"{up['chunk_count']} chunks.")

    content = "\n".join(lines)

    return {
        "title":             filename,
        "content":           content,
        "metadata":          {"upload": summary, "file_type": up.get("file_type"),
                              "target": up.get("target")},
        "source_session_id": up.get("session_id"),
    }


@app.post("/core/save")
async def core_save(body: CoreSaveRequest):
    """
    Save a message or upload to the current user's core.
    No topic at save time — goes to the default unsorted bucket (4c organises).
    Idempotent: saving the same source twice returns the existing save.
    """
    kind = (body.kind or "").strip()
    if kind not in ("message", "upload"):
        raise HTTPException(status_code=400, detail="kind must be 'message' or 'upload'")
    if not body.source_id:
        raise HTTPException(status_code=400, detail="source_id is required")

    if kind == "message":
        snap = _build_message_snapshot(body.source_id)
        try:
            save_id = create_save(
                user_id           = CURRENT_USER_ID,
                kind              = "message",
                title             = snap["title"],
                content           = snap["content"],
                metadata_json     = snap["metadata"],
                note              = body.note,
                source_session_id = snap["source_session_id"],
                source_message_id = body.source_id,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Save failed: {e}")
    else:
        snap = _build_upload_snapshot(body.source_id)
        try:
            save_id = create_save(
                user_id           = CURRENT_USER_ID,
                kind              = "upload",
                title             = snap["title"],
                content           = snap["content"],
                metadata_json     = snap["metadata"],
                note              = body.note,
                source_session_id = snap["source_session_id"],
                source_upload_id  = body.source_id,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Save failed: {e}")

    saved = get_save(save_id)
    return {
        "status":  "saved",
        "save_id": save_id,
        "kind":    kind,
        "title":   saved["title"] if saved else snap["title"],
    }


@app.get("/core/saves")
async def core_saves(source_message_id: Optional[str] = None,
                     source_upload_id:  Optional[str] = None):
    """
    Look up an active save by its source (for filled-button state).
    Returns {saved: bool, save_id: str|None}.
    """
    if not source_message_id and not source_upload_id:
        raise HTTPException(
            status_code=400,
            detail="Provide source_message_id or source_upload_id",
        )
    found = find_save_by_source(
        CURRENT_USER_ID,
        source_message_id=source_message_id,
        source_upload_id=source_upload_id,
    )
    return {
        "saved":   bool(found),
        "save_id": found["save_id"] if found else None,
    }


# ── SUPPORTING ENDPOINTS ───────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status":           "running",
        "db_connected":     DB_PATH.exists(),
        "chroma_connected": CHROMA_DIR.exists(),
        "api_key_set":      bool(os.getenv("OPENAI_API_KEY")),
        "persistence":      (PROJECT_ROOT / "outputs" / "coreckoner.db").exists(),
    }


@app.get("/schema")
async def get_db_schema():
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail="accounting.db not found")
    conn = get_db_connection(DB_PATH)
    schema = get_schema(conn)
    conn.close()
    return {"schema": schema}


@app.get("/stats")
async def get_stats():
    stats = {"db_exists": DB_PATH.exists(), "chroma_exists": CHROMA_DIR.exists()}
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        for table in ["accounts_payable", "revenue", "journal_entries",
                      "balance_sheet", "profit_loss", "accounts_receivable",
                      "general_ledger", "chart_of_accounts"]:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[f"{table}_rows"] = cursor.fetchone()[0]
            except Exception:
                pass
        conn.close()
    try:
        stats["session_count"] = len(get_all_sessions())
    except Exception:
        stats["session_count"] = 0

    # Phase 4a counts
    try:
        stats["user_count"]  = count_users()
        stats["topic_count"] = count_topics()
        stats["save_count"]  = count_saves()
    except Exception as e:
        print(f"[main] stats core counts failed: {e}")

    return stats


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    ui_path = static_dir / "index.html"
    if ui_path.exists():
        return FileResponse(str(ui_path))
    return HTMLResponse("<h2>Chat UI not found.</h2>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=False)
