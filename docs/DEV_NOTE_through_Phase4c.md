# CoReckoner — Cumulative Development Note (through Phase 4c)

> **An AI-powered accounting assistant** that answers plain-English questions about
> both unstructured documents (IRS publications + user PDFs) and structured financial
> data (QuickBooks-style exports), with persistent multi-session chat, per-session file
> uploads, and a user-controlled permanent "core" knowledge base. Served through a
> FastAPI backend (port 8002) and a dark-themed chat UI.

**Status as of this note:** Phases 1–3 complete and shipped; Phase 4a / 4b / 4c complete
and committed. Phase 4d (natural-language recall) is the next build — the flagship feature
that makes the save/recall story pay off.

**This is an intermediary log, not a handoff.** It cumulates progress so far so the project
has a single snapshot at a meaningful milestone. More phases remain (4d–4f, then Phase 5
production hardening).

---

## 1. What This Project Does

A unified accounting chatbot combining several capabilities under one interface:

- **RAG pipeline** — answers policy/regulation questions grounded in three IRS publications
  (Pub 15, 15-T, 15-B), with inline source citations.
- **Text-to-SQL pipeline** — converts plain-English questions into SQL over a 7-table
  accounting database, returning exact numbers with auto-generated Plotly charts.
- **Hybrid router** — classifies each question and routes to RAG, SQL, or both; now also
  aware of session-uploaded PDFs.
- **Persistent multi-session chat** — ChatGPT-style sessions saved to SQLite, restorable
  from a sidebar, with messages + artifacts (SQL, charts, citations) preserved.
- **Per-session file uploads** — CSV / Excel into a session SQLite DB; PDF into a
  session-scoped ChromaDB collection. Each upload carries a rich summary captured at ingest.
- **User-controlled "core"** — a permanent knowledge base. The user explicitly **saves**
  chosen answers or uploads into the core, organizes them into **topics**, and (coming in
  4d) recalls them by asking in natural language from any session.

The guiding vision: a "mini-ChatGPT for accountants" where **session = scratchpad** and
**core = vault**, and **save = an explicit commit gesture**.

---

## 2. Architecture (current)

```
                          USER QUESTION
                               │
                               ▼
                   QUERY ROUTER (history-aware, PDF-aware)
              Is this NUMBERS, DOCUMENT, BOTH?  (4d adds: CORE RECALL)
                 │                         │
        ┌────────┘                         └────────┐
        ▼                                           ▼
  TEXT-TO-SQL PIPELINE                        RAG PIPELINE
  schema-grounded SQL                         dual-collection retrieval:
  on accounting.db +                          • irs_pub15  (public IRS docs)
  per-session uploads                         • user_uploads (session-scoped PDFs)
        │                                           │
        └─────────────────┬─────────────────────────┘
                          ▼
                    UNIFIED ANSWER
        text + Plotly chart (if any) + citations (if RAG)
                          │
                          ▼
              FastAPI → dark-themed chat UI (port 8002)
        sidebar: sessions · uploads · 💾 save · 🗄 My Core modal

   PERSISTENCE (coreckoner.db)              CORE (same DB, Phase 4)
   • sessions / messages / artifacts        • users (single 'default' for now)
   • uploads (+ summary_json)               • core_topics
                                            • core_saves (+ embedding_json, 4d)
```

---

## 3. Phase-by-Phase Progress

### Phases 1–3 — Foundation (✅ shipped)

| Capability | Status |
|---|---|
| RAG pipeline over 3 IRS publications, grouped citations | ✅ |
| Text-to-SQL over 7-table accounting DB | ✅ |
| Hybrid router (SQL / RAG / BOTH) | ✅ |
| Plotly auto-charts (bar / pie / line) | ✅ |
| Schema-grounded SQL refusals (no hallucinated tables) | ✅ |
| Conversation memory (history-aware) | ✅ |
| Bilingual comprehension (Korean + English) | ✅ |
| Persistent multi-session chat (SQLite, restorable sidebar) | ✅ |
| Per-session CSV / Excel upload → session SQLite DB | ✅ |
| Per-session PDF upload → session-scoped ChromaDB (C3) | ✅ |
| Session-delete cascade (SQLite + session DB + vectors) | ✅ |
| Friendly categorized error messages | ✅ |

