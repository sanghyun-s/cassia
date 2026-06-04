# CASSIA — Cumulative Development Note (through Phase 5 close-out)

> **An AI-powered accounting assistant** that answers plain-English questions
> about both unstructured documents (IRS publications + user PDFs) and structured
> financial data (QuickBooks-style exports), with persistent multi-session chat,
> per-session file uploads, natural-language recall of saved answers, auto-
> generated session titles in the user's language, a topic-grouped sidebar,
> **invite-only multi-user authentication**, and **per-user data isolation
> enforced at every layer (API, relational DB, vector store).** Served through
> a FastAPI backend (port 8002) and a dark-themed chat UI.

**Status as of this note: Phase 5 is closed.** Phases 1–5 are complete,
committed, tested end-to-end, and pushed to GitHub. The application is
single-server multi-user ready: auth, data isolation, hybrid SQL+RAG routing
with chart auto-rendering, the flagship save→recall workflow, topic
organization, and the cross-cutting polish item ("also move source session")
all functional and verified.

**Next milestone: Phase 6 — systematic business-case simulation testing.**
This is testing work, not coding. Scenarios will be provided separately; output
is a structured test report quantifying the application's behavior across
realistic accounting workflows.

---

## 1. What This Project Does

A unified accounting chatbot combining several capabilities under one
interface:

- **RAG pipeline** — answers policy/regulation questions grounded in three IRS
  publications (Pub 15, 15-T, 15-B), with inline source citations.
- **Text-to-SQL pipeline** — converts plain-English questions into SQL over a
  7-table accounting database, returning exact numbers with auto-generated
  Plotly charts.
- **Hybrid router** — classifies each question and routes to SQL, RAG, BOTH,
  or CORE_RECALL. PDF-aware (knows which uploads the session has) so the same
  question can route differently depending on session context.
- **Persistent multi-session chat** — ChatGPT-style sessions saved to SQLite,
  restorable from a sidebar, with messages + artifacts (SQL, charts,
  citations, core sources) preserved.
- **Per-session file uploads** — CSV / Excel into a session SQLite DB; PDF into
  a session-scoped ChromaDB collection. Each upload carries a rich summary
  captured at ingest.
- **User-controlled "core"** — a permanent knowledge base. The user explicitly
  saves chosen answers or uploads into the core, organizes them into topics,
  and recalls them by asking in natural language from any session.
- **Auto-generated session titles** — first user+assistant exchange triggers a
  small LLM call that produces a 3-6 word title in the user's language
  (English, Korean, …).
- **Topic-grouped sidebar** — sessions and saves share a single topic namespace
  with an optional opt-in ripple ("also move source session") when re-organizing
  saves.
- **Multi-user authentication** — invite-only signup, email-or-username login,
  bcrypt-hashed passwords, server-side session cookies with sliding renewal,
  per-user data isolation at every layer.

The guiding vision: a "mini-ChatGPT for accountants" where **session =
scratchpad**, **core = vault**, **save = an explicit commit gesture**, **recall
= the payoff**, and **authentication keeps each user's reasoning private**.

---

## 2. Architecture (post-Phase 5)

