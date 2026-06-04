# CASSIA — Chat-based Accounting System

**Chat-based Accounting System for SQL, Search, Insight & Analysis**

An AI accounting assistant that answers plain-English questions about both
unstructured documents (IRS publications, uploaded PDFs) and structured
financial data (QuickBooks-style exports), with persistent multi-session
chat, per-session file uploads, semantic recall of saved answers, and
multi-user authentication.

> Built as a portfolio project to demonstrate hybrid RAG + Text-to-SQL
> orchestration, vector-grounded retrieval, conversational LLM integration,
> and production-grade engineering practices (idempotent migrations,
> phased delivery, dev notes, multi-user data isolation).

> *Previously developed under the working name CoReckoner. Renamed to
> CASSIA during Phase 5 to better reflect the architecture.*

---

## Status

Active development. Phases 1–4 complete and verified end-to-end.
Phase 5 (multi-user authentication + data isolation) in progress.

| Phase | Capability | Status |
|------|------------|--------|
| 1–2  | Hybrid RAG + Text-to-SQL with router classification | ✅ shipped |
| 3    | Per-session uploads (CSV / Excel / PDF) | ✅ shipped |
| 4a–c | Persistent sessions, save-to-core, topic organization | ✅ shipped |
| 4d   | Natural-language recall of saved answers | ✅ shipped |
| 4e   | Topic-grouped sidebar, auto-generated session titles, chart fix | ✅ shipped |
| 5a   | Auth foundation — signup, login, sessions, bcrypt | ✅ shipped |
| 5b–d | Endpoint scoping, ChromaDB user isolation, login UI | 🚧 in progress |
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

**Document upload + grounded Q&A** (per-session ChromaDB):
> Upload Apple's 10-K PDF, then ask *"What was Apple's total net sales in FY 2024?"* → answer cites the uploaded document and page number

**Save important answers to your permanent core**:
> Click 💾 on any answer or upload → it becomes permanently recallable across all future sessions

**Recall by natural language** (semantic search over saves):
> *"What did I save about net income?"* → returns your saved Q1 analysis with relevance scores, even months later in a different session

**Multilingual**:
> *"1월 매출이 얼마야?"* → answers in Korean, generates a Korean session title

---

## Architecture

```
                          USER QUESTION
                               │
                               ▼
       QUERY ROUTER  (history-aware, PDF-aware, recall-aware)
       • trigger phrases   → CORE_RECALL (deterministic)
       • LLM classifies    → SQL / RAG / BOTH / CORE_RECALL
                 │                         │
        ┌────────┘                         └────────┐
        ▼                                           ▼
  TEXT-TO-SQL                                  RAG PIPELINE
  schema-grounded SQL                          dual-collection retrieval
  over accounting.db +                         • irs_pub15  (global)
  per-session uploads                          • user_uploads (per-session)
        │                                            │
        │       ┌─── CORE RECALL ─────────────┐      │
        │       │ embed question              │      │
        │       │ cosine over saves           │      │
        │       │ threshold 0.35, top-5       │      │
        │       │ LLM cites saved titles+date │      │
        │       │ no match → fall through     │      │
        │       └─────────────────────────────┘      │
        ▼                                            ▼
                       UNIFIED ANSWER
   text + Plotly chart (SQL) + citations (RAG) + sources (recall)
                              │
                              ▼
                   FastAPI on port 8002
       Dark-themed chat UI: topic-grouped sidebar · 💾 save ·
       🗄 My Core modal · session restore · uploads cascade

   PERSISTENCE (SQLite)             AUTH (Phase 5a)
   ├─ sessions  (+user_id+topic)    ├─ users (bcrypt password_hash)
   ├─ messages  + artifacts         ├─ auth_sessions (cookie tokens)
   ├─ uploads   (+ summary_json)    └─ HttpOnly + SameSite cookies
   ├─ core_topics (per user)
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
  `coreckoner.db` is persistence (sessions, messages, uploads, core saves).
  Never mix the two.
- *Two ChromaDB collections.* `irs_pub15` is shared reference content,
  globally readable. `user_uploads` is per-session (and as of Phase 5, per-user)
  for uploaded PDFs.
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

Open `http://localhost:8002` — the chat UI loads.

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

