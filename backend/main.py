"""
=============================================================
CoReckoner — FastAPI Backend  (Phase 4e: topic-grouped sessions)
=============================================================

Phase 4d (natural-language recall):
  - Router learns a 4th route: 'core_recall' (triggers + LLM + fall-through)
  - pipelines/core_recall_pipeline.py does cosine similarity over saves
  - pipelines/core_embed.py provides embed_text + cosine_similarity
  - core_saves are embedded at save time (call into core_embed in /core/save)
  - When core_recall returns no match, /chat falls through to the normal
    pipeline AND surfaces a visible "no recall match" banner via the
    `core_fallthrough_note` artifact.

v2.9.1 — auto session titles:
  - After the first user+assistant exchange in a session, a small LLM call
    generates a 3-6 word title in the user's language (English or Korean).
  - Set-once on first exchange only; manual rename still overrides.

v2.10.0 — Phase 4e: topic-grouped sessions:
  - sessions can be assigned to a topic (shared namespace with 4c core saves).
  - New endpoint: PATCH /sessions/{id}/topic — set or clear a session's topic.
  - get_all_sessions() returns topic_id so the sidebar can render groups.
  - Smoother default in /core/save: a save inherits its source session's
    topic_id automatically, so the user doesn't have to re-sort saves
    that came from an already-organized session.
  - No in-chat header dropdown — topic assignment lives only in the sidebar
    (inline hover menu on each session row).

ChatResponse gains (4d, unchanged):
  core_recall_attempted : bool
  core_recall_matched   : bool
  core_fallthrough_note : str
  core_sources          : list
"""

import os
import json
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
from pipelines.core_recall_pipeline import run_core_recall_pipeline
from pipelines.core_embed import embed_text

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
    update_session_topic,
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
    # Phase 4c
    create_topic,
    list_topics,
    rename_topic,
    delete_topic,
    list_saves,
    update_save_topic,
    archive_save,
    # Phase 4d
    update_save_embedding,
    list_saves_needing_embedding,
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
    print("  v2.10.0 · Phase 4e: topic-grouped sessions")
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

    # Phase 4d: warn if any saves still lack embeddings
    try:
        unembedded = list_saves_needing_embedding(CURRENT_USER_ID)
        if unembedded:
            print(f"  ⚠ {len(unembedded)} core save(s) missing embeddings — "
                  f"run: python3 backend/scripts/backfill_save_embeddings.py")
    except Exception as e:
        print(f"  ⚠ embedding-check failed: {e}")

    print("═" * 52)
    print("  Chat UI:  http://localhost:8002")
    print("  API docs: http://localhost:8002/docs")
    print("═" * 52 + "\n")
    yield
    print("\nShutting down CoReckoner.")


