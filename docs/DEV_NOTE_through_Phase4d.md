# CoReckoner — Cumulative Development Note (through Phase 4d)

> **An AI-powered accounting assistant** that answers plain-English questions about
> both unstructured documents (IRS publications + user PDFs) and structured financial
> data (QuickBooks-style exports), with persistent multi-session chat, per-session file
> uploads, a user-controlled permanent "core" knowledge base, and **natural-language
> recall** that can pull saved answers back in any future session. Served through a
> FastAPI backend (port 8002) and a dark-themed chat UI.

**Status as of this note:** Phases 1–3 complete; Phase 4a / 4b / 4c / **4d** complete
and committed. The flagship save→recall vision is **functional end-to-end** — the
project now does the thing the design was always aiming at.

**This is an intermediary log, not a handoff.** Three small Phase 4 items remain
(auto session titles, topic-grouped sidebar 4e, chart bug fix); 4f real auth is
explicitly deferred to Phase 5. After those three, the project is portfolio-ready.

---

## 1. What This Project Does

A unified accounting chatbot combining several capabilities under one interface:

- **RAG pipeline** — answers policy/regulation questions grounded in three IRS publications
  (Pub 15, 15-T, 15-B), with inline source citations.
- **Text-to-SQL pipeline** — converts plain-English questions into SQL over a 7-table
  accounting database, returning exact numbers with auto-generated Plotly charts.
- **Hybrid router** — classifies each question and routes to SQL, RAG, BOTH, or
  **CORE_RECALL**. Aware of session-uploaded PDFs.
- **Persistent multi-session chat** — ChatGPT-style sessions saved to SQLite, restorable
  from a sidebar, with messages + artifacts (SQL, charts, citations, core sources)
  preserved.
- **Per-session file uploads** — CSV / Excel into a session SQLite DB; PDF into a
  session-scoped ChromaDB collection. Each upload carries a rich summary captured at ingest.
- **User-controlled "core"** — a permanent knowledge base. The user explicitly **saves**
  chosen answers or uploads into the core, organizes them into **topics**, and now
  **recalls** them by asking in natural language from any session.

The guiding vision: a "mini-ChatGPT for accountants" where **session = scratchpad**,
**core = vault**, **save = an explicit commit gesture**, and **recall = the payoff**.

---

## 2. Architecture (current — post-4d)

```
                          USER QUESTION
                               │
                               ▼
              QUERY ROUTER (history-aware, PDF-aware, recall-aware)
        Trigger phrases → CORE_RECALL (deterministic)
        Otherwise: LLM picks SQL / RAG / BOTH / CORE_RECALL
                 │                         │
        ┌────────┘                         └────────┐
        ▼                                           ▼
  TEXT-TO-SQL PIPELINE                        RAG PIPELINE
  schema-grounded SQL                         dual-collection:
  on accounting.db +                          • irs_pub15  (public)
  per-session uploads                         • user_uploads (session-scoped)
        │                                           │
        └────────────────┬──────────────────────────┘
                         │      ┌─── CORE RECALL PIPELINE (4d) ───┐
                         │      │  embed question                  │
                         │      │  cosine-similar against saves    │
                         │      │  threshold 0.35, top-5           │
                         │      │  LLM cites saved titles + dates  │
                         │      │  no match → fall-through banner  │
                         │      └──────────────────────────────────┘
                         ▼
                   UNIFIED ANSWER
        text + Plotly chart (if any) + citations (RAG) or core sources (recall)
                         │
                         ▼
              FastAPI → dark-themed chat UI (port 8002)
        sidebar: sessions · uploads · 💾 save · 🗄 My Core modal

   PERSISTENCE (coreckoner.db)              CORE (same DB, Phase 4)
   • sessions / messages / artifacts        • users (single 'default' for now)
   • uploads (+ summary_json)               • core_topics
                                            • core_saves (+ embedding_json — used in 4d)
```

---

## 3. Phase-by-Phase Progress

### Phases 1–3 — Foundation (✅ shipped)

| Capability | Status |
|---|---|
| RAG pipeline over 3 IRS publications, grouped citations | ✅ |
| Text-to-SQL over 7-table accounting DB | ✅ |
| Hybrid router (SQL / RAG / BOTH) | ✅ |
| Plotly auto-charts (bar / pie / line) | ✅ (chart-type bug pending fix) |
| Schema-grounded SQL refusals | ✅ |
| Conversation memory | ✅ |
| Bilingual comprehension (Korean + English) | ✅ |
| Persistent multi-session chat | ✅ |
| Per-session CSV / Excel upload → session SQLite DB | ✅ |
| Per-session PDF upload → session-scoped ChromaDB (C3) | ✅ |
| Session-delete cascade (SQLite + session DB + vectors) | ✅ |
| Friendly categorized error messages | ✅ |

