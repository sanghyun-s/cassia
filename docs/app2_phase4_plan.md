# CoReckoner — Phase 4 Plan
## Save & Recall Architecture (Demo-Grade)

*Locked: 2026-XX-XX. To revisit only if mentor pushes back.*

---

## Vision

CoReckoner becomes a personal accounting assistant where users **explicitly choose what to save** to a permanent core database, and **recall it later by asking in natural language across sessions.**

Inspiration: *"Like a cosmetic 2026 tax form prep that pulls 2025 tax return info — historical data should be loadable on demand. Not auto-saved as a single dump, but as a database where the user chooses what to save to secure storage, organized by topic."*

---

## Locked design decisions

| Decision | Choice | Why |
|----------|--------|-----|
| **Two-pass approach** | Phase 4 = demo-grade, Phase 5 = production hardening | "Demo-ready in a few weeks" timeline. Encryption and full auth are Phase 5 problems. |
| **Audience** | 1-3 trusted users initially, public someday | Drives architecture to be retrofittable, not security-paranoid yet |
| **Save-time topic selection** | No dropdown at save-time. Organize later in 4c | Simpler 4b, faster ship. Don't make user think during save. |
| **Auth in Phase 4** | Single hard-coded user_id baked in, real auth added in 4f only if needed | Skip auth complexity until features prove themselves |
| **Encryption at rest** | NOT in Phase 4 — moved to Phase 5 | Demo-grade. Add when real strangers can sign up. |
| **Router PDF-awareness fix** | Done as warm-up before 4a (15 min) | Polishes Phase 3 demo, light entry back into code |

---

## Pre-Phase-4 Warm-up — Router PDF-awareness fix

**Estimated time:** 15-20 min

**Problem:** When user asks *"What were Apple's total net sales for fiscal year 2024?"* in a session with an uploaded Apple 10-K, the router classifies as SQL (because of keywords like "total" and "sales") and the PDF is never queried.

**Fix in `routers/query_router.py`:**
- Accept `session_id` parameter
- Look up uploaded files via `list_uploads(session_id)`
- If PDFs exist in session, append to classification prompt:
  > *"This session has uploaded PDFs ({filenames}). Questions that could be about those documents should prefer RAG or BOTH, even if they mention numbers."*
- Pass `session_id` from `main.py`'s `/chat` handler

**Test:** Upload `apple_10k_2024.pdf`, ask *"What were Apple's total net sales for fiscal year 2024?"* without saying "uploaded" — should route to RAG and give the $391B answer.

---

## Phase 4a — Data Model + Auth Scaffolding

**Estimated time:** 1 session
**User-visible changes:** None

**Goal:** Build the database foundations every future phase depends on. No new UI yet.

**Schema additions to `coreckoner.db`:**

```sql
CREATE TABLE users (
    user_id      TEXT PRIMARY KEY,
    email        TEXT UNIQUE,           -- nullable for now
    display_name TEXT,
    created_at   TEXT NOT NULL,
    -- Demo-grade: no password_hash, no oauth tokens yet
    is_default   INTEGER DEFAULT 0      -- 1 for the hard-coded single user
);

CREATE TABLE core_topics (
    topic_id    TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE(user_id, name)
);

CREATE TABLE core_saves (
    save_id          TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    topic_id         TEXT REFERENCES core_topics(topic_id) ON DELETE SET NULL,
    kind             TEXT NOT NULL CHECK(kind IN ('message','upload')),
    -- Provenance
    source_session_id TEXT,
    source_message_id TEXT,
    source_upload_id  TEXT,
    -- Snapshot of saved content (immutable)
    title            TEXT,            -- short label, e.g. first 80 chars of message
    content          TEXT,            -- full message text OR upload summary
    metadata_json    TEXT,            -- {sql_query, citations, etc.}
    note             TEXT,            -- optional user note at save time
    -- Lifecycle
    created_at       TEXT NOT NULL,
    archived_at      TEXT             -- soft delete
);

-- Indexes for the recall pipeline
CREATE INDEX idx_core_saves_user      ON core_saves(user_id, archived_at);
CREATE INDEX idx_core_saves_topic     ON core_saves(topic_id);
CREATE INDEX idx_core_topics_user     ON core_topics(user_id);
```

**New helpers in `backend/db/session_store.py`:**

