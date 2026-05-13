# CoReckoner — Accounting AI Chatbot
## Session Handoff Document v3 — May 13, 2026

---

## What CoReckoner Is

An accounting AI chatbot combining **RAG** (IRS document search) and
**Text-to-SQL** (structured QuickBooks data) into one hybrid system.
FastAPI backend, persistent SQLite sessions, per-session user-data uploads,
Plotly charts, dark UI.

**Port: 8002** — never reuse 3000 (prototype), 3001 (App 1), 3002 (future Next.js)

---

## How to Start Every Session

```bash
cd "/Users/sanghyunseong/Desktop/Z26 Glob NG consult/app 2 - chatbot/app2"
source venv/bin/activate
lsof -ti:8002 | xargs kill -9
python3 backend/main.py
```

Open: http://localhost:8002

**Important:** the project folder is `app 2 - chatbot/app2/`. All CSVs and
PDFs are at `app 2 - chatbot/app2/data/` (NOT in a sibling folder).
The v2 handoff was misleading on this point — fixed in v3.

**When to restart vs refresh:**
- Changed .py file → server restart required
- Changed index.html only → browser Cmd+R is enough
- Changed CSV data → run sql/phase1_load.py then restart
- Changed IRS PDF → run rag/phase1_ingest.py then restart

---

## Folder Structure (updated)

```
app2/
├── venv/                        single venv, Python 3.13 ARM
├── .env                         OPENAI_API_KEY
├── requirements.txt             added: python-multipart, openpyxl
├── data/                        11 source files (8 CSV + 3 PDF)
│   ├── irs_pub15.pdf, irs_pub15b.pdf, irs_pub15t.pdf
│   ├── accounts_payable.csv, accounts_receivable.csv
│   ├── balance_sheet.csv, chart_of_accounts.csv
│   ├── general_ledger.csv, journal_entries.csv
│   ├── profit_loss.csv, revenue.csv
├── outputs/
│   ├── chroma_db/               414 vectors (IRS Pub 15)
│   ├── accounting.db            7 SQL tables (demo data)
│   ├── coreckoner.db            sessions, messages, artifacts, uploads
│   └── sessions/                NEW — per-session user upload DBs
│       └── {session_id}.db      created on first ingest
├── rag/                         phase1_ingest, phase2_query, phase3_inspect
├── sql/                         phase1_load, phase2_query
└── backend/
    ├── main.py
    ├── db/
    │   ├── __init__.py
    │   └── session_store.py     coreckoner.db CRUD (sessions/messages/artifacts/uploads)
    ├── pipelines/
    │   ├── __init__.py
    │   ├── sql_pipeline.py      now attaches per-session DB as 'user_data'
    │   └── rag_pipeline.py      unchanged this phase (session-scope coming with PDF)
    ├── routers/
    │   ├── __init__.py
    │   ├── query_router.py
    │   └── upload_router.py     NEW — preview/ingest/list/delete uploads
    ├── uploads/                 NEW
    │   ├── __init__.py
    │   ├── schema_utils.py      identifier sanitization, type inference
    │   ├── tabular.py           CSV/Excel preview + ingest
    │   └── session_db.py        per-session SQLite manager
    └── static/
        └── index.html           now has 📎 upload + toast + uploads sidebar
```

---

## Databases

### accounting.db — demo dataset (7 tables, unchanged)

| Table | Rows | Key columns |
|-------|------|-------------|
| chart_of_accounts | 52 | account_code, account_type, account_subtype |
| general_ledger | 139 | date, debit, credit, period, client_vendor |
| balance_sheet | 27 | jan_31_2026 → apr_30_2026, account_subtype |
| profit_loss | 28 | january_2026 → april_2026, ytd_total, category |
| accounts_receivable | 14 | balance_due, days_outstanding, aging_bucket, billing_partner |
| accounts_payable | 45 | amount, status, days_outstanding, vendor_name |
| revenue | 53 | amount, invoice_date, service_type, client_name |

### coreckoner.db — persistence (4 tables)