### Phase 4 Warm-up — Router PDF-awareness (✅ shipped, v2.5.1)

`classify_question()` receives `session_id` and injects uploaded-PDF filenames into the
router prompt, biasing toward RAG/BOTH for questions targetable by uploaded docs.

### Phase 4a — Data model foundation (✅ shipped, v2.6.0)

Three tables added to `coreckoner.db`: `users` (single hard-coded default),
`core_topics`, `core_saves` (with `embedding_json` provisioned for 4d). Full CRUD
written, tested, no user-visible change.

### Phase 4b — Save (✅ shipped, v2.7.0, commit `5e291b8`)

- **4b-1:** Rich `summary_json` captured at upload-ingest (columns + sample rows for
  tabular, page/chunk counts + preview text for PDFs). Idempotent `ALTER` migration.
- **4b-2:** 💾 Save button on every assistant message and upload. New `POST /core/save`
  and `GET /core/saves` endpoints. **Bug caught & fixed:** the filled-state check raced
  the restore render and silently missed; fixed by removing a per-message async check
  and deferring `refreshSavedStates()` by one animation frame.

### Phase 4c — Topics + My Core Data (✅ shipped, v2.8.0, commit `66b2125`)

- Backend: 7 thin endpoints over the 4a CRUD (`GET/POST/PATCH/DELETE /core/topics`,
  `GET /core/saves/list`, `PATCH /core/saves/{id}`, `DELETE /core/saves/{id}` (archive)).
- Frontend: 🗄 **My Core** header button with live save-count badge opens a modal —
  topics column (All / Unsorted / user topics with live counts) and saves column
  (kind badge, title, content preview, topic dropdown to move, archive button).

### Phase 4d — Natural-language recall (✅ shipped, v2.9.0, commit `ce5e6a5`)

**The flagship.** Two new files, three modifications, one one-time backfill script.

- **`pipelines/core_embed.py`** (new) — `text-embedding-3-small` helper +
  pure-Python cosine similarity. Used at save time (embed-on-save) and at query time.
- **`pipelines/core_recall_pipeline.py`** (new) — embeds the question, scores every
  active save by cosine similarity, keeps anything above threshold 0.35 (top-5), then
  the LLM composes a grounded answer citing saved titles and dates.
- **`routers/query_router.py`** — adds `CORE_RECALL` as a 4th route with **hybrid
  detection**: 9 explicit trigger phrases force the route deterministically (no LLM
  call); the LLM is also told `core_recall` exists and may pick it on its own.
- **`db/session_store.py`** — adds `update_save_embedding()` and
  `list_saves_needing_embedding()`. `embedding_json` column itself was provisioned in
  4a, so no migration needed.
- **`main.py` v2.9.0** — wires the new route, embeds saves on commit (best-effort),
  implements **transparent fall-through**: when recall returns no match above
  threshold, the route demotes to sql/rag/both AND surfaces a visible amber
  "no recall match" banner via a new `core_fallthrough_note` artifact.
- **`scripts/backfill_save_embeddings.py`** (new) — one-time fill for pre-4d saves.
- **Frontend:** new purple **CORE** badge, amber fall-through banner, core-sources
  panel listing matched saves with relevance scores. Restore path reads the new
  `core_sources` and `core_fallthrough_note` artifacts so restored sessions still
  show recall context.

**Verified end-to-end in browser test:**
- 3 existing saves backfilled cleanly via the script
- "Recall saved net income" in a fresh session → **CORE badge** with the saved Q1
  data and sources panel (relevance 0.49 for both Q1 saves; 0.40 for the loosely
  related Apple 10-K save — all above the 0.35 threshold)
- "What did I save about pizza?" → trigger fired, no match (best 0.11, under 0.35)
  → fall-through banner appeared, demoted to SQL with the "no uploaded data"
  refusal — exactly the transparent-fallthrough behavior the design specified
- "Show revenue by service line as a bar chart" → routed cleanly to SQL with no
  false-positive on `core_recall`

---

## 4. Current Data Model (coreckoner.db)