```python
# Users
ensure_default_user() -> str               # returns user_id "default"
get_user(user_id) -> dict | None

# Topics
create_topic(user_id, name) -> str
list_topics(user_id) -> list[dict]
rename_topic(topic_id, new_name) -> bool
delete_topic(topic_id) -> bool             # also sets topic_id=NULL on saves

# Saves
create_save(user_id, kind, source_*, title, content, metadata_json, note) -> save_id
list_saves(user_id, topic_id=None) -> list[dict]
get_save(save_id) -> dict | None
update_save_topic(save_id, topic_id) -> bool
archive_save(save_id) -> bool              # soft delete
```

**Schema migration script:** `db/migrate_phase4a.py` — idempotent, checks if tables exist before creating.

**Bake in default user at startup:** In `main.py` lifespan, call `ensure_default_user()` and stash `DEFAULT_USER_ID` as a module-level constant. Every endpoint uses this until Phase 4f.

**Demoable?** No — foundation only. But `curl localhost:8002/stats` should show `user_count: 1`, `topic_count: 0`, `save_count: 0`.

**Tests:** Schema migration runs cleanly twice. Existing `/chat`, `/sessions`, `/uploads/*` endpoints still work unchanged.

---

## Phase 4b — Save Button (Per Message + Per Upload)

**Estimated time:** 1-2 sessions
**User-visible changes:** 💾 button appears on chat messages and uploads

**Goal:** User can click 💾 to save anything to their core database. No topic selection yet — saves go to a default "Unsorted" bucket.

**Backend additions:**

New endpoint:
```
POST /core/save
Body: { kind: "message" | "upload", source_id, note?: string }
Returns: { save_id, kind, title }
```

For `kind = "message"`:
- Look up the message + its artifacts (SQL query, citations, chart spec)
- Snapshot into `core_saves.content` (full text) and `metadata_json` (artifacts)
- Title = first 80 chars of message content

For `kind = "upload"`:
- Look up the upload row + retrieve summary
  - CSV: column names + row count + first 5 rows
  - PDF: filename + page count + chunk count + first 200 chars of first chunk
- Snapshot the summary, not the raw data (raw stays in session DB / ChromaDB)
- Title = filename

**Frontend additions to `index.html`:**

1. Add 💾 button next to each assistant message (small icon, right side of message body)
2. Add 💾 button next to each upload row in the "Uploaded files" sidebar section
3. On click: `POST /core/save` with the source_id
4. Show toast: *"Saved to core"*
5. Disable button briefly (avoid double-save)

**Visual indicator:** Already-saved items show a filled 💾 (vs outline). Backend exposes `GET /core/saves?source_message_id=X` to check.

**Demoable?** Yes:
- Ask a question, get an answer
- Click 💾 → toast appears
- Hard-refresh page → button shows filled state (proves it persisted)
- Click 💾 on an upload row in sidebar — same flow

**Tests:**
- Save a message → row exists in `core_saves`
- Save same message twice → returns existing save_id (idempotent), no duplicate
- Save an upload → snapshot captured correctly
- Source session deleted later → save still exists (decoupled storage)

---

## Phase 4c — Topic Organization

**Estimated time:** 1 session
**User-visible changes:** "My Core Data" panel in sidebar; topic CRUD

**Goal:** Saved items become navigable. User can create topics, assign saves to them, and browse.

**New endpoints:**

```
GET    /core/topics                       List all topics for user
POST   /core/topics      {name}            Create topic
PATCH  /core/topics/{id} {name}            Rename
DELETE /core/topics/{id}                   Delete (saves keep their data, lose topic)

GET    /core/saves?topic_id=X              List saves, optionally filtered
PATCH  /core/saves/{id}  {topic_id, note}  Move to topic / update note
DELETE /core/saves/{id}                    Archive (soft delete)
```

**Frontend additions:**

New sidebar section between "Recent sessions" and "Uploaded files":

```
MY CORE DATA  [+]
  ▼ Q1 Payroll (3)
      💬 W-2 question from May 14
      📄 payroll.csv summary
      💬 FICA calculation answer
  ▼ Tax 2025 (1)
      📄 apple_10k_2024.pdf
  ▼ Unsorted (4)
      ...
```

- Click topic header → expand/collapse
- Click save item → opens a modal with full content + "Move to topic" dropdown + "Open in original session" link
- `[+]` next to "MY CORE DATA" → create new topic dialog

**Visual:** Distinct from sessions. Tinted background or different border to signal "this is permanent, not chat scratchpad."