```
                            USER QUESTION (via authenticated session)
                                       │
                                       ▼
                  QUERY ROUTER (history-aware, PDF-aware, recall-aware)
              Trigger phrases → CORE_RECALL (deterministic)
              Otherwise: LLM picks SQL / RAG / BOTH / CORE_RECALL
                       │                                  │
              ┌────────┘                                  └────────┐
              ▼                                                    ▼
        TEXT-TO-SQL PIPELINE                              RAG PIPELINE
        schema-grounded SQL                               dual-collection retrieval:
        on accounting.db +                                • irs_pub15  (globally readable)
        per-session uploads                               • user_uploads (session+user filtered)
        → chart_builder.py:                                       │
          • infer_chart_hint                                      │
          • reorder_for_chart (bar DESC)                          │
              │                                                   │
              └────────────────────┬──────────────────────────────┘
                                   │      ┌─── CORE RECALL PIPELINE ────────┐
                                   │      │  embed question                 │
                                   │      │  cosine over saves              │
                                   │      │  threshold 0.35, top-5          │
                                   │      │  LLM cites saved titles + dates │
                                   │      │  no match → fall-through banner │
                                   │      └─────────────────────────────────┘
                                   ▼
                            UNIFIED ANSWER
        text + Plotly chart (SQL) + citations (RAG) + sources (recall)
                                   │
                                   ▼
                  FastAPI on port 8002, behind auth dependency
              CORS: allow_origins=["http://localhost:8002"], credentials enabled
              Cookie: HttpOnly · SameSite=Lax · 30-day sliding renewal
              Login UI: dark-themed inline SPA · email-or-username · invite-only signup

   PERSISTENCE (coreckoner.db)                  AUTHENTICATION (Phase 5a)
   ├─ sessions (+ user_id, topic_id)            ├─ users
   ├─ messages / artifacts                      │   email · username · password_hash
   ├─ uploads (+ user_id, summary_json)         │   invite_code_used · is_admin · is_default
   ├─ core_topics (per-user)                    └─ auth_sessions
   └─ core_saves (+ topic_id, embedding_json)       session_token · user_id · expires_at

   VECTOR STORE (chroma_db)
   ├─ irs_pub15        (no user filter — global reference content)
   └─ user_uploads     (every chunk tagged {session_id, user_id} — Pass 3)
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
| Schema-grounded SQL refusals | ✅ |
| Conversation memory | ✅ |
| Bilingual comprehension (Korean + English) | ✅ |
| Persistent multi-session chat | ✅ |
| Per-session CSV / Excel upload → session SQLite DB | ✅ |
| Per-session PDF upload → session-scoped ChromaDB | ✅ |
| Session-delete cascade (SQLite + session DB + vectors) | ✅ |
| Friendly categorized error messages | ✅ |

See earlier dev notes for full detail.

### Phase 4 — Save & Recall + UX completeness (✅ shipped, closed)

See `DEV_NOTE_through_Phase4.md` for the full record. Recap:

- **4a** — data model foundation (users, core_topics, core_saves with
  embedding_json provisioned for 4d)
- **4b** — Save button on every assistant message + upload; rich summary_json
  captured at ingest
- **4c** — My Core modal with topics + saves columns
- **4d** — the flagship: natural-language recall via embeddings + cosine
  similarity + new router route (CORE_RECALL)
- **v2.9.1** — auto-generated session titles in the user's language
- **4e** — topic-grouped sidebar (sessions and saves share namespace)
- **v2.10.1** — chart fix + chart_builder.py extraction

After Phase 4, the application was demo-ready but single-user. Phase 5 brought
it to multi-user production-discipline.

### Phase 5a — Auth foundation (✅ shipped, commit `f2ace55`)

The scaffolding pass — new files, no behavior change to existing endpoints.

**New files:**
- `backend/auth.py` — bcrypt password hashing via `passlib`, 32-byte session
  token generation, `get_current_user()` FastAPI dependency reading HttpOnly
  cookie + validating against `auth_sessions` + applying sliding renewal,
  `set_session_cookie` / `clear_session_cookie` helpers.
- `backend/db/auth_migrations.py` — idempotent `migrate()` adding columns to
  `users` (password_hash, username, invite_code_used, is_admin) and `user_id`
  to `sessions` and `uploads`. Creates `auth_sessions` table. Case-insensitive
  UNIQUE indexes for email and username.
- `backend/db/auth_queries.py` — user CRUD with case-insensitive
  email-or-username lookup, `claim_orphaned_data()` for first-signup
  migration, auth-session CRUD.
- `backend/routers/auth_router.py` — `POST /auth/signup`, `POST /auth/login`,
  `POST /auth/logout`, `GET /auth/me`.

**.env additions:** `SIGNUP_INVITE_CODE=cassia-mvp-2026`,
`SESSION_LIFETIME_DAYS=30`, `COOKIE_SECURE=false`.

**Touch to existing code:** two additive edits to `main.py` (import + lifespan
migration call + router include). Nothing else changed in Phase 4 code paths.

### Phase 5b/c — Endpoint scoping + login UI + CASSIA rename (✅ shipped, commit `63c648b`)

The "make it actually multi-user" pass. Banner v2.10.1 → v2.11.0.

**Backend (Pass 2 — endpoint scoping):**
- `current_user: User = Depends(get_current_user)` added to every endpoint
  serving user data
- `_assert_*_owned_by` helpers (sessions, topics, uploads, saves) — each
  returns **404 (not 403)** on mismatch so existence isn't leaked to
  unauthorized callers
- CORS hardened: `allow_origins=["http://localhost:8002"]`,
  `allow_credentials=True`
- bcrypt warning suppressed cosmetically via
  `logging.getLogger("passlib").setLevel(logging.ERROR)`

**New file:** `backend/db/auth_reclaim.py` — extracted from
`auth_queries.claim_orphaned_data`, made idempotent (runs only when user owns
0 entities AND orphans exist). Handles the rare second-signup-after-claim
edge case.

**Frontend (Pass 4):**
- Dark-themed inline login + signup SPA at `index.html`
- `apiFetch` helper that adds `credentials: 'include'` to every fetch
- Header user dropdown with logout
- All 23 fetch sites get cookie-credentials threading
- "CoReckoner" → "CASSIA" throughout (header, welcome screen, banner, page
  title, cookie name `cassia_session`)
- Themed inline errors for wrong password / email taken / username taken /
  wrong invite code

**Verified end-to-end with 11 smoke tests:** curl /auth/me 401 → browser
login → welcome toast → session restore with artifacts → fresh chat with
CASSIA label → topic move with toast → save flow (12→13) → My Core modal →
logout (cookie cleared) → wrong-password themed error → duplicate-email
themed error → re-login (idempotent reclaim no-op).

**GitHub workflow:** initial push rejected due to a web-edit on the README
during the session; resolved via `git stash` + `git pull --rebase` + `git
push`. The README's CASSIA title used an em-dash on both sides (web edit and
local edit converged on the same character), so the stash was dropped as
redundant after rebase.

### Phase 5c (Pass 3) — ChromaDB user isolation (✅ shipped, commit `77b7b59`)

Defense-in-depth at the vector store. Banner v2.11.0 → v2.12.0.

**The problem:** pre-Pass-3 the `user_uploads` collection's chunks were tagged
only with `session_id`. The Phase 5b API layer verified session ownership
before any RAG query, so cross-user retrieval was already blocked in practice
— but a single bug at the API layer would silently expose another user's
content because the vector store itself had no knowledge of users.

**Pass 3 pushes the check down into the metadata.** Every chunk now carries
`{session_id, user_id}` and every retrieval applies both as a hard
conjunction filter via `$and`. Even if a session_id leaks (shared URL, log
file, future "share session" feature), the user_id check at the store layer
still blocks cross-user reads.

**Files modified:**
- `backend/uploads/document.py` — `ingest_pdf()` now REQUIRES `user_id` (no
  default, no fallback). Raises `ValueError` if missing. Vector metadata gains
  `user_id` alongside the existing fields.
- `backend/pipelines/rag_pipeline.py` — new `_query_user_uploads(question,
  user_id, session_id, k, chroma_dir)` helper, **THE ONLY entry point** for
  user_uploads retrieval. Docstring explicitly warns against bypassing it.
  `_retrieve()` and `run_rag_pipeline()` accept `user_id` (Optional — IRS
  query still works if missing).
- `backend/routers/upload_router.py` — temporary try/except TypeError fallback
  from Phase 5b/c REMOVED. ingest_pdf is called with
  `user_id=current_user.user_id` unconditionally.
- `backend/main.py` `/chat` — one-line addition: pass
  `user_id=current_user.user_id` into `run_rag_pipeline(...)`.

**New file:** `backend/scripts/wipe_user_uploads.py` — one-time migration
script. Drops the `user_uploads` ChromaDB collection and deletes
`target='rag'` rows from `coreckoner.db.uploads`. Confirmation prompt
required (`type 'wipe'`).

**Migration:** existing vectors had no `user_id` metadata. The wipe script
ran cleanly (2 target='rag' rows + the collection), the user re-uploaded
`apple_10k_2024.pdf` into a designated demo session, RAG produced a correct
answer with citation. Direct ChromaDB metadata inspection confirmed every
chunk carries `'user_id': 'usr_d3ce41e79c5c'` alongside the session_id.

The IRS Pub 15 collection was NOT touched — it remains globally readable
reference content. CSV/Excel uploads (`target='sql'`) were NOT touched —
they live in per-session SQLite DBs and were already transitively user-safe
via Pass 2 session ownership.

### Phase 5 close-out (Pass 5) — "Also move source session" checkbox (✅ shipped)

The polish item that closes the workflow gap from §6 of
`DEV_NOTE_through_Phase4.md`. Banner v2.12.0 → v2.12.1 (patch-level).

**The workflow gap:** when a user moved a save's topic in My Core, the
originating chat session stayed in its old topic. The independence model
was architecturally correct (one session can produce saves about different
topics) but created friction — users had to do the same gesture twice.

**Pass 5's solution:** opt-in checkbox below the topic dropdown labeled
"Also move source session", default **unchecked**. When checked, moving the
save also moves the originating session to the same topic. Toast appends
" · session also moved" to the existing "Save moved · topic updated" message
when the ripple actually fires.

**Files modified:**
- `backend/main.py` — `SaveUpdateRequest` gains `also_move_session: bool =
  False`. PATCH /core/saves/{save_id} handler runs the opt-in ripple after
  the save itself moves: looks up source_session_id, confirms ownership via
  `session_belongs_to_user`, then calls `update_session_topic`. Silent skip
  for upload saves (no source session) or deleted sessions. Response
  includes `session_also_moved: bool` for the frontend.
- `backend/static/index.html` — `renderCoreSaves()` wraps topic dropdown +
  new checkbox in a column container inside `.core-save-foot`. Archive
  button still flush right. `moveSaveToTopic()` reads checkbox state,
  includes `also_move_session` in PATCH body, refreshes sidebar via
  `loadSessions()` when response confirms `session_also_moved`. Inline
  styles for the new label (intentional — keeps the change self-contained).

**New file:** `backend/scripts/apply_pass5.py` — surgical applier script
with `.bak` safety, all-or-nothing semantics (refuses to half-apply),
idempotent re-run (detects already-patched state via marker strings).

**Verified end-to-end:** checkbox renders below dropdown with unchecked
default; unchecked → only save moves, sidebar unchanged; checked → save
AND source session both move, sidebar refreshes, toast confirms; topic
counts in My Core updated correctly (e.g. Q1 Tax Work 2→1 and Net Income
1→2 after a checked move).

---

## 4. Current Data Model (post-Phase 5)

```
users(user_id, email, username, password_hash, display_name,
      invite_code_used, is_admin, is_default, created_at)
   email + username case-insensitive UNIQUE; first real signup claims
   pre-existing 'default'-owned data

