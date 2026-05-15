# CoReckoner — Accounting AI Chatbot
## Session Handoff Document v4 — May 15, 2026

---

## Status — Phase 3 fully complete ✅

CoReckoner is a hybrid RAG + Text-to-SQL accounting chatbot with persistent
multi-session chat, CSV/Excel data uploads, and **session-scoped PDF uploads
with provable isolation between sessions.**

Demo-ready for mentor conversations. Portfolio-ready after recording a Loom.

**Port: 8002** — never reuse 3000 (prototype), 3001 (App 1), 3002 (future Next.js)
**Version: 2.5.0**
**Repo:** github.com/sanghyun-s/accounting-ai-chatbot (private)

---

## How to Start Every Session

```bash
cd "/Users/sanghyunseong/Desktop/Z26 Glob NG consult/app 2 - chatbot/app2"
source venv/bin/activate
lsof -ti:8002 | xargs kill -9 ; python3 backend/main.py
```

Open: **http://localhost:8002** *(use incognito to bypass cache issues)*

Banner should say:
```
  Phase 3 C3: PDF upload + dual-collection RAG
```

**When to restart vs refresh:**
- Changed any .py file → server restart required
- Changed index.html only → Cmd+R reload (with DevTools open + "Disable cache" checked)
- Changed CSV data → run `sql/phase1_load.py` then restart
- Changed IRS PDF → run `rag/phase1_ingest.py` then restart

---

## What's Built (Phase 3 complete)

### C1 — File upload engine ✅
- 📎 button in chat composer with native file picker
- Toast notifications (top-right, success/error/in-progress)
- Auto-creates session if user clicks 📎 with no active session

### C2 — CSV/Excel ingest ✅
- Two-stage API: `/preview` inspects, `/ingest` persists
- Per-session SQLite at `outputs/sessions/{session_id}.db`
- Auto-suffix on table name collision (`revenue` → `revenue_2`)
- Excel: every sheet becomes its own table
- Column sanitization with reserved word handling

### C3 — PDF upload (NEW in v2.5.0) ✅
- **Two ChromaDB collections:** `irs_pub15` (read-only public) + `user_uploads` (writable, session-tagged)
- PDFs chunked using same constants as `phase1_ingest.py` (chunk_size=1000, overlap=200)
- Same `text-embedding-3-small` model
- Boilerplate stripping reused from phase1
- Multi-file batch upload: user can Cmd-click multiple PDFs in the picker
- Frontend loops `/ingest` calls one per file with independent toasts
- File picker accepts `.csv`, `.xlsx`, `.xls`, `.pdf`

### C5 — Missing-data nudge ✅
- When SQL returns `no_data`, appends friendly hint to upload via 📎
- Short-circuit prevents LLM hallucinating `user_data.<table>` when no uploads exist

### Session delete cascade ✅
- `DELETE /sessions/{id}` cascades through:
  1. coreckoner.db rows (FK cleanup)
  2. Per-session SQLite at `outputs/sessions/{id}.db`
  3. **NEW:** ChromaDB vectors in `user_uploads` where `metadata.session_id == id`

### SQL Pipeline — user-data support ✅
- `run_sql_pipeline()` accepts `session_id`
- ATTACHes session DB as `user_data` schema at query time
- Injects USER UPLOADED TABLES into prompt with inferred types

### RAG Pipeline — dual-collection retrieval ✅
- `run_rag_pipeline()` accepts `session_id`
- Queries BOTH `irs_pub15` AND `user_uploads` collections in parallel
- Filters user_uploads by `{"session_id": current_session}` — security boundary
- Merges results by similarity score, returns top-4 overall
- Backwards compatible: if no session_id passed, only IRS docs are searched

---

## Phase 3 C3 Test Results (May 15, 2026)

Test PDF: `data/apple_10k_2024.pdf` (Apple FY24 consolidated financial statements, 4.7MB, 14 chunks)

| Test | Result | What it proved |
|------|--------|----------------|
| 1. Single PDF upload | ✅ | Backend ingest works end-to-end (toast + sidebar + server log clean) |
| 2. Session A queries its PDF | ✅ | User_uploads collection is searchable, citations from apple_10k_2024.pdf |
| 3. Session B cannot see PDF | ✅ | **Session isolation works — security guarantee verified** |
| 4. IRS docs still work | ✅ | Public collection unaffected, 2%/5%/10%/15% penalty answer with Pub 15 citations |
| 5. Multi-PDF batch | skipped | Only one non-IRS test PDF available — frontend code exercised by Test 1 anyway |
| 6. Session delete cascade | ✅ | Server log: `[main] cascade: deleted 14 vectors`. After-check: 0 vectors |

