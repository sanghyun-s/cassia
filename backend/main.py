"""
=============================================================
CASSIA — FastAPI Backend  (Phase 5b/c: auth-required everywhere)
=============================================================

Project rebrand:
  CoReckoner → CASSIA (Chat-based Accounting System for SQL, Search,
  Insight & Analysis). Backend identifier (db filename, cookie name)
  stays as coreckoner.db / cassia_session respectively.

v2.12.1 — Phase 5b/c (this version):
  - Every user-data endpoint now requires authentication via
    get_current_user. Unauthenticated requests return 401.
  - CURRENT_USER_ID global removed; user_id flows from the request
    cookie through to every persistence call.
  - Ownership checks: every per-session, per-upload, per-topic, per-save
    endpoint calls a small _assert_*_owned_by helper that returns 404
    (NOT 403) when the resource doesn't belong to the caller. 404
    prevents leaking the existence of resources owned by other users.
  - CORS hardened: allow_origins=["http://localhost:8002"],
    allow_credentials=True. Cookie auth requires explicit origin —
    wildcard origins reject credentialed requests.
  - Bcrypt "trapped error reading bcrypt version" startup warning
    silenced via a one-line passlib log filter. Cosmetic only;
    functionality is unaffected.
  - Banner bumped to v2.12.1.

Previous v2.10.1 highlights kept intact:
  - Phase 4d core recall, Phase 4e topic-grouped sessions,
    auto-titles, chart fix.

This file is the largest single edit in Phase 5b/c — the auth
dependency lands on ~17 endpoints. Routes that DON'T require auth:
  - GET /            (serves the HTML; HTML drives the login flow)
  - GET /health      (status probe)
  - GET /schema      (read-only accounting demo schema)
  - GET /stats       (read-only diagnostic counts)
  - All /auth/*      (login endpoints themselves)
  - /static/*        (CSS/JS assets)
"""

import os
import json
from utils.json_safe import safe_json_dumps
import logging
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI

from auth import User, get_current_user
from routers.query_router  import classify_question
from routers.upload_router import router as upload_router
from routers.auth_router   import router as auth_router

from db.auth_migrations import migrate as auth_migrate
from pipelines.sql_pipeline         import run_sql_pipeline, get_db_connection, get_schema
from pipelines.rag_pipeline         import run_rag_pipeline
from pipelines.core_recall_pipeline import run_core_recall_pipeline
from pipelines.core_embed           import embed_text
from pipelines.chart_builder        import build_chart_spec

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
    session_belongs_to_user,
    upload_belongs_to_user,
    topic_belongs_to_user,
    save_belongs_to_user,
    ensure_default_user,
    count_users,
    count_topics,
    count_saves,
    DEFAULT_USER_ID,
    get_session_messages,
    get_message_artifacts,
    get_upload,
    create_save,
    get_save,
    find_save_by_source,
    create_topic,
    list_topics,
    rename_topic,
    delete_topic,
    list_saves,
    update_save_topic,
    archive_save,
    update_save_embedding,
    list_saves_needing_embedding,
)
from uploads.session_db import delete_session_db
from uploads.document   import delete_session_vectors

load_dotenv()

# ── Silence the cosmetic bcrypt-version warning at startup ──
# bcrypt 5.x removed __about__ which passlib 1.7.4 reads. The error is
# caught and re-raised as a log message — functionality is fine. We
# raise passlib's log level to ERROR so the trapped-version line stops
# printing on every server boot.
logging.getLogger("passlib").setLevel(logging.ERROR)


PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH      = PROJECT_ROOT / "outputs" / "accounting.db"
CHROMA_DIR   = PROJECT_ROOT / "outputs" / "chroma_db"


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n" + "═" * 52)
    print("  CASSIA — Accounting AI Chatbot")
    print("  v2.12.1 · Phase 5b/c (auth-required)")
    print("═" * 52)
    try:
        init_db()
        print("  ✓ coreckoner.db initialised")
    except Exception as e:
        print(f"  ⚠ coreckoner.db init failed: {e}")

    try:
        auth_migrate()
        print("  ✓ auth migrations applied")
    except Exception as e:
        print(f"  ⚠ auth migrations failed: {e}")

    try:
        ensure_default_user()
        print(f"  ✓ default user ensured (tombstone)")
    except Exception as e:
        print(f"  ⚠ ensure_default_user failed: {e}")

    if not os.getenv("OPENAI_API_KEY"):
        print("  ❌ OPENAI_API_KEY not found")
    else:
        print("  ✓ OpenAI API key loaded")

    if not os.getenv("SIGNUP_INVITE_CODE"):
        print("  ⚠ SIGNUP_INVITE_CODE not set — signup will be disabled")
    else:
        print("  ✓ Invite code configured")

    print(f"  {'✓' if DB_PATH.exists()    else '⚠'} accounting.db  {'found' if DB_PATH.exists()    else 'NOT found'}")
    print(f"  {'✓' if CHROMA_DIR.exists() else '⚠'} chroma_db     {'found' if CHROMA_DIR.exists() else 'NOT found'}")

    print("═" * 52)
    print("  Chat UI:  http://localhost:8002")
    print("  API docs: http://localhost:8002/docs")
    print("═" * 52 + "\n")
    yield
    print("\nShutting down CASSIA.")


app = FastAPI(
    title       = "CASSIA — Accounting AI Chatbot",
    description = "Hybrid RAG + Text-to-SQL with persistent sessions, uploads, core recall, multi-user auth",
    version     = "2.12.1",
    lifespan    = lifespan,
)

# ── CORS — Phase 5b/c hardened ──────────────────────────────
# Cookie-based auth requires:
#   - allow_credentials=True  (so browser sends our HttpOnly cookie)
#   - allow_origins to be an explicit list (NOT "*") because browsers
#     refuse to send credentials to wildcard origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["http://localhost:8002"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

app.include_router(upload_router)
app.include_router(auth_router)

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
    core_recall_attempted: bool          = False
    core_recall_matched:   bool          = False
    core_fallthrough_note: Optional[str] = None
    core_sources:          Optional[list] = None
    timestamp:         str


class SessionRenameRequest(BaseModel):
    title: str


class SessionTopicRequest(BaseModel):
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
    topic_id:          Optional[str] = None
    note:              Optional[str] = None
    clear_topic:       bool          = False
    also_move_session: bool          = False


# ── Ownership-check helpers ────────────────────────────────
# Each one raises 404 on mismatch — 404 (not 403) so the caller cannot
# discover whether a resource exists for some other user.

def _assert_session_owned_by(session_id: str, user_id: str) -> None:
    if not session_belongs_to_user(session_id, user_id):
        raise HTTPException(status_code=404, detail="Session not found")


def _assert_upload_owned_by(upload_id: str, user_id: str) -> None:
    if not upload_belongs_to_user(upload_id, user_id):
        raise HTTPException(status_code=404, detail="Upload not found")


def _assert_topic_owned_by(topic_id: str, user_id: str) -> None:
    if not topic_belongs_to_user(topic_id, user_id):
        raise HTTPException(status_code=404, detail="Topic not found")


def _assert_save_owned_by(save_id: str, user_id: str) -> None:
    if not save_belongs_to_user(save_id, user_id):
        raise HTTPException(status_code=404, detail="Save not found")


# ── Misc helpers ───────────────────────────────────────────

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
    if not save_id or not text:
        return
    try:
        vec  = embed_text(text)
        vstr = safe_json_dumps(vec)
        update_save_embedding(save_id, vstr)
    except Exception as e:
        print(f"[main] embed-on-save failed for {save_id}: {e}")


def _inherit_session_topic(source_session_id: str | None) -> str | None:
    if not source_session_id:
        return None
    try:
        sess = get_session(source_session_id)
        if sess and sess.get("topic_id"):
            return sess["topic_id"]
    except Exception as e:
        print(f"[main] inherit-session-topic failed: {e}")
    return None