auth_sessions(session_token PK, user_id→users, created_at, expires_at,
              last_seen_at)
   HttpOnly cookie tokens · sliding renewal · 30-day default lifetime

sessions(session_id, user_id→users, title, topic_id→core_topics(SET NULL),
         created_at, updated_at)

messages(message_id, session_id→sessions, role, content, pipeline_used,
         timestamp)

artifacts(artifact_id, message_id→messages, artifact_type, content_json,
          created_at)
   artifact_type ∈ {sql_query, sql_result, citations, route_explanation,
                    response_type, chart_spec, core_sources,
                    core_fallthrough_note}

uploads(upload_id, session_id→sessions, user_id→users, filename, file_type,
        target, table_names, chunk_count, row_count, summary_json,
        uploaded_at)

core_topics(topic_id, user_id→users, name, created_at,
            UNIQUE(user_id, name))

core_saves(save_id, user_id→users, topic_id→core_topics(SET NULL), kind,
           source_session_id, source_message_id, source_upload_id, title,
           content, metadata_json, note, embedding_json, created_at,
           archived_at)
```

**ChromaDB collections:**
- `irs_pub15` — IRS Pub 15, 15-T, 15-B chunks. No per-user filter; globally
  readable.
- `user_uploads` — per-session user PDF chunks. Every chunk's metadata has
  `{session_id, user_id, source_file, source_doc, source_type, page,
  page_display}`. Retrieval applies `$and: [{session_id}, {user_id}]` as a
  hard conjunction filter.

**Cumulative design decisions:**
- Saved items **outlive** the session they came from (session-delete does
  not delete `core_saves`).
- Saves default to **Unsorted** at save time unless the source session has a
  topic, in which case they inherit it (Phase 4e).
- `embedding_json` provisioned in 4a to avoid a migration in 4d.
- Embed-on-save is best-effort; backfill script exists.
- Sessions and saves **share** the topic namespace but have **independent**
  topic assignments. Pass 5 added an opt-in coordinated move
  (`also_move_session`); the independence model itself is unchanged.
- First real signup claims pre-existing demo data via
  `auth_reclaim.reclaim_data_for_user()` — idempotent, runs only when the
  user owns 0 entities AND orphans exist.
- The `default` user row remains in the DB as a **tombstone** — owns nothing
  after the first claim, useful for tracing what was pre-auth data.
- Server-side session cookies, not JWT — simpler, safer for a known web
  frontend, no token-refresh or blacklist machinery needed.
- ChromaDB user isolation is **defense in depth**: API layer (Pass 2) and
  vector store layer (Pass 3) both enforce. Either one alone is sufficient
  in practice; together they're robust against any single-layer bug.

---

## 5. How to Run

**Prerequisites:**
- Python 3.13 (tested on macOS ARM)
- OpenAI API key with access to `gpt-4o-mini` and `text-embedding-3-small`

**Setup (first time):**

```bash
git clone https://github.com/sanghyun-s/accounting-ai-chatbot.git cassia
cd cassia
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install 'passlib[bcrypt]>=1.7.4' 'bcrypt>=4.0.1,<5.0.0'
cp .env.example .env
# Edit .env:
#   OPENAI_API_KEY=sk-...
#   SIGNUP_INVITE_CODE=<choose-your-own>
#   SESSION_LIFETIME_DAYS=30
#   COOKIE_SECURE=false