```
sessions    — session_id, title, created_at, updated_at
messages    — message_id, session_id, role, content, pipeline_used, timestamp
artifacts   — artifact_id, message_id, artifact_type, content_json, created_at
uploads     — upload_id, session_id, filename, file_type, target,        NEW
              table_names, chunk_count, row_count, uploaded_at
```

Artifact types saved per assistant message:
- route_explanation, response_type, sql_query, sql_result, citations, chart_spec

### outputs/sessions/{session_id}.db — per-session user data — NEW

Each session that has at least one upload owns a SQLite file here.
The SQL pipeline ATTACHes this file as `user_data` so user tables are
queryable as `user_data.<table>` alongside the demo accounting.db.

Lifecycle:
- Created on first ingest call for the session
- Tables added per upload (auto-suffixed _2, _3 on name collision)
- Tables dropped via DELETE /uploads/{id}
- File deleted on cascade when DELETE /sessions/{id} fires

---

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | /chat | Main chat |
| GET | /sessions | List all sessions |
| POST | /sessions | Create new session |
| GET | /sessions/{id} | Full restore with messages + artifacts |
| PATCH | /sessions/{id} | Rename |
| DELETE | /sessions/{id} | Delete session, cascade DB file |
| GET | /health | Server status |
| GET | /stats | Row counts + session count |
| GET | /schema | accounting.db schema |
| POST | /sessions/{id}/uploads/preview | NEW — inspect CSV/Excel, no persist |
| POST | /sessions/{id}/uploads/ingest | NEW — write file to session DB or ChromaDB |
| GET | /sessions/{id}/uploads | NEW — list uploads for sidebar |
| DELETE | /uploads/{id} | NEW — drop tables/vectors + remove uploads row |

---

## Phase 3 — What Is Completed ✅

### C1 — File upload engine ✅
- 📎 button in chat composer
- Native file picker filtered to .csv / .xlsx / .xls
- Auto-creates a session if user clicks 📎 with no active session
- Toast notifications (top-right) for success/error/in-progress

### C2 — CSV/Excel ingest ✅
- Two-stage API: /uploads/preview returns detected schema without persist
- /uploads/ingest writes to outputs/sessions/{id}.db
- Auto-suffix on table-name collision (revenue → revenue_2)
- Excel: every sheet becomes its own table, per-sheet success/failure
- Column-name sanitization with reserved-word handling
- Uploads list visible in sidebar between sessions and Quick Questions
- ✕ button on each upload drops the table and removes the row

### C5 — Missing-data nudge ✅
- When SQL pipeline returns response_type="no_data", appends a friendly
  hint: "This data isn't in the demo tables — click 📎 to upload a CSV/Excel."

### Session-delete cascade ✅
- DELETE /sessions/{id} now also deletes outputs/sessions/{id}.db
- ChromaDB vector cleanup stubbed in main.py for PDF step

### SQL Pipeline — user-data support ✅
- run_sql_pipeline() now takes optional session_id
- ATTACHes outputs/sessions/{id}.db as 'user_data' at query time
- Injects USER UPLOADED TABLES block into prompt with sniffed types
- Short-circuit: if question mentions uploads but none exist, returns
  friendly message in CODE (not LLM) — prevents user_data.* hallucinations
- All demo queries (net income, AR, etc.) work unchanged

---

## Phase 3 — What Remains ❌

### C3 — PDF / text upload into RAG — NEXT
- Backend: chunk + embed PDFs, write to ChromaDB with session_id metadata
- Backend: extend upload_router to handle .pdf/.txt
- Pipeline: RAG retrieval filter — session vectors OR irs vectors only
- UI: extend file-input `accept` to allow .pdf / .txt
- Cascade: hook ChromaDB cleanup into main.py's delete_session

### C4 — Image upload — deferred
- Embed description into ChromaDB
- Probably 1 session of work, low priority

---

## Phase 4 — Future Vision (captured for the next handoff)

**Core idea:** CoReckoner becomes a personal accounting assistant where
the user *chooses* what to save, with a permanent core database that
can recall information across sessions.

**Architecture shift from today:**