**Demoable?** Yes — this is when the project starts looking like a real product:
- "I save things over time, organize them into topics, browse by topic, edit notes."

**Tests:**
- Create 3 topics, move saves between them
- Delete a topic → its saves move to "Unsorted"
- Archive a save → disappears from listing
- Saves persist across server restarts

---

## Phase 4d — Recall via Natural Language (FLAGSHIP)

**Estimated time:** 2 sessions
**User-visible changes:** *"What did I save about X?"* actually works

**Goal:** User asks in any session "What did I save about Q1 payroll?" and gets back a synthesized answer pulled from their core saves with provenance.

### Architecture

**New pipeline:** `backend/pipelines/core_recall_pipeline.py`

```python
def run_core_recall_pipeline(question, llm, user_id, top_k=5) -> dict:
    # 1. Embed the question
    # 2. Embed each core_save.title + content (CACHED in core_saves.embedding_json)
    # 3. Cosine similarity against embeddings
    # 4. Return top-k saves
    # 5. Synthesize an answer that cites which saves it used
    # Returns: { answer, sources: [{save_id, topic, title, snippet}], pipeline: "core_recall" }
```

**Embedding cache:** Add `embedding_json` column to `core_saves` at 4d start. On save creation OR migration, generate embedding once, store as JSON array. Recall reads from cache — no per-query embedding cost beyond the question.

### Router updates

The query router learns a fourth route: `core_recall`.

**Detection signals** (from `query_router.py`):
- Phrases: "what did I save", "find my saved", "what's in my core", "my saved data", "recall my", "show me my notes about"
- Or: question mentions a specific past time period ("Q1 payroll from last year") that almost certainly came from saved data, not the demo DB

The router can also pick `core_recall + sql` or `core_recall + rag` as combined routes when the question spans both.

### Frontend

Recall answers render distinctly from regular chat answers:

- Different background tint (mauve/lavender to signal "from your core")
- "From your core data" subtitle
- Each citation links to the original save → click to open the modal from 4c
- Shows topic context: *"Found in your 'Q1 Payroll' topic, saved 2 weeks ago"*

### Demo flow

1. Upload `apple_10k_2024.pdf` in Session A
2. Ask in Session A: *"What were Apple's total net sales?"* → get answer, click 💾
3. In 4c, move that save to a new topic "Apple FY24"
4. **Open Session B** (totally new conversation, no upload, different chat thread)
5. Ask: *"What did I save about Apple revenue?"*
6. → Recall pipeline fires, returns the saved answer with "Found in your 'Apple FY24' topic" subtitle

**This is the "mini-ChatGPT for accountants" moment.** When this works, the project's vision is real, not aspirational.

**Tests:**
- Recall finds saves by content even when question phrasing differs ("net sales" ↔ "revenue")
- Recall filters by user_id — User A's saves never appear in User B's recall (verified in 4f when auth lands)
- Recall handles "I haven't saved anything yet" gracefully
- Recall handles saves that were later archived (excluded from results)

---

## Phase 4e — Topic-Based Session Sidebar

**Estimated time:** 1 session
**User-visible changes:** Sidebar reorganization

**Goal:** Sessions group under topics, not chronologically. Polish.

**Schema addition:**
```sql
ALTER TABLE sessions ADD COLUMN topic_id TEXT REFERENCES core_topics(topic_id);
```

**Behavior:**
- When user creates a new session, they can optionally pick a topic OR leave "Untagged"
- Existing session rename UI extends to also let user set/change topic
- Sidebar shows:

```
[+ New Chat]

▼ P&L (4 sessions)
    Q1 review · 2h ago
    Margin breakdown · yesterday
    ...

▼ Payroll (2 sessions)
    ...

▼ Untagged (3 sessions)
    ...

MY CORE DATA
    [as before from 4c]
```

**Cross-references:** Hover over a session, see "links" badge if it has saves. Click the badge → filter "My Core Data" to only that session's saves.

**Why last:** Pure UX. The features must exist first. Doing this earlier would force re-work when 4d's recall lands.

**Demoable?** Yes — the sidebar now reads as a *workspace*, not a chat log.

---

## Phase 4f — Real Auth (OPTIONAL — only if going beyond solo)

**Estimated time:** 1-2 sessions
**User-visible changes:** Login page; everything else hidden behind auth

**Skip if:** You're still solo at end of Phase 4e. The hard-coded default user is fine.

**Do if:** You want to give the link to mentor + 1-2 friends for real testing.