# One-time data prep
python3 sql/phase1_load.py        # build accounting.db from CSVs
python3 rag/phase1_ingest.py      # index IRS publications into ChromaDB

# Run
python3 backend/main.py           # FastAPI on :8002
```

Open `http://localhost:8002` — chat UI loads. First signup with your invite
code claims any pre-existing demo data.

**Run from app2/ root** — `python3 backend/main.py` inside `backend/` looks
for `backend/backend/main.py` and fails. Always `cd` to the project root.

**Recurring run cycle:**
```bash
cd "/path/to/app2"
source venv/bin/activate
lsof -ti:8002 | xargs kill -9    # kill stale server if any
python3 backend/main.py          # start
```

**Backup pattern (idempotent one-liner):**
```bash
mkdir -p ~/Desktop/"application backup zips" && \
cd "/Users/sanghyunseong/Desktop/Z26 Glob NG consult" && \
zip -r ~/Desktop/"application backup zips"/app2_$(date +%Y-%m-%d_%H%M)_<tag>.zip \
  "app 2 - chatbot/app2" \
  -x "*/venv/*" "*/outputs/chroma_db/*" "*/outputs/sessions/*" \
     "*/.git/*" "*/.env" "*/__pycache__/*" "*.pyc" "*.DS_Store"
```

