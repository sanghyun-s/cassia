# CASSIA — Chat-based Accounting System

**Chat-based Accounting System for SQL, Search, Insight & Analysis**

An AI accounting assistant that answers plain-English questions about both
unstructured documents (IRS publications, uploaded PDFs) and structured
financial data (QuickBooks-style exports), with persistent multi-session
chat, per-session file uploads, semantic recall of saved answers, and
invite-only multi-user authentication with per-user data isolation.

> Built as a portfolio project to demonstrate hybrid RAG + Text-to-SQL
> orchestration, vector-grounded retrieval, conversational LLM integration,
> and production-grade engineering practices (idempotent migrations,
> phased delivery, dev notes, defense-in-depth multi-user data isolation).

> *Previously developed under the working name CoReckoner. Renamed to
> CASSIA during Phase 5 to better reflect the architecture.*

---

## Status

Phases 1–5 complete and verified end-to-end. Currently running **v2.12.1**.
Phase 6 (business case simulation testing) queued.

| Phase | Capability | Status |
|------|------------|--------|
| 1–2  | Hybrid RAG + Text-to-SQL with router classification | ✅ shipped |
| 3    | Per-session uploads (CSV / Excel / PDF) | ✅ shipped |
| 4a–c | Persistent sessions, save-to-core, topic organization | ✅ shipped |
| 4d   | Natural-language recall of saved answers | ✅ shipped |
| 4e   | Topic-grouped sidebar, auto-generated session titles, chart fix | ✅ shipped |
| 5a   | Auth foundation — signup, login, sessions, bcrypt | ✅ shipped |
| 5b/c | Endpoint scoping, login UI, CASSIA rename | ✅ shipped |
| 5c Pass 3 | ChromaDB user isolation (vector metadata + filter) | ✅ shipped |
| 5 polish | "Also move source session" checkbox | ✅ shipped |
| 6    | Systematic business-case simulation testing | ⏳ queued |

---

## What it does

Ask plain-English questions and get answers grounded in real data.

**Structured financial queries** (Text-to-SQL over the demo accounting DB):
> *"What's our net income for Q1 2026?"* → SQL query → table + chart + plain-English explanation

**Policy and regulation lookup** (RAG over IRS publications):
> *"What is the penalty for late payroll tax deposits?"* → cited excerpts from IRS Pub 15 with page numbers

**Hybrid questions** (router blends both):
> *"What's our overdue AP balance and what does the IRS say about it?"* → SQL result + RAG citations, merged into a unified answer

**Document upload + grounded Q&A** (per-session, per-user ChromaDB):
> Upload Apple's 10-K PDF, then ask *"What was Apple's total net sales in FY 2024?"* → answer cites the uploaded document and page number; only the uploading user sees the chunks

**Save important answers to your permanent core**:
> Click 💾 on any answer or upload → it becomes permanently recallable across all future sessions

**Recall by natural language** (semantic search over saves):
> *"What did I save about net income?"* → returns your saved Q1 analysis with relevance scores, even months later in a different session

**Multi-user with per-user isolation:**
> Invite-only signup; every session, save, upload, and vector belongs to a single user. Defense in depth at both the API layer and the vector store layer.

**Multilingual**:
> *"1월 매출이 얼마야?"* → answers in Korean, generates a Korean session title

---

## Architecture

```
                                USER QUESTION (via authenticated session)
                                          │
                                          ▼
              QUERY ROUTER  (history-aware, PDF-aware, recall-aware)
              • trigger phrases   → CORE_RECALL (deterministic)
              • LLM classifies    → SQL / RAG / BOTH / CORE_RECALL
                       │                                  │
            ┌──────────┘                                  └──────────┐
            ▼                                                        ▼
      TEXT-TO-SQL                                              RAG PIPELINE
      schema-grounded SQL                                      dual-collection retrieval
      over accounting.db +                                     • irs_pub15  (global)
      per-session uploads                                      • user_uploads
            │                                                    (session + user filtered)
            │     ┌─── CORE RECALL ─────────────┐                 │
            │     │ embed question              │                 │
            │     │ cosine over saves           │                 │
            │     │ threshold 0.35, top-5       │                 │
            │     │ LLM cites saved titles+date │                 │
            │     │ no match → fall through     │                 │
            │     └─────────────────────────────┘                 │
            ▼                                                     ▼
                              UNIFIED ANSWER
        text + Plotly chart (SQL) + citations (RAG) + sources (recall)
                                     │
                                     ▼
                  FastAPI on port 8002, behind auth dependency
       Dark-themed chat UI: login screen · topic-grouped sidebar ·
       💾 save · 🗄 My Core modal · "Also move source session" opt-in

   PERSISTENCE (SQLite — coreckoner.db)        AUTH (Phase 5a–c)
   ├─ sessions  (+user_id, topic_id)           ├─ users (bcrypt password_hash)
   ├─ messages  + artifacts                    ├─ auth_sessions (cookie tokens)
   ├─ uploads   (+user_id, summary_json)       └─ HttpOnly + SameSite cookies,
   ├─ core_topics (per user)                       30-day sliding renewal
   └─ core_saves (+ cached embeddings)
```