Routing decisions come from a small LLM call plus a list of explicit trigger phrases for `CORE_RECALL` ("what did I save about…", "recall my…"). The router is also aware of which PDFs are uploaded into the current session, so it can prefer RAG when a relevant document is present.

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
1. **`irs_pub15`** — IRS Publication 15 (Circular E), 15-T (federal income tax withholding), 15-B (employer's tax guide to fringe benefits). Globally readable.
2. **`user_uploads`** — per-session uploaded PDFs, tagged with `session_id` (and in Phase 5+, `user_id`).

Each retrieval returns top-k chunks per collection, merges by similarity score, and returns the top-k overall. Citations include the source document and page number.

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

### Topic-grouped sidebar

Sessions can be assigned to a topic via the sidebar's 📁 menu. Topics share their namespace with core saves — moving a save to "Tax Q1" uses the same topic as a session assigned to "Tax Q1". Groups are collapsible; "Unsorted" is always shown last.

### Authentication (Phase 5a)

Server-side session cookies via `passlib[bcrypt]`:

- **`POST /auth/signup`** — invite-only (requires `SIGNUP_INVITE_CODE` env var); email required, username optional (case-insensitive uniqueness on both)
- **`POST /auth/login`** — accepts email OR username
- **`POST /auth/logout`** — server-side session deletion + cookie clear
- **`GET /auth/me`** — current user or 401

Cookies are HttpOnly, SameSite=Lax, with 30-day expiration and sliding renewal. The first real signup automatically claims pre-existing demo data — sessions, uploads, saves, and topics move from the placeholder `default` user to the new account.

> **Current limitation:** Phase 5a ships the auth foundation but does NOT
> yet enforce auth on existing chat / sessions / core endpoints. That
> happens in Pass 2. Until then, the auth endpoints work independently
> and the chat UI continues to operate against the `default` user.

---

## Project layout

```
app2/
├── README.md                                    # this file
├── docs/                                        # phase-by-phase dev notes
│   ├── DEV_NOTE_through_Phase4.md
│   ├── DEV_NOTE_through_Phase4c.md
│   ├── DEV_NOTE_through_Phase4d.md
│   └── DEV_NOTE_phase5a.md
├── data/                                        # seed CSVs + IRS PDFs
├── rag/                                         # one-time ChromaDB ingest
├── sql/                                         # one-time relational load
├── outputs/                                     # gitignored — DBs and vectors
│   ├── accounting.db                            # read-only demo data
│   ├── coreckoner.db                            # sessions, saves, users
│   └── chroma_db/                               # vector store
├── backend/
│   ├── main.py                                  # FastAPI app + endpoints
│   ├── auth.py                                  # Phase 5a auth primitives
│   ├── db/
│   │   ├── session_store.py                     # CRUD for coreckoner.db
│   │   ├── auth_migrations.py                   # Phase 5a schema changes
│   │   └── auth_queries.py                      # Phase 5a user/session ops
│   ├── pipelines/
│   │   ├── sql_pipeline.py                      # Text-to-SQL
│   │   ├── rag_pipeline.py                      # dual-collection RAG
│   │   ├── core_recall_pipeline.py              # semantic recall (Phase 4d)
│   │   ├── core_embed.py                        # embedding + cosine
│   │   └── chart_builder.py                     # chart type + ordering
│   ├── routers/
│   │   ├── query_router.py                      # hybrid router
│   │   ├── upload_router.py                     # file ingest endpoints
│   │   └── auth_router.py                       # Phase 5a auth endpoints
│   ├── uploads/                                 # ingest workers
│   ├── scripts/                                 # one-off maintenance scripts
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

### Versioning in the banner

The startup banner always shows the current version (e.g. `v2.10.1 · Phase 4e + chart fix`)
so a glance at the terminal tells you which generation of the code is running.

---

## Roadmap

### Phase 5 (in progress)

- **5a — Auth foundation** ✅
- **5b — Endpoint scoping** — every existing endpoint scoped to `current_user`; `claim_orphaned_data` re-run for the first signed-up user
- **5c — ChromaDB user isolation** — `user_id` added to vector metadata; query-time filter prevents cross-user retrieval; demo PDFs re-uploaded
- **5d — Frontend auth UI** — login/signup screens themed to match the dark surface; logout in header; all 23 `fetch()` calls get `credentials: 'include'`; CASSIA rename throughout the UI
- **5e — Polish** — "Also move source session" checkbox in My Core save card; suppress cosmetic bcrypt warning

### Phase 6 — Business-case simulation testing

Systematic test pass of 15–20 realistic scenarios across month-end close,
AR follow-up, IRS deposit questions, mixed RAG+SQL queries, and recall
continuity. Output is a structured test report — what worked, what
surprised, what surfaced as bugs.

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