**Phase 3 C3 highlight — session-isolated PDF RAG.** PDFs ingest into a separate
`user_uploads` ChromaDB collection (the public `irs_pub15` collection is never written to),
each chunk tagged with `session_id`. Retrieval filters so a session only sees its own PDFs
plus the shared IRS docs. Verified with a security test: Session A queried an uploaded
Apple 10-K successfully; Session B (no upload) returned "not found" with zero leakage.

### Phase 4 Warm-up — Router PDF-awareness (✅ shipped, v2.5.1)

`classify_question()` now receives `session_id` and injects the list of uploaded PDF
filenames into the router prompt, so questions about an uploaded document route to RAG
instead of being misclassified as SQL. Keyword path untouched; byte-identical behavior when
no PDFs are present.

### Phase 4a — Data model foundation (✅ shipped, v2.6.0)

Added three tables to `coreckoner.db` (folded into `init_db()`, no separate migration):
- **`users`** — single hard-coded `default` user (real auth deferred to 4f).
- **`core_topics`** — user-defined topics, `UNIQUE(user_id, name)`.
- **`core_saves`** — saved messages/uploads with provenance columns, soft-delete
  (`archived_at`), and an `embedding_json` column provisioned now for 4d recall.

Full CRUD written and tested: `ensure_default_user`, topic create/list/rename/delete,
save create/list/get/update-topic/archive, `find_save_by_source`, plus counts for `/stats`.
No user-visible change — foundation only.

### Phase 4b — Save (✅ shipped, v2.7.0)

Split into two clean sub-steps:

**4b-1 — Rich upload summary at ingest.** Added `summary_json` to the uploads table (with an
idempotent `ALTER TABLE` guard, since the table pre-existed). `ingest_csv`/`ingest_xlsx` now
capture columns + first 5 sample rows per table; `ingest_pdf` captures page/chunk counts +
first ~200 chars of the first chunk. This means a saved upload carries real, readable content
without ever re-reading the original file.

**4b-2 — The save button.** `ChatResponse` gained `message_id` so a freshly-sent answer can be
saved immediately. New `POST /core/save` (messages snapshot full text + artifacts; uploads copy
the 4b-1 summary) and `GET /core/saves` (filled-button state). The UI added a 💾 Save button on
every assistant message and every upload row, a purple "core" toast, and saved-state on load.
**Bug caught & fixed:** the filled-state check raced the restore render and silently missed,
leaving buttons un-filled on reopen — fixed by removing a per-message async check and deferring
a single `refreshSavedStates()` pass by one animation frame. Verified: saves persist, filled
state survives reload, idempotent (no duplicate saves).

### Phase 4c — Topics + My Core Data (✅ shipped, v2.8.0)

**Backend:** thin endpoints over the 4a CRUD —
`GET/POST/PATCH/DELETE /core/topics`, `GET /core/saves/list` (optionally by topic),
`PATCH /core/saves/{id}` (move to topic / set note), `DELETE /core/saves/{id}` (archive).

**Frontend:** a **🗄 My Core** header button with a live save-count badge opens a modal
overlay — a topics column (All / Unsorted / user topics with live counts, inline new-topic
creation, hover rename/delete) and a saves column (kind badge, title, content preview, a
topic dropdown to move, an Archive button). Closes on Esc, backdrop click, or ✕.

Verified in browser: topic creation, save-move, topic filtering, and archive all work with
counts updating live (e.g. Unsorted 1 / Tax Q1 1). Existing chat/upload/save UI unaffected.

---

## 4. Current Data Model (coreckoner.db)