---

## Tech stack

| Layer | Choice |
|-------|--------|
| Backend framework | FastAPI (Python 3.13) |
| LLM | OpenAI `gpt-4o-mini` |
| Embeddings | OpenAI `text-embedding-3-small` |
| Vector DB | ChromaDB (persistent, two collections) |
| Relational DB | SQLite (separate `accounting.db` and `coreckoner.db`) |
| Auth | `passlib[bcrypt]` + server-side session cookies (HttpOnly, SameSite=Lax) |
| Frontend | Vanilla HTML / CSS / JS + Plotly.js |
| Orchestration | LangChain for prompt templates and document loaders |

**Design notes:**
- *Server-side session cookies, not JWT.* No token refresh, no localStorage,
  no blacklist machinery — simpler and safer for a known web frontend.
- *Two SQLite databases.* `accounting.db` is read-only demo data;
  `coreckoner.db` is persistence (sessions, messages, uploads, core saves,
  users, auth sessions). Never mix the two.
- *Two ChromaDB collections.* `irs_pub15` is shared reference content,
  globally readable. `user_uploads` is per-user, per-session for uploaded
  PDFs — every chunk carries `{session_id, user_id}` and queries apply both
  as a hard conjunction filter.
- *Defense in depth on user isolation.* The API layer verifies ownership
  before any query (Pass 2). The vector store also filters by `user_id`
  (Pass 3). Either is sufficient in practice; together they're robust
  against any single-layer bug.
- *Idempotent migrations.* Every schema change uses `_ensure_column` and
  `CREATE … IF NOT EXISTS`. Re-running on the same DB is a no-op.

---

## Quick start

### Prerequisites

- Python 3.13 (tested on macOS ARM)
- An OpenAI API key with access to `gpt-4o-mini` and `text-embedding-3-small`

### Setup

```bash
git clone https://github.com/sanghyun-s/accounting-ai-chatbot.git cassia
cd cassia

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install 'passlib[bcrypt]>=1.7.4' 'bcrypt>=4.0.1,<5.0.0'

cp .env.example .env
# Edit .env and set:
#   OPENAI_API_KEY=sk-...
#   SIGNUP_INVITE_CODE=<choose-your-own>
#   SESSION_LIFETIME_DAYS=30
#   COOKIE_SECURE=false
```

### One-time data preparation

```bash
# Build the relational DB from the seed CSVs
python3 sql/phase1_load.py

# Index the IRS publications into ChromaDB
python3 rag/phase1_ingest.py
```

### Run

```bash
python3 backend/main.py
```

Open `http://localhost:8002` — the login screen appears. Sign up with your
chosen invite code; the first real signup automatically claims any
pre-existing demo data.

The startup banner shows green checkmarks for each subsystem. If any
appear as warnings (⚠), the message tells you what's missing.

---

## How it works — by feature

### Hybrid routing

Each incoming question goes through a router that picks one of four paths:

- **SQL** — structured numeric or tabular question over the accounting DB
- **RAG** — policy, regulation, or factual question that should be grounded in documents
- **BOTH** — question with numeric and policy components (e.g. "what's our overdue AP and what does the IRS say about late deposits?")
- **CORE_RECALL** — question about something previously saved

Routing decisions come from a small LLM call plus a list of explicit trigger phrases for `CORE_RECALL` ("what did I save about…", "recall my…"). The router is also aware of which PDFs are uploaded into the current session, so it can prefer RAG when a relevant document is present. The same question can route differently depending on session context (e.g. "Apple net sales" routes to RAG in a session with the 10-K uploaded, but to SQL in a session without it).

### Text-to-SQL

The SQL pipeline ships a schema-grounded prompt that includes:
- The full table schema with column types
- Curated table-level descriptions (e.g. "profit_loss has NO date column — use month columns instead")
- Structural query patterns (trend over months, revenue breakdown, current ratio, AR aging)
- Few-shot examples for user-uploaded tables

Generated SQL runs against the demo accounting DB. If the user has uploaded CSV/Excel files into the current session, those tables are `ATTACH`ed as `user_data.<table_name>` so queries can blend demo and uploaded data.