---

## 6. Important Behavioral Notes

### Session topic vs save topic — independence + opt-in ripple

The data model has two `topic_id` columns: `sessions.topic_id` and
`core_saves.topic_id`. Both share the `core_topics` namespace, but
assignments are **independent**.

**Why independent:** a single session can produce multiple saves about
different topics. Force-coupling would fight the user.

**The flow that connects them:** at save time, `_inherit_session_topic`
flows **session → save** (a save from a topic-tagged session inherits that
topic). After Pass 5, the user can also opt in to a **save → session**
ripple by checking the "Also move source session" checkbox in My Core. Both
flows are explicit; neither runs automatically without a user gesture.

### Defense in depth at the vector layer (Pass 3)

The API layer (Pass 2) verifies session ownership before any RAG query, so
cross-user retrieval is blocked at the controller level. Pass 3 adds a
second line of defense by tagging every PDF chunk with `user_id` and
applying both `session_id` AND `user_id` as a hard filter in the vector
query. Even if a session_id ever leaks, the user_id check at the store
layer still blocks cross-user reads.

The IRS Pub 15 collection has **no per-user filter** — it's reference
content, intentionally globally readable for all authenticated users.

### Authentication

- **Cookie:** HttpOnly, SameSite=Lax, 30-day default lifetime, sliding
  renewal on every authenticated request.