```
sessions(session_id, title, created_at, updated_at)
messages(message_id, session_id→sessions, role, content, pipeline_used, timestamp)
artifacts(artifact_id, message_id→messages, artifact_type, content_json, created_at)
  artifact_type values: sql_query, sql_result, citations, route_explanation,
                        response_type, chart_spec,
                        core_sources, core_fallthrough_note   ← Phase 4d additions
uploads(upload_id, session_id→sessions, filename, file_type, target,
        table_names, chunk_count, row_count, summary_json, uploaded_at)
users(user_id, email, display_name, created_at, is_default)
core_topics(topic_id, user_id→users, name, created_at, UNIQUE(user_id,name))
core_saves(save_id, user_id→users, topic_id→core_topics(SET NULL), kind,
           source_session_id, source_message_id, source_upload_id,
           title, content, metadata_json, note, embedding_json,
           created_at, archived_at)
```

Demo accounting data (separate `accounting.db`, unchanged): accounts_payable 45,
revenue 53, balance_sheet 28, profit_loss 36, accounts_receivable 14,
general_ledger 139, chart_of_accounts 59.

**Key design decisions (cumulative):**
- Saved items **outlive** the session they came from (session-delete does not
  delete core_saves).
- Saves go to a default **Unsorted** bucket at save time; users organize into
  topics afterward via the My Core modal.
- `embedding_json` provisioned in 4a to avoid a migration in 4d.
- **Embed-on-save is best-effort**, never blocks the save itself; backfill script
  exists for any save without an embedding.
- **Hybrid routing for recall** (triggers + LLM + fall-through) — see 4d notes.

---

## 5. How to Run

```bash
cd "/path/to/app2"
source venv/bin/activate

# Every session — MUST run from app2/ root, not backend/
lsof -ti:8002 | xargs kill -9    # kill any stale server
python3 backend/main.py          # start FastAPI on port 8002
# open http://localhost:8002 (incognito recommended)
```

**Recurring gotcha:** running `python3 backend/main.py` from inside `backend/`
looks for `backend/backend/main.py` and fails — always `cd` to the `app2/` root
first.

**Backups** (current pattern is a one-liner, not the older script):
```bash
mkdir -p ~/Desktop/"application backup zips" && \
cd "/Users/sanghyunseong/Desktop/Z26 Glob NG consult" && \
zip -r ~/Desktop/"application backup zips"/app2_$(date +%Y-%m-%d_%H%M)_<tag>.zip \
  "app 2 - chatbot/app2" \
  -x "*/venv/*" "*/outputs/chroma_db/*" "*/outputs/sessions/*" \
     "*/.git/*" "*/.env" "*/__pycache__/*" "*.pyc" "*.DS_Store"
```

**One-time after 4d install (already done):**
```bash
python3 backend/scripts/backfill_save_embeddings.py
```
Idempotent — running it again on already-embedded saves does nothing.

---

## 6. Remaining Roadmap — Revised Phase 4 Close-out

After 4d shipped, the remaining Phase 4 work was reconsidered in conversation with
both Claude and the project mentor. The original plan called for 4e (topic-grouped
sidebar) and 4f (auth). The revised plan adds two pilot fixes and reorders 4e to
build *on top of* one of them.

### Why the order matters

The sidebar's usability problem isn't really "lack of topic grouping" — it's that
most sessions are stuck on the literal title "New Chat" because the auto-title only
fires on the very first message and even then captures raw truncated user text.
A sidebar of "New Chat" entries isn't worth grouping; the names need to be
*meaningful* first. ChatGPT solves this by auto-generating a 3–6 word summary title
after the first exchange — which is exactly the missing piece.

Once titles are meaningful, topic grouping (4e) becomes the layer that takes a
flat list of well-named sessions and organizes them into navigable groups when the
list gets long. Auto-titles alone work for ~10–20 sessions; grouping pays off
beyond that.

So: **auto-titles first (foundation), then 4e (organization on top).** This was
discussed with the mentor and locked in.

### The close-out plan