| Today | Phase 4 vision |
|-------|----------------|
| Anonymous sessions | Per-user accounts |
| Auto-save everything | User clicks "save" to commit |
| Session-scoped data | Tiered: session (scratchpad) vs core (vault) |
| One DB per session | Sessions ephemeral by default, core permanent |

**Concrete features:**
- **User accounts** — login, profile (fiscal_year_end, accounting_standard)
- **Save button** — per message and per upload, "save to my permanent data"
- **Core database** — encrypted, per-user, organized by topic (P&L, payroll,
  bookkeeping)
- **Recall** — natural language ("What did I save about Q1 payroll?") pulls
  from core, displays as past data with provenance
- **Multi-session per topic** — Session #1 P&L, Session #2 Payroll,
  Session #3 Bookkeeping; each can read from core, optionally write back

**Inspiration phrasing the user used:**
> "Like a cosmetic 2026 tax form prep that pulls 2025 tax return info —
> historical data should be loadable on demand. Not auto-saved as a single
> dump, but as a database where the user chooses what to save to secure
> storage, organized by session topic."

**Order of work for Phase 4:**
1. Auth + user accounts (FastAPI Users or custom JWT)
2. "Save" button UI + backend endpoint to commit a session artifact to core
3. Core database schema design (per-user, per-topic partitioning)
4. Recall query — natural language to "search my saved data"
5. Multi-session UI redesign (topic-based sidebar, not chronological)

---

## Known Issues / Carry-Over

| Issue | Status |
|-------|--------|
| LLM hallucinated user_data.revenue when no uploads | Fixed via code short-circuit |
| no_data response had no follow-up suggestion | Fixed via NO_UPLOAD_NUDGE |
| Deleted session left outputs/sessions/{id}.db on disk | Fixed via cascade |
| PDF upload returns 501 placeholder | By design — next session |
| LangChain Chroma deprecation warning | Cosmetic, fixed in next refactor |

---

## 60 Demo Questions (unchanged from v2)

Plus three new ones for user-uploaded data:

**Upload demo (any session with revenue.csv uploaded):**
- How many rows are in my uploaded data?
- What is the total amount in my uploaded revenue table?
- Show the first 10 rows of my uploaded data

**Upload nudge demo (any session with no uploads):**
- How much did I spend on travel? → friendly nudge to upload a CSV

---

## Demo Sequence (updated, 6 questions)

| # | Question | Shows |
|---|----------|-------|
| 1 | What is our net income for Q1 2026? | P&L, monthly breakdown |
| 2 | Show our net income trend as a line chart | Plotly line chart |
| 3 | (Upload revenue.csv via 📎) | Upload UI, toast, sidebar |
| 4 | How many rows are in my uploaded data? | Session-scoped user_data.revenue |
| 5 | What is the penalty for late payroll tax deposits? | RAG, IRS citations |
| 6 | What is our overdue AP balance and what is the IRS penalty? | BOTH pipeline |

---

## Sessions 8–10 Roadmap

| Session | Focus |
|---------|-------|
| **8** | C3 PDF upload — ChromaDB session-scoping + RAG filter |
| 9 | Phase 4 design + user accounts + "save" architecture |
| 10 | UX polish + Loom recording + GitHub repo + LinkedIn post |

---

## Job Positioning (unchanged)

LinkedIn headline:
"Applied Gen AI Developer — RAG + Text-to-SQL for Accounting & Finance"

Positioning statement:
"I build practical AI tools for accounting, finance, tax, and
document-heavy business workflows using RAG + Text-to-SQL architecture
with per-user data uploads."

2-minute demo script:
  0:00–0:30  Problem — accountants need AI for data queries on demand
  0:30–1:00  Demo — ask demo data question, get answer + chart
  1:00–1:30  Demo — upload personal CSV, ask question on it
  1:30–2:00  Tech stack — RAG + Text-to-SQL + per-session uploads + persistent sessions

---

*Last updated: May 13, 2026*
*Next task: Session 8 — Phase 3 C3 (PDF upload into RAG, session-scoped)*