- **Invite code:** required at signup, validated against
  `SIGNUP_INVITE_CODE` from `.env`. Single shared code; rotate by editing
  `.env` and restarting the server.
- **Email or username login:** both work; lookup is case-insensitive.
  Email-lookup tried first; username-lookup as fallback.
- **First-signup-claims-all:** the first real signup runs
  `reclaim_data_for_user()` which assigns NULL-user sessions/uploads and
  'default'-owned saves/topics to the new account. Idempotent — runs only
  when the user owns 0 entities AND orphans exist.
- **Logout vs session expiry:** logging out deletes the auth_sessions row
  AND clears the cookie. Closing the browser tab without logging out leaves
  the row in place; the cookie persists until the 30-day expiry (or sliding
  renewal extends it).
- **Tombstone default user:** the original `default` user remains in the
  `users` table after a claim — owns nothing, useful for tracing what was
  pre-auth data.

### Session lifecycle (closing tab vs logging out)

Closing a tab or stopping the server does NOT log you out:
- `auth_sessions` rows are persisted in `coreckoner.db` (SQLite, survives
  process death)
- HttpOnly cookie has `Max-Age=2592000` (30 days, NOT a browser-session-only
  cookie)
- 30-day auto-expiry is enforced via the `expires_at` check in
  `get_current_user`

Deliberate logout matters only for shared machines or when revoking access
explicitly.

---

## 7. Known Notes & Trade-offs

- **LangChain Chroma migration deferred** — `langchain_community.vectorstores.Chroma`
  is deprecated, but migrating hits a Python 3.13 + numpy 2.x dependency
  wall. Deprecation + ChromaDB telemetry warnings on startup are cosmetic
  and don't affect behavior.
- **ChromaDB telemetry warnings** — `Failed to send telemetry event
  ClientStartEvent: capture() takes 1 positional argument but 3 were given`
  appears on every ChromaDB client init. Known cosmetic issue with the
  pinned `chromadb` version. Harmless.
- **PyPDF "wrong pointing object" warnings** on some PDFs (e.g. Apple 10-K)
  are harmless — the document ingests cleanly.
- **Native dialogs** for topic rename/delete and save archive
  (`prompt()` / `confirm()`) — functional, themed later if needed.
- **Embed-on-save is best-effort** — a failure logs to console and doesn't
  block the save; the backfill script (`backfill_save_embeddings.py`) can
  fill any gaps.
- **Recall-route similarity threshold is 0.35** (tuned for small core
  size). If the user's core grows large and false positives appear, may need
  bumping to 0.45–0.50.
- **chart_builder thresholds** (`len(rows) <= 15` / `<= 20`) for bar-chart
  data-shape detection are heuristics from Phase 3.
- **Email verification, OAuth, 2FA — not implemented.** Deliberately out of
  scope for the MVP. Production deployment of CASSIA would need them.
- **HTTPS, rate limiting, encryption at rest — not implemented.**
  Deliberately out of scope for local-development. Would be a separate
  production-hardening pass.
- **bcrypt warning** suppressed cosmetically via
  `logging.getLogger("passlib").setLevel(logging.ERROR)` — `bcrypt 4.x +
  passlib 1.7.x` emits a version-detection warning that doesn't affect
  hashing or verification.
- **Author email placeholder** in git commits shows
  `your-github-email@example.com` — set `git config user.email` to your real
  GitHub-registered address to retroactively or prospectively link commits
  to your GitHub profile.
- **`.bak` files** from Pass 3 and Pass 5 install steps are gitignored and
  should be removed before commit — included in the install guides.

---

## 8. Current Versions & Commits

- Backend `main.py`: **v2.12.1** (banner: `v2.12.1 · Phase 5b/c (auth-required)`
  or `Phase 5 complete` if the optional cosmetic tag bump was applied)