# ── Auto session titles ────────────────────────────────────

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
    if not session_id or not question:
        return
    try:
        prompt = TITLE_GEN_PROMPT.format(
            question=question[:500],
            answer_preview=(answer or "")[:300],
        )
        resp = llm.invoke(prompt)
        title = (resp.content or "").strip()
        title = title.strip('"\'`').strip()
        title = title.rstrip(".!?,;: ")
        if not title or len(title) > 80:
            return
        update_session_title(session_id, title)
    except Exception as e:
        print(f"[main] auto-title failed for {session_id}: {e}")


# ── CHAT ENDPOINT ──────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
async def chat(
    request:      ChatRequest,
    current_user: User = Depends(get_current_user),
):
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    timestamp = datetime.now().isoformat()
    llm       = get_llm()

    session_id = request.session_id

    # Validate any incoming session_id: must exist AND be owned by caller.
    # If either check fails, we treat it as a fresh session — same external
    # behavior as v2.10.1 but with ownership enforced.
    if session_id:
        try:
            if not session_belongs_to_user(session_id, current_user.user_id):
                session_id = None
        except Exception:
            session_id = None

    session_was_just_created = False
    if not session_id:
        try:
            sess       = create_session(user_id=current_user.user_id, title=question[:80])
            session_id = sess["session_id"]
            session_was_just_created = True
        except Exception:
            import uuid
            session_id = str(uuid.uuid4())
            session_was_just_created = True

    is_first_exchange = session_was_just_created
    if not is_first_exchange:
        try:
            prior_messages = get_session_messages(session_id)
            is_first_exchange = (len(prior_messages) == 0)
        except Exception:
            pass

    _try_save_message(session_id, "user", question)

    route_result = classify_question(question, llm, session_id=session_id)
    route        = route_result["route"]

    sql_result    = {}
    rag_result    = {}
    core_result   = {}
    final_answer  = ""
    pipeline_used = route
    response_type = "answer"
    chart_hint    = "none"

    core_attempted = False
    core_matched   = False
    core_fallnote  = None
    core_sources   = None

    try:
        if route == "core_recall":
            core_attempted = True

            # v2 stabilization: hard timeout on Core Recall to prevent
            # hangs like Sim 3's 5-minute embedding wait. On timeout or
            # unexpected error, return a controlled user-visible message
            # (matched=True so the message becomes the final answer).
            import concurrent.futures as _cf
            try:
                with _cf.ThreadPoolExecutor(max_workers=1) as _ex:
                    _future = _ex.submit(
                        run_core_recall_pipeline, question, llm,
                        user_id=current_user.user_id,
                    )
                    core_result = _future.result(timeout=30.0)
            except _cf.TimeoutError:
                print("[core_recall] timeout after 30s — returning fallback")
                core_result = {
                    "pipeline":      "core_recall",
                    "response_type": "answer",
                    "matched":       True,
                    "answer":        (
                        "Searching your saved work is taking longer than "
                        "expected. Please try rephrasing your question, or "
                        "try again in a moment."
                    ),
                    "sources":    [],
                    "chart_hint": "none",
                    "sql":        None,
                    "raw_data":   [],
                    "columns":    [],
                }
            except Exception as _e:
                print(f"[core_recall] error: {_e}")
                core_result = {
                    "pipeline":      "core_recall",
                    "response_type": "answer",
                    "matched":       True,
                    "answer":        (
                        "I couldn't search your saved work right now. "
                        "Please try again in a moment."
                    ),
                    "sources":    [],
                    "chart_hint": "none",
                    "sql":        None,
                    "raw_data":   [],
                    "columns":    [],
                }

            if core_result.get("matched"):
                core_matched  = True
                final_answer  = core_result.get("answer", "")
                core_sources  = core_result.get("sources", [])
                pipeline_used = "core_recall"
                response_type = core_result.get("response_type", "answer")
            else:
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

        if route in ("sql", "both"):
            sql_result = run_sql_pipeline(question, llm, DB_PATH, session_id=session_id)
            response_type = sql_result.get("response_type", "answer")
            chart_hint    = sql_result.get("chart_hint", "none")

        if route in ("rag", "both"):
            rag_result = run_rag_pipeline(
                question, llm, CHROMA_DIR,
                session_id=session_id,
                user_id=current_user.user_id,
            )
            if route == "rag":
                response_type = rag_result.get("response_type", "answer")

        if not core_matched:
            if route == "both":
                sql_ans = sql_result.get("answer", "")
                rag_ans = rag_result.get("answer", "")

                # v2 stabilization: detect SQL stubs/errors so they're
                # not passed to the synthesizer as evidence
                _sql_lower = str(sql_ans).lower()
                _sql_unusable_patterns = (
                    "no uploaded data",
                    "this data is not in the uploaded files",
                    "this data isn't in the demo tables",
                    "execution failed",
                    "only one sql statement",
                    "no such column",
                    "no such table",
                    "selects to the left and right of union",
                    "syntax error",
                    "the query execution failed",
                    "the query could not be executed",
                )
                sql_unusable = (
                    not sql_ans
                    or any(p in _sql_lower for p in _sql_unusable_patterns)
                )

                if sql_unusable:
                    # SQL portion failed or returned a stub — synthesize
                    # from RAG alone with explicit instruction not to leak
                    # technical error text or claim no data exists
                    merge = llm.invoke(
                        f"Answer the user's question below using only the "
                        f"policy/guidance content provided. The structured-"
                        f"data retrieval for this question failed or returned "
                        f"no usable result. Do NOT claim 'there is no uploaded "
                        f"data' or quote any technical SQL error text — just "
                        f"answer from the policy content if it's sufficient, "
                        f"or briefly acknowledge you couldn't form a reliable "
                        f"data query and ask the user to specify the table, "
                        f"amount, or comparison target.\n\n"
                        f"Question: {question}\n\n"
                        f"POLICY ANSWER: {rag_ans}\n\n"
                        f"Write a unified 3-5 sentence answer."
                    )
                else:
                    merge = llm.invoke(
                        f"Combine these two answers into one clear response:\n\n"
                        f"DATA ANSWER: {sql_ans}\n"
                        f"POLICY ANSWER: {rag_ans}\n\n"
                        f"Write a unified 3-5 sentence answer addressing both numbers and policy context."
                    )
                final_answer  = merge.content.strip()
                response_type = "answer"
            elif route == "sql":
                # P2b stabilization: guard the SQL-only route the same way
                # the BOTH route is guarded. If the SQL pipeline returned a
                # stub or leaked an execution error, replace it with a clean
                # fallback instead of surfacing raw SQLite text to the user
                # (Phase 6 Sim 4 / Image 4 Oracle UNION "no such column").
                _sql_only_ans   = sql_result.get("answer", "")
                _sql_only_lower = str(_sql_only_ans).lower()
                _p2b_unusable_patterns = (
                    "no uploaded data",
                    "this data is not in the uploaded files",
                    "this data isn't in the demo tables",
                    "execution failed",
                    "only one sql statement",
                    "no such column",
                    "no such table",
                    "selects to the left and right of union",
                    "syntax error",
                    "the query execution failed",
                    "the query could not be executed",
                )
                _p2b_unusable = (
                    not _sql_only_ans
                    or any(p in _sql_only_lower for p in _p2b_unusable_patterns)
                )
                if _p2b_unusable:
                    final_answer = (
                        "I couldn't form a reliable data query. Could you "
                        "specify which table, amount, or comparison target "
                        "you'd like me to look at?"
                    )
                    response_type = "answer"
                else:
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
            _try_save_artifact(asst_msg_id, "chart_spec", build_chart_spec(
                columns    = sql_result.get("columns", []),
                rows       = sql_result.get("raw_data", []),
                question   = question,
                chart_hint = chart_hint,
            ))
        if core_sources:
            _try_save_artifact(asst_msg_id, "core_sources", core_sources)
        if core_fallnote:
            _try_save_artifact(asst_msg_id, "core_fallthrough_note", core_fallnote)

    _try_touch(session_id)

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
async def list_sessions(current_user: User = Depends(get_current_user)):
    try:
        sessions = get_all_sessions(current_user.user_id)
        return {"sessions": sessions, "count": len(sessions)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sessions")
async def new_session(current_user: User = Depends(get_current_user)):
    try:
        return create_session(user_id=current_user.user_id, title="New Chat")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions/{session_id}")
async def get_full_session(
    session_id:   str,
    current_user: User = Depends(get_current_user),
):
    _assert_session_owned_by(session_id, current_user.user_id)
    try:
        session = get_session_with_messages(session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.patch("/sessions/{session_id}")
async def rename_session(
    session_id:   str,
    body:         SessionRenameRequest,
    current_user: User = Depends(get_current_user),
):
    if not body.title or not body.title.strip():
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    _assert_session_owned_by(session_id, current_user.user_id)
    try:
        update_session_title(session_id, body.title.strip())
        return {"session_id": session_id, "title": body.title.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/sessions/{session_id}/topic")
async def set_session_topic(
    session_id:   str,
    body:         SessionTopicRequest,
    current_user: User = Depends(get_current_user),
):
    _assert_session_owned_by(session_id, current_user.user_id)

    target = body.topic_id
    if body.clear_topic or target in ("", "__none__"):
        target = None

    # If assigning to a topic, verify the topic also belongs to this user
    if target is not None:
        _assert_topic_owned_by(target, current_user.user_id)

    try:
        ok = update_session_topic(session_id, target)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not ok:
        raise HTTPException(status_code=500, detail="Could not update session topic")

    return {"status": "updated", "session_id": session_id, "topic_id": target}


@app.delete("/sessions/{session_id}")
async def remove_session(
    session_id:   str,
    current_user: User = Depends(get_current_user),
):
    _assert_session_owned_by(session_id, current_user.user_id)
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


# ── CORE SAVE ENDPOINTS ────────────────────────────────────

def _build_message_snapshot(message_id: str, user_id: str) -> dict:
    """
    Build a snapshot for saving a message. Verifies that the source
    message lives in a session owned by the caller — prevents user A
    from saving user B's message content into their own core.
    """
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

    # Ownership check via session
    if not session_belongs_to_user(msg["session_id"], user_id):
        raise HTTPException(status_code=404, detail=f"Message {message_id} not found")

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


def _build_upload_snapshot(upload_id: str, user_id: str) -> dict:
    """
    Build a snapshot for saving an upload. Verifies the upload belongs
    to the caller.
    """
    up = get_upload(upload_id)
    if not up:
        raise HTTPException(status_code=404, detail=f"Upload {upload_id} not found")

    if up.get("user_id") != user_id:
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
async def core_save(
    body:         CoreSaveRequest,
    current_user: User = Depends(get_current_user),
):
    kind = (body.kind or "").strip()
    if kind not in ("message", "upload"):
        raise HTTPException(status_code=400, detail="kind must be 'message' or 'upload'")
    if not body.source_id:
        raise HTTPException(status_code=400, detail="source_id is required")

    if kind == "message":
        snap = _build_message_snapshot(body.source_id, current_user.user_id)
        inherited_topic = _inherit_session_topic(snap.get("source_session_id"))
        try:
            save_id = create_save(
                user_id           = current_user.user_id,
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
        snap = _build_upload_snapshot(body.source_id, current_user.user_id)
        inherited_topic = _inherit_session_topic(snap.get("source_session_id"))
        try:
            save_id = create_save(
                user_id           = current_user.user_id,
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
async def core_saves(
    source_message_id: Optional[str] = None,
    source_upload_id:  Optional[str] = None,
    current_user:      User = Depends(get_current_user),
):
    if not source_message_id and not source_upload_id:
        raise HTTPException(
            status_code=400,
            detail="Provide source_message_id or source_upload_id",
        )
    found = find_save_by_source(
        current_user.user_id,
        source_message_id=source_message_id,
        source_upload_id=source_upload_id,
    )
    return {
        "saved":   bool(found),
        "save_id": found["save_id"] if found else None,
    }


# ── CORE TOPIC / DATA ENDPOINTS ────────────────────────────

@app.get("/core/topics")
async def core_list_topics(current_user: User = Depends(get_current_user)):
    try:
        topics = list_topics(current_user.user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    try:
        unsorted = list_saves(current_user.user_id, topic_id="__none__")
        unsorted_count = len(unsorted)
    except Exception:
        unsorted_count = 0

    try:
        all_saves = list_saves(current_user.user_id)
        total = len(all_saves)
    except Exception:
        total = 0

    return {
        "topics":         topics,
        "unsorted_count": unsorted_count,
        "total_count":    total,
    }


@app.post("/core/topics")
async def core_create_topic(
    body:         TopicCreateRequest,
    current_user: User = Depends(get_current_user),
):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Topic name cannot be empty")
    try:
        topic_id = create_topic(current_user.user_id, name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "created", "topic_id": topic_id, "name": name}


@app.patch("/core/topics/{topic_id}")
async def core_rename_topic(
    topic_id:     str,
    body:         TopicRenameRequest,
    current_user: User = Depends(get_current_user),
):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Topic name cannot be empty")
    _assert_topic_owned_by(topic_id, current_user.user_id)
    try:
        ok = rename_topic(topic_id, name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"status": "renamed", "topic_id": topic_id, "name": name}


@app.delete("/core/topics/{topic_id}")
async def core_delete_topic(
    topic_id:     str,
    current_user: User = Depends(get_current_user),
):
    _assert_topic_owned_by(topic_id, current_user.user_id)
    try:
        ok = delete_topic(topic_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not ok:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"status": "deleted", "topic_id": topic_id}


@app.get("/core/saves/list")
async def core_saves_list(
    topic_id:     Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    try:
        saves = list_saves(current_user.user_id, topic_id=topic_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"saves": saves, "count": len(saves)}


@app.patch("/core/saves/{save_id}")
async def core_update_save(
    save_id:      str,
    body:         SaveUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    _assert_save_owned_by(save_id, current_user.user_id)
    existing = get_save(save_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Save not found")

    target_topic = existing.get("topic_id")
    if body.clear_topic or body.topic_id in ("", "__none__"):
        target_topic = None
    elif body.topic_id is not None:
        # Verify target topic also belongs to this user
        _assert_topic_owned_by(body.topic_id, current_user.user_id)
        target_topic = body.topic_id

    try:
        update_save_topic(save_id, target_topic, note=body.note)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Pass 5 (Stream B polish): opt-in ripple — when also_move_session=True,
    # also move the originating chat session to the same topic. Silent skip
    # if the save has no source_session_id (e.g. upload saves) or the source
    # session no longer exists / no longer belongs to the user.
    session_also_moved = False
    if body.also_move_session:
        source_session_id = existing.get("source_session_id")
        if source_session_id and session_belongs_to_user(source_session_id, current_user.user_id):
            try:
                if update_session_topic(source_session_id, target_topic):
                    session_also_moved = True
            except Exception as e:
                print(f"[main] also_move_session ripple failed for {source_session_id}: {e}")

    return {
        "status":             "updated",
        "save_id":            save_id,
        "topic_id":           target_topic,
        "session_also_moved": session_also_moved,
    }


@app.delete("/core/saves/{save_id}")
async def core_archive_save(
    save_id:      str,
    current_user: User = Depends(get_current_user),
):
    _assert_save_owned_by(save_id, current_user.user_id)
    try:
        ok = archive_save(save_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "archived" if ok else "already_archived", "save_id": save_id}


# ── SUPPORTING ENDPOINTS (unauthenticated) ─────────────────

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
    """Read-only demo schema; no user data exposed."""
    if not DB_PATH.exists():
        raise HTTPException(status_code=503, detail="accounting.db not found")
    conn = get_db_connection(DB_PATH)
    schema = get_schema(conn)
    conn.close()
    return {"schema": schema}


@app.get("/stats")
async def get_stats():
    """Diagnostic counts only. No per-user data exposed."""
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
        stats["user_count"]  = count_users()
        stats["topic_count"] = count_topics()
        stats["save_count"]  = count_saves()
    except Exception as e:
        print(f"[main] stats core counts failed: {e}")

    return stats


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """
    Serves the single-page UI. The UI itself calls /auth/me on load
    and decides whether to render the chat or the login screen, so
    this endpoint is intentionally unauthenticated.
    """
    ui_path = static_dir / "index.html"
    if ui_path.exists():
        return FileResponse(str(ui_path))
    return HTMLResponse("<h2>Chat UI not found.</h2>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=False)