| Step | Scope | Status | Why this order |
|---|---|---|---|
| **Auto session titles** | After first user+assistant exchange in a new session, fire a 1-call LLM summary (~$0.0005) → update session.title. One-shot backfill for existing "New Chat" sessions. Single file change (`main.py`) + tiny script. No frontend work. | ⏭ Next | Makes sidebar names meaningful — the foundation 4e depends on. |
| **4e — Topic-grouped sidebar** | Idempotent `ALTER TABLE sessions ADD COLUMN topic_id`. One thin endpoint `PATCH /sessions/{id}/topic`. Sidebar regrouped into collapsible topic sections (uses the topics already created in 4c — shared namespace). Inline hover dropdown on each session row to assign/move. Skip the in-chat header dropdown — keep it lean. Optional smoother default: saves inherit their session's topic at save time. | After auto-titles | Layers organization on top of names that now mean something. With "Unsorted" sessions also visible, the topic structure of the app becomes legible. |
| **Chart bug fix** | Bar charts rendering as line charts; SQL `ORDER BY` ignored in chart x-axis. Pre-existing in `sql_pipeline.py` and the frontend `renderChart()` — **not** introduced by 4d. Standalone diagnostic + fix. | Standalone, slot anywhere | Independent of the sidebar work — cleanest as its own commit so `git log` reads clearly. |
| **4f — Real auth** | Login, signup, per-user data isolation. Touches every existing endpoint to scope by `current_user` instead of `DEFAULT_USER_ID`. Belongs in Phase 5 production hardening. | 🔮 Deferred | For 1–3 trusted demo users it doesn't earn its keep. Real auth is a Phase 5 multi-session project alongside encryption, HTTPS, rate limiting, etc. |

Three more focused sessions to ship the close-out (auto-titles, 4e, chart fix),
each ending in a clean commit your mentor can read in `git log`. After those,
the project is **portfolio-ready** (Loom + screenshots).

### Phase 5 polish backlog (carried forward)

- **Replace native `prompt()`/`confirm()` dialogs** (topic rename, topic delete,
  save archive) with themed inline editing + a reusable confirm modal.
  Demo-correct as-is; production-correct needs themed dialogs (native ones are
  unstylable, block the tab, and can be suppressed by the browser). Pattern
  already exists in the session-rename inline editor.

---

## 7. Known Notes & Trade-offs

- **LangChain Chroma migration deferred** — `langchain_community.vectorstores.Chroma`
  is deprecated, but migrating hits a Python 3.13 + numpy 2.x dependency wall.
  The deprecation + ChromaDB telemetry warnings on startup are cosmetic.
- **PyPDF "wrong pointing object" warnings** on some PDFs (e.g. the Apple 10-K)
  are harmless — the document still ingests cleanly.
- **Single hard-coded user** (`default`) throughout Phase 4. Real multi-user
  support is Phase 4f / Phase 5.
- **Native dialogs** for a few rare actions (see Phase 5 backlog above) —
  functional, themed later.
- **Bar charts misrender as line, ignore SQL `ORDER BY`** — pre-existing bug, fix
  planned as standalone commit in the close-out.
- **Embed-on-save is best-effort** — a failure logs to console and doesn't block
  the save; the backfill script can fill any gaps.
- **Recall-route similarity threshold is 0.35** (tuned for small core size). If
  the user's core grows large and false positives appear, this may need bumping
  to 0.45–0.50.

---

## 8. Current Versions

- Backend `main.py`: **v2.9.0** (banner: "Phase 4d: natural-language core recall")
- Latest commit: **`ce5e6a5`** — "Phase 4d: natural-language core recall"
- Working backup: `app2_2026-05-28_2143_phase4d-working.zip` (in `~/Desktop/application backup zips/`)
- **Demo status:** the flagship save→recall vision is functional end-to-end.
  Three small polish items remain before portfolio-ready.

---

## 9. Re-initiate Prompt for Next Session

When you come back to start the next phase (auto session titles), open a fresh
chat and paste this:

> Picking up CoReckoner Phase 4 close-out. State: 4d shipped (commit `ce5e6a5`),
> flagship recall working end-to-end. Per the revised plan in
> `DEV_NOTE_through_Phase4d.md`, the remaining work is:
>
> 1. **Auto session titles** (next, this session) — LLM-generated 3–6 word title
>    after first exchange, plus one-shot backfill for existing "New Chat" sessions.
> 2. **4e topic-grouped sidebar** (after auto-titles) — `topic_id` on sessions,
>    sidebar regrouped, shared with the 4c topics namespace.
> 3. **Chart bug fix** — standalone (bar charts misrender, ORDER BY ignored).
> 4. 4f auth deferred to Phase 5.
>
> Today: auto session titles. Files you'll need: `backend/main.py` (current
> v2.9.0). I'll paste it.

That re-initiate prompt — plus the file paste — lets next session skip the entire
"what are we doing" conversation and go straight to building.