```
sessions(session_id, title, created_at, updated_at)
messages(message_id, session_id→sessions, role, content, pipeline_used, timestamp)
artifacts(artifact_id, message_id→messages, artifact_type, content_json, created_at)
uploads(upload_id, session_id→sessions, filename, file_type, target,
        table_names, chunk_count, row_count, summary_json, uploaded_at)
users(user_id, email, display_name, created_at, is_default)
core_topics(topic_id, user_id→users, name, created_at, UNIQUE(user_id,name))
core_saves(save_id, user_id→users, topic_id→core_topics(SET NULL), kind,
           source_session_id, source_message_id, source_upload_id,
           title, content, metadata_json, note, embedding_json,
           created_at, archived_at)
```

Demo accounting data (separate `accounting.db`, unchanged): accounts_payable 45, revenue 53,
balance_sheet 28, profit_loss 36, accounts_receivable 14, general_ledger 139,
chart_of_accounts 59.

Key design decisions: saved items **outlive** the session they came from (session-delete does
not delete core_saves); saves go to a default **Unsorted** bucket at save time and are organized
into topics afterward; `embedding_json` was provisioned in 4a to avoid a migration in 4d.

---

## 5. How to Run

```bash
cd "/path/to/app2"
source venv/bin/activate

# Every session — MUST run from app2/ root, not backend/
lsof -ti:8002 | xargs kill -9    # kill any stale server
python3 backend/main.py          # start FastAPI on port 8002
# open http://localhost:8002 (incognito recommended to avoid cache fighting edits)
```

**Recurring gotcha:** running `python3 backend/main.py` from inside `backend/` looks for
`backend/backend/main.py` and fails — always `cd` to the `app2/` root first. (Tell: prompt
ending in `backend %` → `cd ..`.)

**Backups:** `./backup_app2.sh <tag>` writes a dated zip to `~/Desktop/application backup zips/`,
excluding venv / chroma_db / per-session DBs / __pycache__ / .git.

---

## 6. Remaining Roadmap

| Phase | Scope | Status |
|---|---|---|
| **4d** | **Natural-language recall** — embed saved content, cosine similarity, router learns a `core_recall` route. Ask "what did I save about net income?" in a fresh session and get it back. | ⏭ Next (the flagship) |
| 4e | Topic-grouped session sidebar (`ALTER TABLE sessions ADD COLUMN topic_id`) | 🔮 Planned |
| 4f | Real auth (JWT + bcrypt, signup-code-gated) — optional, skippable if solo | 🔮 Optional |
| **Phase 5** | Production hardening: real auth + email verify + password reset, httpOnly cookies, rate limiting, audit log, encryption at rest, GDPR export/delete, HTTPS, CORS lockdown, hosting, monitoring | 🔮 Future (separate project) |

**Phase 5 polish backlog (noted, deferred):**
- Replace native `prompt()` / `confirm()` dialogs (topic rename, topic delete, save archive)
  with themed inline editing + a reusable confirm modal. Demo-correct as-is; production-correct
  needs themed dialogs (native ones are unstylable, block the tab, and can be suppressed by the
  browser). Pattern already exists in the session-rename inline editor.

---

## 7. Known Notes & Trade-offs

- **LangChain Chroma migration deferred** — `langchain_community.vectorstores.Chroma` is
  deprecated, but migrating hits a Python 3.13 + numpy 2.x dependency wall. The deprecation +
  ChromaDB telemetry warnings on startup are cosmetic and ignored.
- **PyPDF "wrong pointing object" warnings** on some PDFs (e.g. the Apple 10-K) are harmless —
  the document still ingests.
- **Single hard-coded user** (`default`) throughout Phase 4 — every core endpoint is scoped to
  `CURRENT_USER_ID`. Real multi-user support is Phase 4f / Phase 5.
- **Native dialogs** for a few rare actions (see Phase 5 backlog above) — functional, themed
  later.

---

## 8. Current Versions

- Backend `main.py`: **v2.8.0** (banner: "Phase 4c: topics + My Core Data")
- Latest commit: `66b2125` — "Phase 4c: topics + My Core Data modal"
- Demo-ready for a mentor: hybrid RAG+SQL, persistent sessions, charts, CSV/Excel/PDF uploads,
  session isolation, save-to-core, topic organization. Portfolio-ready (Loom + screenshots)
  roughly one polish session away; the recall flagship (4d) is the highest-value remaining work.
```
