"""
=============================================================
FASTAPI BACKEND — App 2 Accounting AI Chatbot
=============================================================

Single server that connects:
  - Query Router     (classifies each question)
  - SQL Pipeline     (structured QuickBooks data)
  - RAG Pipeline     (IRS Publication 15 documents)
  - Conversation Memory (multi-turn context)

Endpoints:
  POST /chat          → main chat endpoint
  GET  /health        → server status check
  GET  /history       → conversation history
  DELETE /history     → clear conversation
  GET  /schema        → show database tables
  GET  /stats         → collection stats

Run with:
  uvicorn main:app --reload --port 8000

Then open: http://localhost:8000
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
from httpcore import request
from pydantic import BaseModel
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI

# Local modules
from routers.query_router import classify_question
from pipelines.sql_pipeline import run_sql_pipeline, get_db_connection, get_schema
from pipelines.rag_pipeline import run_rag_pipeline

load_dotenv()

# ── Paths — adjust if your folder structure differs ───────
PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH      = PROJECT_ROOT / "outputs" / "accounting.db"
CHROMA_DIR   = PROJECT_ROOT / "outputs" / "chroma_db"

# In-memory conversation history (per server session)
# Each entry: {question, answer, pipeline, sql, raw_data, columns, chart_spec, sources, timestamp, route_explanation}
conversation_history = []

# How many recent exchanges to feed into router/pipelines for context resolution
HISTORY_WINDOW = 3


# ── Startup / shutdown ─────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate required resources on startup."""
    print("\n" + "═" * 50)
    print("  App 2 — Accounting AI Chatbot")
    print("  FastAPI Backend starting...")
    print("═" * 50)

    if not os.getenv("OPENAI_API_KEY"):
        print("  ❌ OPENAI_API_KEY not found in .env")
    else:
        print("  ✓ OpenAI API key loaded")

    if DB_PATH.exists():
        print(f"  ✓ SQLite DB found: {DB_PATH.name}")
    else:
        print(f"  ⚠ SQLite DB not found at: {DB_PATH}")
        print(f"    Run phase1_load.py in session 6. text2sq first")

    if CHROMA_DIR.exists():
        print(f"  ✓ ChromaDB found: {CHROMA_DIR}")
    else:
        print(f"  ⚠ ChromaDB not found at: {CHROMA_DIR}")
        print(f"    Run phase1_ingest.py in session 6. ChromaDB first")

    print("═" * 50)
    print(f"  Chat UI: http://localhost:8000")
    print(f"  API docs: http://localhost:8000/docs")
    print("═" * 50 + "\n")

    yield  # server runs here

    print("\nShutting down App 2 backend.")


# ── FastAPI app ────────────────────────────────────────────
app = FastAPI(
    title="App 2 — Accounting AI Chatbot",
    description="Hybrid RAG + Text-to-SQL accounting assistant",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (the chat UI)
static_dir = PROJECT_ROOT / "backend" / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── Request / Response models ──────────────────────────────
class ChatRequest(BaseModel):
    question: str
    use_memory: bool = True


class ChatResponse(BaseModel):
    question: str
    answer: str
    pipeline: str          # "sql", "rag", or "both"
    route_explanation: str
    sql: Optional[str] = None
    raw_data: Optional[list] = None
    columns: Optional[list] = None
    chart_spec: Optional[dict] = None    # ← ADD THIS LINE
    sources: Optional[list] = None
    timestamp: str


# ── Helper: initialize LLM ────────────────────────────────
def get_llm() -> ChatOpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")
    return ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        openai_api_key=api_key,
    )

def get_recent_context(n: int = HISTORY_WINDOW) -> str:
    """
    Format the last n exchanges as plain text for prompt injection.
    Returns empty string if no prior history.

    Used to give the router and SQL pipeline awareness of prior turns
    so follow-up questions like "show me the top 3 from those" can resolve.
    """
    if not conversation_history:
        return ""

    recent = conversation_history[-n:]
    lines = []
    for i, entry in enumerate(recent, 1):
        q = entry.get("question", "")
        a = entry.get("answer", "")
        # Truncate long answers to keep prompt size manageable
        if len(a) > 400:
            a = a[:400] + "..."
        lines.append(f"Turn {i}:\nUser: {q}\nAssistant: {a}")

    return "\n\n".join(lines)