**Deliverables:**
- Login page with email + password
- Signup gated by a static signup code (or mentor-issued invitation token) — no public signup
- JWT tokens stored in `localStorage` (not httpOnly cookies — that's Phase 5)
- All endpoints require auth header `Authorization: Bearer <token>`
- User can log out
- Password hashed with bcrypt
- Sessions table gets `user_id` column; all queries filter by current user
- Core data already has `user_id` from 4a → just enforce it

**What NOT to build here:** email verification, password reset, OAuth, rate limiting, audit logging, encryption at rest. Those are Phase 5.

**Demoable?** Yes — open two browsers, log in as different users, confirm isolation.

---

## Phase 4 — Summary Table

| Sub-phase | Sessions | Adds | Demoable |
|-----------|----------|------|----------|
| **Warm-up** | 0.25 | Router PDF-awareness | Yes — phrasing-independent PDF queries |
| **4a** | 1 | DB schema + default user | No (foundation) |
| **4b** | 1-2 | 💾 button per message + upload | Yes |
| **4c** | 1 | Topic CRUD + core data sidebar | Yes |
| **4d** | 2 | Natural-language recall pipeline | **FLAGSHIP** |
| **4e** | 1 | Topic-grouped session sidebar | Yes — polished product |
| **4f** | 1-2 | Real auth (if needed) | Yes — multi-user proof |

**Total without 4f:** 6.25 sessions ≈ 3-4 weeks at 2 sessions/week.
**Total with 4f:** 7.25-8.25 sessions ≈ 4-5 weeks.

---

## Phase 5 — Production Hardening (FUTURE, NOT NOW)

Out of scope for this plan. Captured here so we don't drift.

When you decide to go public:

- Real auth with email verification + password reset
- bcrypt cost factor tuned, salts validated
- httpOnly cookies instead of localStorage tokens
- Rate limiting on login + signup + save endpoints
- Audit log table for all data mutations
- Encryption at rest (SQLCipher for SQLite, or move to Postgres + column-level)
- GDPR-ish data export endpoint
- Data deletion (right to be forgotten)
- HTTPS-only with proper certs
- CORS lockdown (no `*`)
- Input sanitization audit
- Secrets management (env vars + Doppler/AWS Secrets Manager)
- Hosting: cloud server with proper backups
- Monitoring + uptime alerts
- Terms of service + privacy policy

That's 8-15 sessions of work, depending on scope. Phase 5 is a real project on its own.

---

## What I'll need from you at the start of each phase

**4a:** Just a green light. I read the v4 handoff to get back into the codebase.

**4b:** Decision on what a "save" actually snapshots for uploads (full CSV data? Just summary? Just metadata?).

**4c:** Decision on default topic name ("Unsorted" vs "Inbox" vs "Recent saves").

**4d:** Decision on whether recall results show the full saved content inline or just a link to open the original.

**4e:** Decision on which topic a session belongs to (optional? Required at creation? Auto-suggested?).

**4f:** Skip or do — depends on whether you've shared with anyone yet.

---

## Open questions (parking lot — answer before each phase)

- [ ] Should saved messages with charts include the chart spec, so recall can re-render the chart?
- [ ] Should saved uploads expire? (E.g., a 1-year-old saved CSV summary may not be useful anymore.)
- [ ] When user deletes a session, do saved items from that session also get archived? Or do they outlive the session?
- [ ] Topics: can a save belong to multiple topics, or just one?

These don't block 4a. We'll lock them as they become relevant.

---

## Risk register

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Embedding all saves for recall hits cost limits | Low | Low | Cache embeddings on save creation; ~$0.00002 per save |
| Schema migration breaks existing sessions | Low | High | Migration script is idempotent and tested before running |
| User uploads a 50MB PDF, save snapshot bloats core_saves | Medium | Medium | For uploads, save only summary + reference, not raw content |
| Phase 4d recall returns wrong results due to lexical mismatch | Medium | Medium | Use embedding similarity, not keyword match |
| User wants to share saves across users (collaboration) | Low | Low | Phase 5+ feature — design now so user_id column supports many-to-many later |
| Phase 4f auth complexity drags timeline | Medium | Medium | Make 4f optional. Solo Phase 4 is complete without it. |

---

## Tracking

**Created:** before Phase 4 starts
**To live at:** `app2/docs/app2_phase4_plan.md`
**Update whenever:** decisions get refined OR a phase ships (mark "done" + link to handoff)
