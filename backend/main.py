"""
=============================================================
CoReckoner — FastAPI Backend  (Phase 3 C3)
=============================================================

Phase 3 C3:
  - run_rag_pipeline() now receives session_id so user PDFs are searchable
  - DELETE /sessions/{id} cascade now also removes ChromaDB vectors
    via document.delete_session_vectors(session_id)
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
)
from uploads.session_db import delete_session_db
from uploads.document   import delete_session_vectors

load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH      = PROJECT_ROOT / "outputs" / "accounting.db"
CHROMA_DIR   = PROJECT_ROOT / "outputs" / "chroma_db"


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n" + "═" * 52)
    print("  CoReckoner — Accounting AI Chatbot")
    print("  Phase 3 C3: PDF upload + dual-collection RAG")
    print("═" * 52)
    try:
        init_db()
        print("  ✓ coreckoner.db initialised")
    except Exception as e:
        print(f"  ⚠ coreckoner.db init failed: {e}")

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
    version="2.5.0",
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

    route_result = classify_question(question, llm)
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
      3. Per-session ChromaDB vectors in 'user_uploads' collection (NEW in C3)
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