Bar-chart results are defensively reordered descending by value so the chart and the data table always show the same meaningful order, regardless of whether the LLM included `ORDER BY`.

### RAG (Retrieval-Augmented Generation)

Two ChromaDB collections, queried in parallel:
1. **`irs_pub15`** — IRS Publication 15 (Circular E), 15-T (federal income tax withholding), 15-B (employer's tax guide to fringe benefits). Globally readable for all authenticated users.
2. **`user_uploads`** — per-session uploaded PDFs, tagged with both `session_id` AND `user_id`. Retrieval applies both as a hard conjunction filter, so even if a session_id ever leaked, the user_id check still blocks cross-user reads (Phase 5c Pass 3).

Each retrieval returns top-k chunks per collection, merges by similarity score, and returns the top-k overall. Citations include the source document and page number. All access to `user_uploads` is funneled through a single `_query_user_uploads()` helper that enforces the filter — bypassing it bypasses user isolation.

### Core saves and natural-language recall

Every assistant answer and every uploaded file can be saved to a permanent "core" via the 💾 button. Saves can be organized into user-defined topics that are shared with sessions (sessions and saves share the same topic namespace).

At save time, each item is embedded using `text-embedding-3-small` and the vector is cached. When the user later asks something like *"What did I save about Q1?"*, the recall pipeline:
1. Embeds the question
2. Computes cosine similarity against every active save
3. Returns top-5 above a threshold of 0.35
4. Has the LLM compose a grounded answer citing the saved titles and dates
5. If nothing matches, falls through to the normal RAG/SQL router with a visible "no recall match" banner

This is the project's flagship feature — your reasoning and analysis persist across sessions and become a private knowledge base.

### Multi-session chat with auto-titles

Sessions are persisted to SQLite. The first user+assistant exchange in a new session triggers a small `gpt-4o-mini` call to generate a 3-6 word title in the user's language (English, Korean, …). Manual rename overrides the auto-title. Set-once on first exchange; never auto-regenerated.

### Topic-grouped sidebar with optional ripple

Sessions can be assigned to a topic via the sidebar's 📁 menu. Topics share their namespace with core saves — moving a save to "Tax Q1" uses the same topic as a session assigned to "Tax Q1". Groups are collapsible; "Unsorted" is always shown last.

In My Core, moving a save's topic now has an opt-in checkbox: **"Also move source session"**. Unchecked by default (preserves the independence model). Checked → both the save and its originating chat session move to the same topic in a single gesture (Phase 5 polish).

### Authentication

Server-side session cookies via `passlib[bcrypt]`:

- **`POST /auth/signup`** — invite-only (requires `SIGNUP_INVITE_CODE` env var); email required, username optional (case-insensitive uniqueness on both). First real signup claims any pre-existing demo data.
- **`POST /auth/login`** — accepts email OR username (case-insensitive lookup)
- **`POST /auth/logout`** — server-side session deletion + cookie clear
- **`GET /auth/me`** — current user or 401

Cookies are HttpOnly, SameSite=Lax, with 30-day expiration and sliding renewal on every authenticated request. Every endpoint serving user data requires the `current_user` dependency — there are no anonymous data endpoints. Ownership-check helpers return **404 (not 403)** on mismatch so resource existence isn't leaked to unauthorized callers.

---

## Project layout

```
app2/
├── README.md                                    # this file
├── docs/                                        # phase-by-phase dev notes
│   ├── DEV_NOTE_through_Phase4.md
│   ├── DEV_NOTE_through_Phase4c.md
│   ├── DEV_NOTE_through_Phase4d.md
│   ├── DEV_NOTE_phase5a.md
│   └── DEV_NOTE_through_Phase5.md               # ← cumulative close-out
├── data/                                        # seed CSVs + IRS PDFs
├── rag/                                         # one-time ChromaDB ingest
├── sql/                                         # one-time relational load
├── outputs/                                     # gitignored — DBs and vectors
│   ├── accounting.db                            # read-only demo data
│   ├── coreckoner.db                            # sessions, saves, users, auth
│   └── chroma_db/                               # vector store
├── backend/
│   ├── main.py                                  # FastAPI app + endpoints
│   ├── auth.py                                  # Phase 5a auth primitives
│   ├── db/
│   │   ├── session_store.py                     # CRUD for coreckoner.db
│   │   ├── auth_migrations.py                   # Phase 5a schema changes
│   │   ├── auth_queries.py                      # Phase 5a user/session ops
│   │   └── auth_reclaim.py                      # first-signup claim logic
│   ├── pipelines/
│   │   ├── sql_pipeline.py                      # Text-to-SQL
│   │   ├── rag_pipeline.py                      # dual-collection RAG + user filter
│   │   ├── core_recall_pipeline.py              # semantic recall
│   │   ├── core_embed.py                        # embedding + cosine
│   │   └── chart_builder.py                     # chart type + ordering
│   ├── routers/
│   │   ├── query_router.py                      # hybrid router
│   │   ├── upload_router.py                     # file ingest endpoints
│   │   └── auth_router.py                       # Phase 5a auth endpoints
│   ├── uploads/                                 # ingest workers (user-aware)
│   ├── scripts/                                 # one-off maintenance scripts
│   │   ├── backfill_session_titles.py
│   │   ├── backfill_save_embeddings.py
│   │   ├── wipe_user_uploads.py                 # Pass 3 migration
│   │   └── apply_pass5.py                       # Pass 5 surgical applier
│   └── static/index.html                        # single-file chat UI
└── requirements.txt
```

---

## Development conventions

### Phased delivery with dev notes

Every meaningful capability ships as a numbered phase (`Phase 4a`, `Phase 5a`, …)
with a dev note in `docs/` capturing:
- What shipped and the commit chain
- Design decisions made and alternatives rejected
- Issues encountered during install/test and how they were resolved
- An explicit re-initiate prompt for resuming in a new session

This is the project's primary engineering practice — it makes the work
durable across long gaps and easy to hand off.

### Idempotent migrations

Schema changes use the `_ensure_column` and `CREATE … IF NOT EXISTS`
pattern. Re-running migrations on the same database is always safe.

### Safe-install pattern

Before editing any production file:
```bash
cp file.py file.py.bak
# install new version
# verify
# if all good: rm file.py.bak
# if regression: cp file.py.bak file.py
```

For Phase 5 Pass 3 and Pass 5, applier scripts (`backend/scripts/`)
automate this pattern with all-or-nothing semantics and idempotent re-runs.

### Versioning in the banner

The startup banner always shows the current version (e.g. `v2.12.1 · Phase 5b/c (auth-required)`)
so a glance at the terminal tells you which generation of the code is running.

---

## Roadmap

### Phase 5 (complete)

- **5a — Auth foundation** ✅ (commit `f2ace55`) — bcrypt password hashing,
  server-side session cookies, invite-only signup, `get_current_user`
  dependency, auth_sessions table with sliding renewal
- **5b/c — Endpoint scoping + login UI + CASSIA rename** ✅ (commit `63c648b`) —
  every endpoint scoped to `current_user`, ownership-check helpers returning
  404 (not 403), CORS hardened, dark-themed inline login/signup SPA, all
  fetch calls get `credentials: 'include'`, header user dropdown with
  logout, themed error states
- **5c Pass 3 — ChromaDB user isolation** ✅ (commit `77b7b59`) — `user_id`
  added to every chunk's vector metadata, RAG retrieval applies
  `{session_id, user_id}` as a hard conjunction filter, all user_uploads
  access funneled through `_query_user_uploads()` helper, one-time wipe
  script for pre-Pass-3 vectors
- **Phase 5 polish — "Also move source session" checkbox** ✅ — opt-in
  ripple in My Core save card, surgical applier script with `.bak` safety
  and idempotent re-run

### Phase 6 — Business-case simulation testing

Systematic test pass of 15–20 realistic scenarios across:
- Month-end close (variance analysis, GL drill-down, P&L commentary)
- AR follow-up (aging deep-dives, billing partner load, collection priority)
- IRS deposit questions (penalty thresholds, deposit schedule edges)
- Mixed RAG+SQL queries
- Recall continuity across sessions
- Korean/English bilingual flow

Output is a structured test report — what worked, what surprised, what
surfaced as bugs, what the architecture's flexibility ceiling looks like.
Demo recordings come after the bug pass.

### Beyond

- Email verification flow
- OAuth providers (Google, GitHub)
- Per-user RBAC (admin vs viewer)
- Production deployment hardening (HTTPS, rate limiting, encryption at rest)
- Migration off LangChain Chroma (currently deprecated)

---

## License

This is a portfolio project. Code is intended for educational and
demonstrative use. The IRS publications in `data/` are public US Government
documents. The accounting demo data is synthetic.

---

## Acknowledgments

Built incrementally with extensive use of Anthropic's Claude as a pair
programmer. All architectural decisions, debugging, and integration work
were collaborative. Phase notes in `docs/` reflect the actual cadence
of design conversations and trade-off decisions.