# ── MAIN CHAT ENDPOINT ─────────────────────────────────────
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    The core endpoint. Flow:
      1. Classify question → SQL or RAG or BOTH
      2. Run appropriate pipeline(s)
      3. If BOTH: merge answers
      4. Save to conversation memory
      5. Return structured response
    """
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    llm = get_llm()
    timestamp = datetime.now().isoformat()

    # Get recent conversation context for follow-up resolution
    history_context = get_recent_context() if request.use_memory else ""

    # Step 1: Route the question (with history awareness)
    route_result = classify_question(question, llm, history=history_context)
    route = route_result["route"]

    sql_result = {}
    rag_result = {}
    final_answer = ""
    pipeline_used = route

    # Step 2: Run pipeline(s) — pass history for follow-up context
    try:
        if route in ("sql", "both"):
            sql_result = run_sql_pipeline(question, llm, DB_PATH, history=history_context)

        if route in ("rag", "both"):
            rag_result = run_rag_pipeline(question, llm, CHROMA_DIR, history=history_context)

    # Step 3: Merge if BOTH
        if route == "both":
            sql_ans = sql_result.get("answer", "")
            rag_ans = rag_result.get("answer", "")

            merge_prompt = f"""Combine these two answers into one clear response:

DATA ANSWER: {sql_ans}
POLICY ANSWER: {rag_ans}

Write a unified 3-5 sentence answer that addresses both the numbers and the policy context."""
            merged = llm.invoke(merge_prompt)
            final_answer = merged.content.strip()
        elif route == "sql":
            final_answer = sql_result.get("answer", "No answer generated.")
        else:
            final_answer = rag_result.get("answer", "No answer generated.")

    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")

    # Step 4: Save to memory and history
 
    entry = {
        "question": question,
        "answer": final_answer,
        "pipeline": pipeline_used,
        "route_explanation": route_result["explanation"],
        "sql": sql_result.get("sql"),
        "raw_data": sql_result.get("raw_data", []),
        "columns": sql_result.get("columns", []),
        "chart_spec": sql_result.get("chart_spec"),    # ← ADD THIS LINE
        "sources": rag_result.get("sources", []),
        "timestamp": timestamp,
        }
    
    conversation_history.append(entry)

    return ChatResponse(**entry)


# ── SUPPORTING ENDPOINTS ───────────────────────────────────
@app.get("/health")
async def health():
    """Check server and pipeline status."""
    return {
        "status": "running",
        "db_connected": DB_PATH.exists(),
        "chroma_connected": CHROMA_DIR.exists(),
        "api_key_set": bool(os.getenv("OPENAI_API_KEY")),
        "conversation_turns": len(conversation_history),
    }


@app.get("/history")
async def get_history():
    """Return full conversation history."""
    return {
        "count": len(conversation_history),
        "history": conversation_history,
    }


@app.delete("/history")
async def clear_history():
    """Clear conversation history."""
    global conversation_history
    conversation_history = []
    return {"status": "cleared"}


@app.get("/schema")
async def get_db_schema():
    """Return database schema — useful for debugging."""
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail="Database not found")
    conn = get_db_connection(DB_PATH)
    schema = get_schema(conn)
    conn.close()
    return {"schema": schema}


@app.get("/stats")
async def get_stats():
    """Return pipeline statistics."""
    stats = {
        "conversation_turns": len(conversation_history),
        "db_exists": DB_PATH.exists(),
        "chroma_exists": CHROMA_DIR.exists(),
    }

    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        for table in ["accounts_payable", "revenue", "journal_entries"]:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[f"{table}_rows"] = cursor.fetchone()[0]
            except Exception:
                pass
        conn.close()

    return stats


# ── SERVE CHAT UI ──────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the chat interface."""
    ui_path = static_dir / "index.html"
    if ui_path.exists():
        return FileResponse(str(ui_path))
    return HTMLResponse("<h2>Chat UI not found. Place index.html in static/</h2>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=False)