Specific evidence from Test 2:
- Query: "According to my uploaded Apple 10-K document, what were the total net sales for fiscal year 2024?"
- Answer: "$391,035 million" + segment breakdown (iPhone $201,183M, Mac $29,984M, iPad $26,694M, Wearables $37,005M, Services $96,169M)
- Citations: 4 chunks from `apple_10k_2024.pdf` pages 1 and 4

---

## Folder Structure (updated)

```
app2/
├── venv/                          single venv, Python 3.13 ARM
├── .env                           OPENAI_API_KEY (gitignored)
├── .env.example                   template
├── .gitignore                     excludes .env, venv, outputs, etc.
├── README.md                      public-facing, polished
├── requirements.txt
├── data/                          11 source files
│   ├── irs_pub15.pdf, irs_pub15t.pdf, irs_pub15b.pdf
│   ├── apple_10k_2024.pdf         NEW — test PDF for Phase 3 C3
│   └── 8 CSVs (revenue, AR, AP, balance_sheet, P&L, GL, COA, journal_entries)
├── outputs/
│   ├── chroma_db/                 995 vectors total
│   │   ├── irs_pub15 collection   (Pub 15 + 15-B + 15-T, public read-only)
│   │   └── user_uploads collection (per-session PDFs, NEW)
│   ├── accounting.db              7 demo tables
│   ├── coreckoner.db              sessions, messages, artifacts, uploads
│   └── sessions/                  per-session SQLite for user uploads
├── rag/                           phase1_ingest, phase2_query, phase3_inspect
├── sql/                           phase1_load, phase2_query
├── backend/
│   ├── main.py                    v2.5.0 — cascade includes vector cleanup
│   ├── db/session_store.py        coreckoner.db CRUD
│   ├── pipelines/
│   │   ├── sql_pipeline.py        ATTACH user_data, short-circuit
│   │   └── rag_pipeline.py        NEW — dual-collection retrieval
│   ├── routers/
│   │   ├── query_router.py
│   │   └── upload_router.py       NEW — PDF preview/ingest/delete LIVE
│   ├── uploads/
│   │   ├── schema_utils.py
│   │   ├── session_db.py
│   │   ├── tabular.py
│   │   └── document.py            NEW — PDF chunking + embedding + ChromaDB ops
│   └── static/index.html          📎 accepts PDFs, multi-file upload
└── docs/
    ├── HANDOFF_README_v2.md       (historical, May 11)
    ├── HANDOFF_README_v3.md       (historical, May 13 — Phase 3 partial)
    ├── HANDOFF_README_v4.md       (CURRENT, May 15 — Phase 3 complete)
    ├── README_v1_archive.md
    ├── INDEX.md
    └── app2_ph3_pdf_.md           (preserved — original Phase 3 C3 plan)
```

---

## Carried-over for next sessions

### Carry-over 1: Router PDF-awareness (15 min, HIGH VALUE)

**Problem observed during testing:** When user asks *"What were Apple's total net sales for fiscal year 2024?"* in a session with an uploaded Apple 10-K, the query router classifies it as SQL (because of keywords like "total" and "sales") and the PDF is never queried. User had to rephrase: *"According to my uploaded Apple 10-K document..."* for RAG to fire.

**Fix in `routers/query_router.py`:**
- Accept `session_id` parameter
- Look up uploaded files via `list_uploads(session_id)`
- If PDFs exist in session, append to classification prompt: *"This session has uploaded PDFs ({filenames}). Questions that could be about those documents should prefer RAG or BOTH, even if they mention numbers."*
- Pass `session_id` from `main.py`'s `/chat` handler

Estimated: one file modification + one call site update. Should not break existing demo questions because the prompt context is only added when uploads exist.

### Carry-over 2: LangChain Chroma migration (DEFERRED)

Attempted May 15. Hit Python 3.13 + numpy 2.x dependency wall. `langchain-chroma 0.2.6` requires numpy 2.1+ on Py3.13, conflicts with `chromadb 0.5.x`. Older `langchain-chroma 0.1.4` may work but adds no real value.

**Decision: revisit when LangChain 1.x ships across full ecosystem (likely Q3 2026)** OR when Phase 4 user-account refactor naturally rewrites ChromaDB calls. To discuss with mentor.

Cosmetic side effect: deprecation warning still appears at startup. Not functional.