app = FastAPI(
    title="CoReckoner — Accounting AI Chatbot",
    description="Hybrid RAG + Text-to-SQL with persistent sessions, uploads, core recall, auto-titles, topic-grouped sidebar",
    version="2.10.0",
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
    message_id:        Optional[str] = None
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
    # Phase 4d additions:
    core_recall_attempted: bool          = False
    core_recall_matched:   bool          = False
    core_fallthrough_note: Optional[str] = None
    core_sources:          Optional[list] = None
    timestamp:         str


class SessionRenameRequest(BaseModel):
    title: str


class SessionTopicRequest(BaseModel):
    """Phase 4e: assign or clear a session's topic."""
    topic_id:    Optional[str] = None
    clear_topic: bool          = False


class CoreSaveRequest(BaseModel):
    kind:      str
    source_id: str
    note:      Optional[str] = None


class TopicCreateRequest(BaseModel):
    name: str


class TopicRenameRequest(BaseModel):
    name: str


class SaveUpdateRequest(BaseModel):
    topic_id: Optional[str] = None
    note:     Optional[str] = None
    clear_topic: bool = False


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


def _try_embed_save(save_id: str, text: str) -> None:
    """
    Phase 4d: embed a save and cache its vector. Best-effort.
    """
    if not save_id or not text:
        return
    try:
        vec  = embed_text(text)
        vstr = json.dumps(vec)
        update_save_embedding(save_id, vstr)
    except Exception as e:
        print(f"[main] embed-on-save failed for {save_id}: {e}")


def _inherit_session_topic(source_session_id: str | None) -> str | None:
    """
    Phase 4e: if the save's source session has a topic assigned, inherit it.
    Returns the topic_id or None. Best-effort — any failure returns None
    and the save lands in Unsorted (the pre-4e default).
    """
    if not source_session_id:
        return None
    try:
        sess = get_session(source_session_id)
        if sess and sess.get("topic_id"):
            return sess["topic_id"]
    except Exception as e:
        print(f"[main] inherit-session-topic failed: {e}")
    return None


# ── Auto session titles (v2.9.1) ───────────────────────────

TITLE_GEN_PROMPT = (
    "Generate a brief, descriptive title for this accounting chat conversation.\n"
    "Rules:\n"
    "- 3 to 6 words\n"
    "- Use the SAME language as the user's question (English or Korean)\n"
    "- Capture the topic, not the user's exact phrasing\n"
    "- No quotation marks, no trailing punctuation\n"
    "- Examples: Q1 2026 Net Income, Revenue by Service Line, "
    "IRS Late Deposit Penalty, 직원 급여 원천징수, AR Aging Over 60 Days\n\n"
    "User question: {question}\n"
    "Assistant answer (first 300 chars): {answer_preview}\n\n"
    "Title:"
)


def _try_generate_session_title(session_id: str, question: str,
                                 answer: str, llm: ChatOpenAI) -> None:
    """
    Generate a short, language-matched session title via a small LLM call.
    Best-effort — failure leaves whatever placeholder is currently set.
    Fires only on a session's first exchange; never auto-regenerates.
    """
    if not session_id or not question:
        return
    try:
        prompt = TITLE_GEN_PROMPT.format(
            question=question[:500],
            answer_preview=(answer or "")[:300],
        )
        resp = llm.invoke(prompt)
        title = (resp.content or "").strip()
        # Sanitize: strip enclosing quotes, trailing punctuation
        title = title.strip('"\'`').strip()
        title = title.rstrip(".!?,;: ")
        # Sanity guards: keep within DB column constraint, never write empty
        if not title or len(title) > 80:
            return
        update_session_title(session_id, title)
    except Exception as e:
        print(f"[main] auto-title failed for {session_id}: {e}")


# ── CHAT ENDPOINT ──────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    timestamp = datetime.now().isoformat()
    llm       = get_llm()

    session_id = request.session_id

    # Validate any incoming session_id; treat as fresh if not found
    if session_id:
        try:
            if not get_session(session_id):
                session_id = None
        except Exception:
            session_id = None

    # Create a session inline if we still don't have one
    session_was_just_created = False
    if not session_id:
        try:
            sess       = create_session(title=question[:80])
            session_id = sess["session_id"]
            session_was_just_created = True
        except Exception:
            import uuid
            session_id = str(uuid.uuid4())
            session_was_just_created = True

    # ── Detect "first exchange" (for auto-title generation) ──
    # True if we just created the session inline, OR if the session existed
    # (e.g., from POST /sessions) but had no prior messages. This catches
    # the "+ New Chat" → first-message path that previously left titles
    # stuck on "New Chat".
    is_first_exchange = session_was_just_created
    if not is_first_exchange:
        try:
            prior_messages = get_session_messages(session_id)
            is_first_exchange = (len(prior_messages) == 0)
        except Exception:
            pass

    _try_save_message(session_id, "user", question)

    # Phase 4 warm-up: pass session_id so the router knows about uploaded PDFs
    route_result = classify_question(question, llm, session_id=session_id)
    route        = route_result["route"]

    sql_result    = {}
    rag_result    = {}
    core_result   = {}
    final_answer  = ""
    pipeline_used = route
    response_type = "answer"
    chart_hint    = "none"

    # Phase 4d state — surfaced in ChatResponse
    core_attempted = False
    core_matched   = False
    core_fallnote  = None
    core_sources   = None

    try:
        # ── Phase 4d: try core_recall first if routed there ──
        if route == "core_recall":
            core_attempted = True
            core_result    = run_core_recall_pipeline(
                question, llm, user_id=CURRENT_USER_ID
            )

            if core_result.get("matched"):
                core_matched  = True
                final_answer  = core_result.get("answer", "")
                core_sources  = core_result.get("sources", [])
                pipeline_used = "core_recall"
                response_type = core_result.get("response_type", "answer")
            else:
                # Fall through to normal classification (sql/rag/both)
                core_fallnote = core_result.get("answer") or (
                    "Nothing in your saved core matched this — answering live instead."
                )
                from routers.query_router import route_with_llm
                pdf_filenames = []
                try:
                    from db.session_store import list_uploads
                    pdf_filenames = [u["filename"] for u in list_uploads(session_id)
                                     if u.get("target") == "rag"]
                except Exception:
                    pass
                fallback_route = route_with_llm(question, llm, pdf_filenames=pdf_filenames)
                if fallback_route == "core_recall":
                    fallback_route = "sql"
                route = fallback_route.value if hasattr(fallback_route, "value") else fallback_route
                pipeline_used = f"core_recall→{route}"

        # ── Standard pipelines ──
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

        if not core_matched:
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
            elif route == "rag":
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
        # Phase 4d artifacts
        if core_sources:
            _try_save_artifact(asst_msg_id, "core_sources", core_sources)
        if core_fallnote:
            _try_save_artifact(asst_msg_id, "core_fallthrough_note", core_fallnote)

    _try_touch(session_id)

    # ── Auto session title (v2.9.1) ──
    # Fires AFTER the first exchange completes. Sets a safety-net placeholder
    # from the question, then upgrades to a clean LLM-summarized title.
    # Best-effort: either step can fail without breaking the chat.
    if is_first_exchange:
        try:
            update_session_title(session_id, question[:80])
        except Exception:
            pass
        _try_generate_session_title(session_id, question, final_answer, llm)

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
        core_recall_attempted = core_attempted,
        core_recall_matched   = core_matched,
        core_fallthrough_note = core_fallnote,
        core_sources          = core_sources,
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


@app.patch("/sessions/{session_id}/topic")
async def set_session_topic(session_id: str, body: SessionTopicRequest):
    """
    Phase 4e: assign a session to a topic, or move it to Unsorted.

    Body forms:
      {"topic_id": "top_abc..."}    → assign to that topic
      {"topic_id": "__none__"}      → move to Unsorted
      {"clear_topic": true}         → move to Unsorted (alias)
    """
    existing = get_session(session_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Session not found")

    target = body.topic_id
    if body.clear_topic or target in ("", "__none__"):
        target = None

    try:
        ok = update_session_topic(session_id, target)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not ok:
        raise HTTPException(status_code=500, detail="Could not update session topic")

    return {"status": "updated", "session_id": session_id, "topic_id": target}


@app.delete("/sessions/{session_id}")
async def remove_session(session_id: str):
    try:
        deleted = delete_session(session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        delete_session_db(session_id)
    except Exception as e:
        print(f"[main] cascade: delete_session_db failed for {session_id}: {e}")

    try:
        n_deleted = delete_session_vectors(session_id)
        if n_deleted:
            print(f"[main] cascade: deleted {n_deleted} vectors for {session_id}")
    except Exception as e:
        print(f"[main] cascade: delete_session_vectors failed for {session_id}: {e}")

    return {"status": "deleted", "session_id": session_id}


# ── CORE SAVE ENDPOINTS (Phase 4b-2) ───────────────────────

def _build_message_snapshot(message_id: str) -> dict:
    from db.session_store import _get_conn
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
    up = get_upload(upload_id)
    if not up:
        raise HTTPException(status_code=404, detail=f"Upload {upload_id} not found")

    filename = up.get("filename", "(file)")
    summary  = up.get("summary")

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
    kind = (body.kind or "").strip()
    if kind not in ("message", "upload"):
        raise HTTPException(status_code=400, detail="kind must be 'message' or 'upload'")
    if not body.source_id:
        raise HTTPException(status_code=400, detail="source_id is required")

    if kind == "message":
        snap = _build_message_snapshot(body.source_id)
        # Phase 4e: inherit the session's topic if it has one assigned
        inherited_topic = _inherit_session_topic(snap.get("source_session_id"))
        try:
            save_id = create_save(
                user_id           = CURRENT_USER_ID,
                kind              = "message",
                title             = snap["title"],
                content           = snap["content"],
                metadata_json     = snap["metadata"],
                note              = body.note,
                topic_id          = inherited_topic,
                source_session_id = snap["source_session_id"],
                source_message_id = body.source_id,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Save failed: {e}")
    else:
        snap = _build_upload_snapshot(body.source_id)
        # Phase 4e: inherit the session's topic for uploads too
        inherited_topic = _inherit_session_topic(snap.get("source_session_id"))
        try:
            save_id = create_save(
                user_id           = CURRENT_USER_ID,
                kind              = "upload",
                title             = snap["title"],
                content           = snap["content"],
                metadata_json     = snap["metadata"],
                note              = body.note,
                topic_id          = inherited_topic,
                source_session_id = snap["source_session_id"],
                source_upload_id  = body.source_id,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Save failed: {e}")

    existing = get_save(save_id)
    if existing and not existing.get("embedding_json"):
        _try_embed_save(save_id, snap["content"])

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


# ── CORE TOPIC / DATA ENDPOINTS (Phase 4c) ─────────────────

@app.get("/core/topics")
async def core_list_topics():
    try:
        topics = list_topics(CURRENT_USER_ID)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    try:
        unsorted = list_saves(CURRENT_USER_ID, topic_id="__none__")
        unsorted_count = len(unsorted)
    except Exception:
        unsorted_count = 0

    try:
        total = count_saves()
    except Exception:
        total = 0

    return {
        "topics":         topics,
        "unsorted_count": unsorted_count,
        "total_count":    total,
    }


@app.post("/core/topics")
async def core_create_topic(body: TopicCreateRequest):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Topic name cannot be empty")
    try:
        topic_id = create_topic(CURRENT_USER_ID, name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "created", "topic_id": topic_id, "name": name}


@app.patch("/core/topics/{topic_id}")
async def core_rename_topic(topic_id: str, body: TopicRenameRequest):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Topic name cannot be empty")
    try:
        ok = rename_topic(topic_id, name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"status": "renamed", "topic_id": topic_id, "name": name}


@app.delete("/core/topics/{topic_id}")
async def core_delete_topic(topic_id: str):
    try:
        ok = delete_topic(topic_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"status": "deleted", "topic_id": topic_id}


@app.get("/core/saves/list")
async def core_saves_list(topic_id: Optional[str] = None):
    try:
        saves = list_saves(CURRENT_USER_ID, topic_id=topic_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"saves": saves, "count": len(saves)}


@app.patch("/core/saves/{save_id}")
async def core_update_save(save_id: str, body: SaveUpdateRequest):
    existing = get_save(save_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Save not found")

    target_topic = existing.get("topic_id")
    if body.clear_topic or body.topic_id in ("", "__none__"):
        target_topic = None
    elif body.topic_id is not None:
        target_topic = body.topic_id

    try:
        update_save_topic(save_id, target_topic, note=body.note)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "updated", "save_id": save_id, "topic_id": target_topic}


@app.delete("/core/saves/{save_id}")
async def core_archive_save(save_id: str):
    existing = get_save(save_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Save not found")
    try:
        ok = archive_save(save_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "archived" if ok else "already_archived", "save_id": save_id}


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

    try:
        stats["user_count"]  = count_users()
        stats["topic_count"] = count_topics()
        stats["save_count"]  = count_saves()
    except Exception as e:
        print(f"[main] stats core counts failed: {e}")

    try:
        stats["saves_needing_embedding"] = len(list_saves_needing_embedding(CURRENT_USER_ID))
    except Exception:
        pass

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