- ChromaDB collections: `irs_pub15` (read-only reference),
  `user_uploads` (per-session + per-user metadata)

**Phase 5 commit chain on `origin/main`:**

| Hash | Pass | Description |
|---|---|---|
| `f2ace55` | 5a | Auth foundation (bcrypt, session cookies, invite-only signup) |
| `63c648b` | 5b/c | Endpoint scoping + login UI + CASSIA rename |
| `77b7b59` | 5c (Pass 3) | ChromaDB user isolation |
| _(this commit)_ | 5 close-out | "Also move source session" checkbox + dev note + README |

**Demo status:** functional end-to-end. Multi-user-capable architecture
(though currently one real user, SanghyunAcct, owns the demo data).

---

## 9. Phase 6 — Plan & Re-initiate Prompt

Phase 6 is **testing, not coding.** The application is feature-complete for
the MVP. What it needs now is systematic evidence of behavior across
realistic accounting workflows.

### Scope

15–20 realistic scenarios across:

- **Month-end close** — variance analysis, GL drill-down, P&L commentary,
  debit/credit reconciliation questions
- **AR follow-up** — aging deep-dives, billing partner load, collection
  priority, customer concentration
- **IRS deposit questions** — late penalty thresholds, deposit schedule edge
  cases, monthly vs semi-weekly classification
- **Mixed RAG+SQL** — "what's our overdue AP and what does the IRS say about
  late deposits", "show net income for Q1 and explain the major variances"
- **Recall continuity** — build a topic of saves over multiple sessions,
  then in a fresh session ask "what did I save about Q1" / "recall my net
  income notes" and verify continuity
- **Korean/English mix** — Korean questions returning Korean answers and
  Korean auto-titles; mixed-language sessions

### Output

A structured test report — NOT a Loom video. Demo recordings come after the
bug pass. For each scenario:
- The question asked
- The route taken (SQL / RAG / BOTH / CORE_RECALL / fall-through)
- The answer (verbatim or summary)
- Citations (page numbers, source documents)
- Charts rendered (if any)
- Time-to-answer (approximate)
- Pass / fail / partial assessment with notes

### Approach

User provides the scenarios in a structured list. CASSIA runs them in a
browser session (no code changes). User captures output (text + screenshots
+ short notes). After all scenarios run, a synthesis report categorizes
findings:

- **What worked** — scenarios that returned high-quality answers
- **What surprised** — emergent behaviors worth noting
- **Bugs surfaced** — anything that broke or returned wrong data
- **Flexibility ceiling** — questions the architecture can't currently handle

That report becomes the portfolio artifact next to the code.

### Re-initiate prompt for Phase 6

When you come back to start Phase 6:

> Picking up CASSIA Phase 6 (business-case simulation testing). State:
> Phase 5 closed — auth, data isolation, RAG+SQL, recall, topic
> grouping, polish item all shipped and pushed to GitHub. Banner
> v2.12.1, latest commit on origin/main is the Phase 5 close-out.
> Account: SanghyunAcct owns 11 sessions, 3 topics, 14+ saves, the
> apple_10k_2024.pdf upload in a designated demo session.
>
> Today: run the 15–20 scenarios I'll provide and capture output. No
> code changes. Output is a structured test report.

That paragraph plus the scenarios is enough for a fresh session to start
testing immediately.

---

## Closing note

Phase 5 was disciplined production-hardening work, not feature exploration.
The pattern that made it possible to ship across multiple sessions:

1. **Plan before code.** Every pass started with a locked design (decisions
   numbered, alternatives rejected explicitly) before any file was edited.
2. **Backup before install.** Every commit has a corresponding pre-`<pass>`
   backup zip on disk.
3. **Idempotent migrations.** Every schema change uses `_ensure_column` +
   `CREATE IF NOT EXISTS`. Re-running the server on a migrated DB is
   always safe.
4. **Smoke-test before commit.** Every pass has a documented test sequence
   that was actually executed before `git push`.
5. **Dev note as the durable artifact.** Code changes; the dev note is what
   makes the changes legible to future-you.

That's the project's primary engineering practice. It's why the work is
durable across long gaps.