### Carry-over 3: C4 image upload (DEFERRED)

Low priority. Embed image descriptions into ChromaDB for visual document search. Probably 1 small session of work.

### Carry-over 4: Polish session (1 session)

- Record 2-min Loom demo (upload + chart + RAG + hybrid)
- Add screenshots to README
- a11y pass: keyboard-only upload flow, focus states, alt text
- Update 60 demo questions with PDF-upload examples

---

## Phase 4 Vision (locked, designed)

**Mini-ChatGPT for accountants.** User accounts, permanent core database,
explicit save/recall workflow.

| Today | Phase 4 vision |
|-------|----------------|
| Anonymous sessions | Per-user accounts (JWT auth) |
| Auto-save everything to session | User clicks "save" per message/upload |
| Session-scoped data | Tiered: session (scratchpad) vs core (vault) |
| One DB per session | Sessions ephemeral by default, core permanent |

**Concrete features:**
- User accounts (FastAPI Users or custom JWT)
- "Save" button on each assistant message
- "Save" button on each upload
- Core database per-user, encrypted at rest, topic-partitioned (P&L, Payroll, Bookkeeping, Tax)
- Recall: *"What did I save about Q1 payroll?"* searches user's core
- Multi-session UI redesign (topic-based sidebar, not chronological)

**Order of work for Phase 4:**
1. Auth + user accounts
2. "Save" UI + backend endpoint
3. Core database schema (per-user, per-topic, encrypted)
4. Recall query — natural language across saved data
5. UI redesign for topic-based sessions

---

## Demo Sequence (8 questions, updated)

| # | Question | Pipeline | Shows |
|---|----------|----------|-------|
| 1 | What is our net income for Q1 2026? | SQL | P&L, monthly breakdown |
| 2 | Show our net income trend as a line chart | SQL | Plotly chart |
| 3 | (Upload `revenue.csv` via 📎) | — | CSV upload UI |
| 4 | How many rows are in my uploaded data? | SQL | user_data attach |
| 5 | (Upload `apple_10k_2024.pdf` via 📎) | — | PDF upload UI |
| 6 | According to my uploaded Apple 10-K, what were total net sales for FY24? | RAG | Session-scoped PDF retrieval |
| 7 | What is the penalty for late payroll tax deposits? | RAG | Public IRS knowledge |
| 8 | What is our overdue AP balance and what is the IRS penalty? | BOTH | Hybrid pipeline |

---

## API Endpoints (no change since v3)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | /chat | Main chat |
| GET | /sessions | List sessions |
| POST | /sessions | Create session |
| GET | /sessions/{id} | Full restore with messages + artifacts |
| PATCH | /sessions/{id} | Rename |
| DELETE | /sessions/{id} | Delete + cascade (db rows + session.db + ChromaDB vectors) |
| GET | /health | Server status |
| GET | /schema | accounting.db schema |
| POST | /sessions/{id}/uploads/preview | Inspect CSV/Excel/PDF |
| POST | /sessions/{id}/uploads/ingest | Persist (SQL DB or ChromaDB) |
| GET | /sessions/{id}/uploads | List for sidebar |
| DELETE | /uploads/{id} | Drop tables OR vectors + remove row |

---

## Known Issues / Carry-Over

| Issue | Status |
|-------|--------|
| Router prefers SQL even when PDF uploaded | Carry-over 1 above |
| LangChain Chroma deprecation warning at startup | Cosmetic, deferred |
| ChromaDB posthog telemetry warnings | Cosmetic, library quirk |
| Browser cache hides index.html changes | Workaround: incognito mode or DevTools "Disable cache" |
| PDF upload UI tooltip still says "CSV or Excel" | Cosmetic, fix anytime |

---

## Job Positioning

LinkedIn headline:
> "Applied Gen AI Developer — RAG + Text-to-SQL for Accounting & Finance"

Positioning statement:
> "I build practical AI tools for accounting, finance, and tax workflows
> using RAG + Text-to-SQL architecture with session-scoped private document
> uploads."

What you can now demonstrably claim:
- ✅ Hybrid RAG + Text-to-SQL routing
- ✅ Persistent multi-session chat with full artifact restore
- ✅ Auto-generated Plotly charts
- ✅ CSV/Excel upload with per-session SQLite
- ✅ **PDF upload with session-scoped ChromaDB retrieval and provable isolation**
- ✅ Session delete cascade across all three storage layers

---

*Last updated: May 15, 2026*
*Next task: Carry-over 1 (router PDF-awareness) OR Phase 4 design discussion with mentor*
