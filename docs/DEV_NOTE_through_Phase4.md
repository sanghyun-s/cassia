# CoReckoner — Cumulative Development Note (through Phase 4 close-out)

> **An AI-powered accounting assistant** that answers plain-English questions about
> both unstructured documents (IRS publications + user PDFs) and structured financial
> data (QuickBooks-style exports), with persistent multi-session chat, per-session file
> uploads, a user-controlled permanent "core" knowledge base, **natural-language recall**
> of saved answers in any future session, **auto-generated session titles** in the user's
> language, and a **topic-grouped sidebar** for organizing both sessions and saves under
> the same topic namespace. Served through a FastAPI backend (port 8002) and a
> dark-themed chat UI.

**Status as of this note: Phase 4 is closed.** Phases 1–3 complete; Phase 4a / 4b / 4c /
4d / v2.9.1 auto-titles / 4e / v2.10.1 chart-fix all complete, committed, and tested
end-to-end. The flagship save→recall vision is functional, the sidebar is navigable
with meaningful auto-titles and topic groups, and the demo bar charts now order
correctly with consistent table+chart+narrative ordering.

**This is an intermediary log, not a handoff.** Two streams remain queued for Phase 5:
real authentication (the primary scope) and a small polish item (the "also move source
sessions" checkbox in My Core). After Phase 5, the app is ready for the systematic
business-case simulation testing — 15-20 realistic scenarios across month-end close,
AR follow-up, IRS deposit questions, mixed RAG+SQL queries, and recall scenarios.

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
  chosen answers or uploads into the core, organizes them into **topics**, and **recalls**
  them by asking in natural language from any session.
- **Auto-generated session titles** — first user+assistant exchange triggers a small
  LLM call that produces a 3-6 word title in the user's language (English or Korean).
- **Topic-grouped sidebar** — sessions and saves share a single topic namespace. The
  sidebar groups sessions under collapsible topic headers (Unsorted last). Topics
  organize **both** "where conversations happen" (sessions) and "what I want to keep"
  (saves).

The guiding vision: a "mini-ChatGPT for accountants" where **session = scratchpad**,
**core = vault**, **save = an explicit commit gesture**, and **recall = the payoff**.

---

## 2. Architecture (current — post-Phase 4)

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
  → chart_builder.py:                                │
    • infer_chart_hint                               │
    • reorder_for_chart (bar DESC)                   │
        │                                            │
        └────────────────┬───────────────────────────┘
                         │      ┌─── CORE RECALL PIPELINE ───────┐
                         │      │  embed question                 │
                         │      │  cosine-similar against saves   │
                         │      │  threshold 0.35, top-5          │
                         │      │  LLM cites saved titles + dates │
                         │      │  no match → fall-through banner │
                         │      └─────────────────────────────────┘
                         ▼
                   UNIFIED ANSWER
        text + Plotly chart (if any) + citations (RAG) or core sources (recall)
                         │
                         ▼
              FastAPI → dark-themed chat UI (port 8002)
        sidebar: topic-grouped sessions · uploads · 💾 save · 🗄 My Core modal
        each session row: ✏️ rename · 📁 move-to-topic · ✕ delete

   PERSISTENCE (coreckoner.db)              CORE
   • sessions (+ topic_id)                  • users (single 'default' for now)
   • messages / artifacts                   • core_topics (shared namespace)
   • uploads (+ summary_json)               • core_saves (+ topic_id, embedding_json)
```

---

## 3. Phase-by-Phase Progress

### Phases 1–3 — Foundation (✅ shipped)

| Capability | Status |
|---|---|
| RAG pipeline over 3 IRS publications, grouped citations | ✅ |
| Text-to-SQL over 7-table accounting DB | ✅ |
| Hybrid router (SQL / RAG / BOTH) | ✅ |
| Plotly auto-charts (bar / pie / line) | ✅ (v2.10.1 fixed bar misrender + ordering) |
| Schema-grounded SQL refusals | ✅ |
| Conversation memory | ✅ |
| Bilingual comprehension (Korean + English) | ✅ |
| Persistent multi-session chat | ✅ |
| Per-session CSV / Excel upload → session SQLite DB | ✅ |
| Per-session PDF upload → session-scoped ChromaDB | ✅ |
| Session-delete cascade (SQLite + session DB + vectors) | ✅ |
| Friendly categorized error messages | ✅ |

### Phase 4 Warm-up — Router PDF-awareness (✅ shipped, v2.5.1)

### Phase 4a — Data model foundation (✅ shipped, v2.6.0)
Three tables added: `users`, `core_topics`, `core_saves` (with `embedding_json`
provisioned for 4d). Full CRUD, no user-visible change.

### Phase 4b — Save (✅ shipped, v2.7.0, commit `5e291b8`)
- 4b-1: Rich `summary_json` captured at upload-ingest. Idempotent ALTER migration.
- 4b-2: 💾 Save button on every assistant message and upload. `POST /core/save`,
  `GET /core/saves`. Filled-state race condition caught and fixed.

### Phase 4c — Topics + My Core Data (✅ shipped, v2.8.0, commit `66b2125`)
- 7 thin endpoints over the 4a CRUD.
- 🗄 **My Core** header button opens a modal with topics column (All / Unsorted /
  user topics with live counts) and saves column (kind badge, title, content preview,
  topic dropdown to move, archive button).

### Phase 4d — Natural-language recall (✅ shipped, v2.9.0, commit `ce5e6a5`)

**The flagship.** Save→recall vision becomes functional end-to-end.

- `pipelines/core_embed.py` (new) — `text-embedding-3-small` helper + pure-Python
  cosine similarity.
- `pipelines/core_recall_pipeline.py` (new) — embeds question, scores saves by
  cosine, threshold 0.35, top-5, LLM composes a grounded answer citing saved
  titles and dates.
- `routers/query_router.py` — `CORE_RECALL` as a 4th route with hybrid detection:
  9 explicit trigger phrases force deterministic routing; LLM also told the route
  exists and may pick it.
- `main.py` v2.9.0 — wires the route, embeds saves on commit (best-effort),
  implements transparent fall-through with visible amber banner when recall
  finds nothing.
- `scripts/backfill_save_embeddings.py` (new) — one-time fill for pre-4d saves.
- Frontend: purple **CORE** badge, amber fall-through banner, core-sources panel
  listing matched saves with relevance scores.

**Verified end-to-end:** 3 saves backfilled cleanly; "Recall saved net income"
returned CORE badge with Q1 data and sources panel (relevance 0.49 for Q1 saves,
0.40 for related Apple save — all above 0.35); "What did I save about pizza?"
showed fall-through banner (best 0.11) and demoted to SQL; "Show revenue by
service line" routed cleanly to SQL with no false-positive on recall.

### v2.9.1 — Auto session titles (✅ shipped, commit `eaf2383`)

**Foundation for 4e — meaningful names before topic grouping.**

After the first user+assistant exchange in a session, fires a small `gpt-4o-mini`
call (~$0.0005) generating a 3-6 word title in the user's language. Manual rename
via PATCH /sessions/{id} still overrides; set-once on first exchange only.

Critical fix in this version: **`is_first_exchange` detection.** Previously
`is_new_session` only fired when `/chat` was called without a session_id, so
sessions created via `POST /sessions` (the "+ New Chat" button) had their titles
stuck on "New Chat" forever. The new detection covers both inline-created sessions
AND empty pre-existing sessions.

Companion script: `scripts/backfill_session_titles.py` — dry-run by default,
`--apply` to write. Idempotent.

**Verified:** 6 existing sessions backfilled cleanly with distinct titles
(English + Korean), live test confirmed set-once behavior, Korean title generated
from Korean question.

### v2.10.0 — Phase 4e: Topic-grouped sidebar (✅ shipped)

Sessions can now be assigned to a topic, sharing the same namespace as 4c saves.
Sidebar regrouped into collapsible topic sections.

**Backend:**
- `sessions.topic_id` column (idempotent ALTER for migrations). On fresh DBs the
  column has a working `REFERENCES core_topics ON DELETE SET NULL` FK; on migrated
  DBs the FK can't be added retroactively (SQLite limitation), so `delete_topic()`
  explicitly clears affected `sessions.topic_id` for both schema paths.
- `update_session_topic(session_id, topic_id)` thin setter.
- `get_all_sessions()` returns `topic_id` for sidebar grouping.
- New endpoint: `PATCH /sessions/{id}/topic` with `{topic_id}` or
  `{topic_id: "__none__"}` or `{clear_topic: true}`.
- Smoother default in `/core/save`: a save inherits its source session's topic
  (`_inherit_session_topic` helper) so saves from topic-tagged sessions land in
  the right topic without manual sorting.

**Frontend:**
- Sidebar regrouped under collapsible topic headers ("📁 Q1 Tax Work (3)",
  "📁 Unsorted (5)"). Empty topic groups don't render.
- Each session row gets a third hover action: 📁 opens a floating topic-assignment
  menu showing all topics + Unsorted, current selection marked with ✓.
- `collapsedTopics` Set tracks per-group collapse state across re-renders.
- Topic CRUD in My Core modal also refreshes the sidebar so
  rename/delete ripple correctly.

**Verified end-to-end:**
- Multiple sessions assigned to existing topic, sidebar regrouped live
- Topic rename in modal → sidebar header updates
- Topic delete in modal → sessions move to Unsorted
- Per-group collapse independent and persistent across renders
- Korean session and English sessions coexist under same topic (shared namespace
  transcends language)

### v2.10.1 — Chart fix + chart_builder.py extraction (✅ shipped)

Two real bugs fixed alongside a small architectural improvement.

**New file `pipelines/chart_builder.py`:**
- `infer_chart_hint(columns, rows, question)` — chart-type decision
- `reorder_for_chart(columns, rows, chart_hint)` — defensive DESC sort for bar
  charts (idempotent, pass-through for non-bar)
- `build_chart_spec(...)` — packages frontend payload

**Bug (1): Line-vs-bar misrender.** The old `_infer_chart_hint` in
`sql_pipeline.py` matched substring `"line"` against the question, so
"Show revenue by service line as a bar chart" routed to a line chart because
"service **LINE**" was caught before the explicit "bar chart" phrase. The new
`infer_chart_hint` phrase-matches explicit chart requests
(`"bar chart"`, `"pie chart"`, `"as a line chart"`) BEFORE falling through to
substring heuristics. Trend keywords still route to line.

**Bug (2): Bar chart data ordering.** The data table and chart sometimes showed
rows in original-DB order even when the SQL had `ORDER BY` (whether the LLM
omitted it or the order didn't survive end-to-end didn't matter — the symptom
was the same). `reorder_for_chart` defensively sorts bar-chart data DESC by the
numeric column. The reorder happens once in `run_sql_pipeline` so the data table,
chart, and LLM's explanation all see the same meaningful order.

`sql_pipeline.py`: `_infer_chart_hint` removed (moved to chart_builder), chart
hint inference + reorder applied to raw_data before building result_str for the
LLM explanation. `main.py` v2.10.1: imports `build_chart_spec`, uses it instead
of inline dict construction.

**Verified end-to-end:**
- "Show revenue by service line as a bar chart" → bar chart, Consulting Revenue
  ($345,500) as leftmost bar, table+chart+narrative all agreeing on order
- "Show net income trend" → still routes to line chart (trend keyword)
- "What are the revenue figures by service line" → bar via data-shape heuristic
  (5 rows × 2 cols), no false-positive on "line"

---

## 4. Current Data Model (coreckoner.db)

```
sessions(session_id, title, topic_id, created_at, updated_at)
  topic_id REFERENCES core_topics ON DELETE SET NULL  ← Phase 4e
messages(message_id, session_id→sessions, role, content, pipeline_used, timestamp)
artifacts(artifact_id, message_id→messages, artifact_type, content_json, created_at)
  artifact_type values: sql_query, sql_result, citations, route_explanation,
                        response_type, chart_spec,
                        core_sources, core_fallthrough_note   ← Phase 4d
uploads(upload_id, session_id→sessions, filename, file_type, target,
        table_names, chunk_count, row_count, summary_json, uploaded_at)
users(user_id, email, display_name, created_at, is_default)
core_topics(topic_id, user_id→users, name, created_at, UNIQUE(user_id, name))
core_saves(save_id, user_id→users, topic_id→core_topics(SET NULL), kind,
           source_session_id, source_message_id, source_upload_id,
           title, content, metadata_json, note, embedding_json,
           created_at, archived_at)
```

Demo accounting data (separate `accounting.db`, unchanged): accounts_payable 45,
revenue 53, balance_sheet 28, profit_loss 36, accounts_receivable 14,
general_ledger 139, chart_of_accounts 59.

**Cumulative design decisions:**
- Saved items **outlive** the session they came from (session-delete does not
  delete `core_saves`).
- Saves default to **Unsorted** at save time unless their source session has a
  topic assigned, in which case they inherit it (Phase 4e smoother default).
- `embedding_json` provisioned in 4a to avoid a migration in 4d.
- Embed-on-save is best-effort; backfill script exists for any save without an embedding.
- Hybrid routing for recall: triggers + LLM + fall-through (4d).
- Sessions and saves **share** the topic namespace but have **independent**
  topic assignments (Phase 4e). See §6 below.

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

**Backups** (one-liner pattern):
```bash
mkdir -p ~/Desktop/"application backup zips" && \
cd "/Users/sanghyunseong/Desktop/Z26 Glob NG consult" && \
zip -r ~/Desktop/"application backup zips"/app2_$(date +%Y-%m-%d_%H%M)_<tag>.zip \
  "app 2 - chatbot/app2" \
  -x "*/venv/*" "*/outputs/chroma_db/*" "*/outputs/sessions/*" \
     "*/.git/*" "*/.env" "*/__pycache__/*" "*.pyc" "*.DS_Store"
```

**Safe-install pattern** (used when installing modified files):
```bash
# Back up in place before overwriting
cp file.py file.py.bak
# Install the new version
cp ~/Downloads/.../file.py file.py
# Test; if anything's wrong, instant rollback:
cp file.py.bak file.py
# When verified, clean up:
rm file.py.bak
```

---

## 6. Important Behavioral Clarification — Session Topic vs Save Topic

Discovered during 4e testing. **Not a bug — by design — but worth documenting
because the expected workflow can mislead.**

**The data model has two separate `topic_id` columns:**
- `sessions.topic_id` — what topic the conversation belongs to
- `core_saves.topic_id` — what topic the saved answer belongs to

Both share the same `core_topics` namespace. But **assignments are independent**:
moving a save to a topic does NOT move its originating session, and vice versa.

**The one place they connect:** at save time, `_inherit_session_topic` flows
**session → save** (a save from a topic-tagged session inherits that topic).
The opposite flow (save → session) does not exist.

**Why this design:** a single session can produce multiple saves about different
topics (e.g. a session that drifts from Q1 tax work into Apple's 10-K research
should yield saves in two different topics). Force-coupling would fight the user.

**The misleading workflow** (encountered during 4e testing):
1. User saves three answers from three sessions
2. User opens My Core, creates a new topic, drops the three saves into it
3. User expects the three **sessions** to also move to the new topic in the sidebar
4. They don't — only the saves moved
5. User assigns the topic separately via the sidebar 📁 menu — works

**Current workaround:** assign session topics from the **sidebar 📁 menu**, not
from My Core. My Core organizes saves; the sidebar organizes sessions. Two
gestures, two intents.

**Polish item queued for Phase 5** (small, after auth):
- Add an **"Also move source sessions"** checkbox next to the topic dropdown in
  the My Core save card. Default unchecked (preserves current independence),
  checked when the user wants the bulk move.
- This makes the cross-cutting operation possible without changing the underlying
  independence model. The user opts in.

---

## 7. Known Notes & Trade-offs

- **LangChain Chroma migration deferred** — `langchain_community.vectorstores.Chroma`
  is deprecated, but migrating hits a Python 3.13 + numpy 2.x dependency wall.
  Deprecation + ChromaDB telemetry warnings on startup are cosmetic.
- **PyPDF "wrong pointing object" warnings** on some PDFs (e.g. Apple 10-K)
  are harmless — the document ingests cleanly.
- **Single hard-coded user** (`default`) throughout Phase 4. Real multi-user
  support is Phase 5 (primary scope).
- **Native dialogs** for topic rename/delete and save archive (`prompt()` /
  `confirm()`) — functional, themed later as Phase 5 polish.
- **Embed-on-save is best-effort** — a failure logs to console and doesn't block
  the save; the backfill script can fill any gaps.
- **Recall-route similarity threshold is 0.35** (tuned for small core size). If
  the user's core grows large and false positives appear, may need bumping to 0.45–0.50.
- **chart_builder thresholds** (`len(rows) <= 15` / `<= 20`) for bar-chart
  data-shape detection are heuristics from Phase 3. Preserved unchanged in
  v2.10.1; could be revisited if the dataset shape changes.

---

## 8. Current Versions & Commits

- Backend `main.py`: **v2.10.1** (banner: "v2.10.1 · Phase 4e + chart fix")
- Latest commit: **`v2.10.1`** — chart fix + chart_builder.py extraction

**Phase 4 close-out commit chain:**
- 4d natural-language core recall (`ce5e6a5`)
- v2.9.1 auto-generated session titles, language-matched (`eaf2383`)
- v2.10.0 Phase 4e topic-grouped session sidebar
- v2.10.1 chart fix + chart_builder.py extraction

**Demo status:** functional end-to-end. The flagship save→recall vision works,
the sidebar is meaningfully navigable, the bar chart bug is fixed, topic
grouping organizes the workspace. Two streams remain for Phase 5 (see §9).

---

## 9. Phase 5 — Plan & Re-initiate Prompt

Phase 5 brings the app from "demo-ready single-user" to "ready for full-scale
business case simulations and broader use." Two streams:

### Stream A — Real authentication (primary scope)

The single hard-coded `default` user has carried Phase 4 perfectly fine for a
demo, but it's the blocker for any multi-tenant use or genuine portfolio
deployment. Phase 5 lands real auth.

**Scope:**
- Auth module (login, signup, password hashing — bcrypt or argon2)
- Session-based or JWT auth (decision in Phase 5)
- Every existing endpoint scoped to `current_user` instead of `DEFAULT_USER_ID`
- Login and signup UI (themed to match existing dark surface)
- "Forgot password" stretch goal — possibly deferred
- Per-user data isolation enforced at the DB query level (sessions, saves,
  topics, uploads — all scoped by `user_id`)

**Non-goals for Phase 5** (production hardening, not feature):
- Email verification flow
- 2FA
- OAuth providers (Google, GitHub) — possible but not required
- Encryption at rest, HTTPS, rate limiting — separate from auth, may slip to
  a Phase 6 production-deployment pass

### Stream B — "Also move source sessions" checkbox (small polish)

Add an opt-in checkbox to the My Core save card so when a save's topic is
changed, the user can optionally have the originating session move to the
same topic. Small UI addition, small backend change (extend the save-update
endpoint to accept an `also_move_session` flag).

This closes the workflow gap identified in §6 without changing the underlying
independent-assignment model.

### After Phase 5 — Business case simulation testing

Once auth is in place and the small polish item is shipped, run a systematic
stress-test pass: 15-20 realistic accounting scenarios across:

- **Month-end close**: variance analysis, GL drill-down, P&L commentary
- **AR follow-up**: aging deep-dives, billing partner load, collection priority
- **IRS deposit questions**: late penalty thresholds, deposit schedule edge cases
- **Mixed RAG+SQL**: "what's our overdue AP and what does the IRS say about it"
- **Recall scenarios**: build up a topic of saves over multiple sessions, test
  recall freshness and cross-session continuity

Output is a test report quantifying flexibility and finding bugs, NOT a Loom
video. Demo recordings come after the bug pass.

### Re-initiate prompt for the next session

When you come back to start Phase 5, paste this:

> Picking up CoReckoner Phase 5. State: Phase 4 closed and committed.
> Current version v2.10.1 — 4d recall + v2.9.1 auto-titles + 4e topic-grouped
> sidebar + chart fix all shipped and verified end-to-end.
>
> Phase 5 has two streams per `DEV_NOTE_through_Phase4.md`:
>
> 1. **Stream A (primary): real authentication** — login, signup, password
>    hashing, JWT or session-based auth, scope every endpoint to `current_user`
>    instead of `DEFAULT_USER_ID`, login/signup UI matching the existing dark
>    theme. Per-user data isolation enforced at the DB layer.
>
> 2. **Stream B (small polish, after auth)**: "Also move source sessions"
>    checkbox in the My Core save card so users can opt in to the save-topic →
>    session-topic ripple. Closes the workflow gap discovered during 4e testing.
>
> Today: start Stream A. We need to decide architecture (JWT vs sessions, password
> storage approach, registration flow). Discuss design first, build second.
>
> Files I'll likely paste when we get to building: backend/main.py (v2.10.1),
> backend/db/session_store.py, backend/static/index.html, possibly a new
> backend/auth.py.

That re-initiate paragraph, plus the discussion, gets next-session-Claude
straight into Phase 5 design without re-litigating Phase 4 decisions.
