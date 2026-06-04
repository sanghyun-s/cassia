# CoReckoner — Phase 5a Dev Note (Pass 1 close-out)

> **Status:** Phase 5a installed, tested, committed. Auth foundation works:
> signup / login / logout / `/auth/me`. Data temporarily un-claimed back to
> the `default` user so Phase 4 UI continues to work. Pass 2 will scope
> existing endpoints to `current_user` and re-run the claim properly.

This note exists so when Pass 2 begins, the constraints, the gotchas, and the
half-state are all clearly captured — no re-litigating Pass 1 decisions.

---

## What Pass 1 shipped

### Four new files (self-contained — no modifications to Phase 4 code)
- `backend/auth.py` — bcrypt hashing (via passlib), session token generation,
  `get_current_user` FastAPI dependency reading HttpOnly cookie, set/clear
  cookie helpers
- `backend/db/auth_migrations.py` — idempotent ALTERs for new columns
  (`password_hash`, `username`, `invite_code_used`, `is_admin` on `users`;
  `user_id` on `sessions` and `uploads`); new `auth_sessions` table;
  case-insensitive UNIQUE indexes for email and username
- `backend/db/auth_queries.py` — user CRUD, identifier lookup
  (email-or-username, case-insensitive), `claim_orphaned_data()` for first-
  signup migration, auth-session CRUD with sliding renewal
- `backend/routers/auth_router.py` — four endpoints with full validation

### Three additive edits to `backend/main.py`
- Two imports (`auth_router`, `auth_migrations`)
- One try-block in `lifespan()` calling `auth_migrate()`
- One `app.include_router(auth_router)` call

That is the entire surface area of touched existing code.

### `.env` additions
- `SIGNUP_INVITE_CODE=cassia-mvp-2026`
- `SESSION_LIFETIME_DAYS=30`
- `COOKIE_SECURE=false` (toggle to `true` in any future prod)

### Pinned dependency
- `bcrypt>=4.0.1,<5.0.0` — bcrypt 5.x removed `__about__.__version__` which
  passlib 1.7.4 reads. The "trapped error reading bcrypt version" warning
  on startup is harmless and will be silenced in a follow-up commit.

---

## Verified during install

Every endpoint behaves as designed:

| Test | Expected | Result |
|------|----------|--------|
| `/auth/me` no cookie | 401 | ✅ |
| `/auth/signup` first-real-user | 200, `claimed_summary` populated | ✅ — 11 sessions, 3 uploads, 12 saves, 3 topics claimed |
| `/auth/me` with cookie | 200 + user info | ✅ |
| `/auth/logout` | 200, cookie cleared (`Max-Age=0`) | ✅ |
| `/auth/me` after logout | 401 | ✅ |
| `/auth/login` mixed-case username | 200, case-insensitive match | ✅ — `SangHyun` matched `sanghyun` |
| `/auth/login` by email | 200 | ✅ |
| Wrong password | 401, same generic message | ✅ — email-enumeration defense intact |
| Wrong invite code | 403 | ✅ |

The cookie produced by signup/login is correctly shaped:
`HttpOnly; Max-Age=2592000; Path=/; SameSite=lax` (no `Secure` for localhost).

---

## The half-state issue (and why we un-claimed)

### What we hit
After signup successfully ran `claim_orphaned_data` and moved 11 sessions
plus 3 topics + 12 saves to the new user, the Phase 4 browser UI showed
only **5 sessions in Unsorted** and **0 topics**. The other 6 sessions and
all 3 topics had effectively become invisible.

### Why it happened
Phase 5a intentionally did **not** scope existing endpoints to `current_user`.
That's Pass 2's job. So:
- `/sessions` still returns all sessions regardless of owner
- But `/core/topics` and `/core/saves/list` ARE user-scoped (since Phase 4c),
  using the hard-coded `CURRENT_USER_ID = 'default'`

When `claim_orphaned_data` moved topics from `default` to `usr_bb2f7e5a58a7`,
the browser still queried `default`'s topics and saves → returned empty list.
The sidebar's grouping logic then said "I have sessions with `topic_id` X,
but no topic X exists in my topics list, so skip the grouping" — and the
sessions still in topics became invisible.

### Why this isn't a bug in Pass 1
This half-state is the **expected consequence** of multi-pass migration. Pass 1
adds the schema, the auth endpoints, and the migration logic. Pass 2 wires
the user identity through every endpoint so the data becomes visible again.

### Why we chose to un-claim
Three reasons:
1. Preserves a fully-working Phase 4 demo environment in the meantime
2. Validates that "un-claiming" works as a true reversal (useful for any
   future production migration where a rollback might be needed)
3. The user account (`usr_bb2f7e5a58a7`) is preserved with password intact
   — only data ownership flipped back

### How we un-claimed
Direct SQL on `coreckoner.db`:
```sql
UPDATE sessions    SET user_id = NULL          WHERE user_id = 'usr_bb2f7e5a58a7';
UPDATE uploads     SET user_id = NULL          WHERE user_id = 'usr_bb2f7e5a58a7';
UPDATE core_topics SET user_id = 'default'     WHERE user_id = 'usr_bb2f7e5a58a7';
UPDATE core_saves  SET user_id = 'default'     WHERE user_id = 'usr_bb2f7e5a58a7';
```

A safety backup of `coreckoner.db` was made at
`outputs/coreckoner.db.pre-unclaim.bak` before running the UPDATEs.

After un-claiming, the browser UI shows all 11 sessions, all 3 topics, all
12 saves — Phase 4 baseline state.

---

## What this means for Pass 2

Pass 2 needs to do three things in coordination:

1. **Scope every existing endpoint to `current_user`.**
   - Replace `CURRENT_USER_ID` global with `current_user: User = Depends(get_current_user)`
   - `get_all_sessions()`, `create_session()`, etc. need `user_id` params
   - All ~16 endpoints in `main.py` get the dependency
   - 401 returned by the dependency for unauthenticated requests

2. **Re-run the data claim at the right time.**
   - The first real signup still triggers `claim_orphaned_data`
   - But now the moved data will be visible because endpoints are user-scoped
   - User who is currently logged in (`usr_bb2f7e5a58a7`) is already in the
     DB — Pass 2 needs to handle "user exists but no data is owned" case
     gracefully (probably: provide a one-time admin endpoint or re-trigger
     the claim when this specific user logs in if no data is currently owned)

3. **Don't break the Phase 4 features that ARE already user-scoped.**
   - `/core/topics`, `/core/saves/*` are already `user_id`-aware in their
     queries — they just use the hard-coded `default`. Replacing
     `CURRENT_USER_ID` with `current_user.user_id` is the change.

A possible Pass 2 deliverable structure:
- ONE modified file: `backend/main.py` (the big one — endpoint dependencies)
- ONE modified file: `backend/db/session_store.py` (signature updates for
  `get_all_sessions`, `create_session`, `list_uploads`)
- ONE NEW small file: `backend/db/auth_reclaim.py` containing
  `reclaim_data_for_user(user_id)` — a callable that can be triggered for
  the specific case where a user signed up before endpoint scoping was in
  place

The `reclaim_data_for_user` flow on first login after Pass 2 install:
- If no other real users own any sessions
- AND the current user owns no sessions
- AND there exist NULL-user sessions and `default`-owned topics/saves
- → Run the claim again for this user
- → Show a toast "Welcome back — claimed N sessions, N saves into your account"

This handles the specific recovery path for the `sanghyun` account.

---

## Open items for Pass 2 build

- [ ] Scope `/chat` to `current_user` (the big one — also passes user_id
      into RAG pipeline for ChromaDB filtering in Pass 3)
- [ ] Scope all `/sessions/*` endpoints
- [ ] Scope all `/core/*` endpoints
- [ ] Scope upload endpoints (`/sessions/{id}/uploads`, `/uploads/{id}`)
- [ ] Update `session_store.get_all_sessions()` to take `user_id`
- [ ] Update `session_store.create_session()` to take `user_id`
- [ ] Update `session_store.list_uploads()` to verify session-belongs-to-user
- [ ] Add session-belongs-to-user verification helper used across endpoints
- [ ] Add `auth_reclaim.reclaim_data_for_user()` for the recovery case
- [ ] CORS middleware: `allow_origins=["http://localhost:8002"]` + `allow_credentials=True`
- [ ] Silence the bcrypt "trapped error" warning (one-line passlib log filter)

---

## Open items for Pass 3 (ChromaDB user isolation)

Already designed; preserved here so it doesn't get lost:

- [ ] `pipelines/rag_pipeline.py`: add `user_id` filter to `user_uploads`
      collection query; centralize in `_query_user_uploads()` helper
- [ ] `uploads/document.py`: add `user_id` to vector metadata at upload
- [ ] `routers/upload_router.py`: pass `user_id` from `current_user` to
      `ingest_pdf()`
- [ ] Wipe existing `user_uploads` ChromaDB collection (no `user_id`
      metadata on old vectors); demo PDFs need re-upload after Pass 3

---

## Open items for Pass 4 (frontend)

- [ ] Login screen + signup screen inside `index.html` (single-page-app
      pattern, no new HTML files)
- [ ] Page load: `GET /auth/me` → 401 shows auth, 200 shows chat UI
- [ ] All 23 fetch() calls need `credentials: 'include'`
- [ ] Header logout dropdown (next to "My Core" button)
- [ ] Rename throughout: CoReckoner → CASSIA
  - HTML title, header logo text, welcome screen, assistant message label
- [ ] Welcome subtitle expansion: "Chat-based Accounting System for SQL,
      Search, Insight & Analysis"

---

## Open items for Pass 5 (Stream B polish)

- [ ] `PATCH /core/saves/{save_id}` accepts `also_move_session: bool`
- [ ] My Core save card gets "Also move source session" checkbox

---

## Recovery cheatsheet (if anything goes sideways)

### If Phase 5a auth endpoints break

```bash
APP="/Users/sanghyunseong/Desktop/Z26 Glob NG consult/app 2 - chatbot/app2"
cp "$APP/backend/main.py" "$APP/backend/main.py.broken"
# Restore main.py from the backup if it still exists, or undo the three
# additive edits manually
rm "$APP/backend/auth.py" "$APP/backend/db/auth_migrations.py" \
   "$APP/backend/db/auth_queries.py" "$APP/backend/routers/auth_router.py"
# Restart
lsof -ti:8002 | xargs kill -9 ; python3 backend/main.py
```

The auth_sessions table and new columns will remain in the DB but are unused.
Harmless. If you want a clean DB, restore from the pre-phase5a backup zip.

### If the Phase 4 UI breaks again

The cause is almost certainly data ownership flipping back to `usr_bb2f7e5a58a7`.
Re-run the un-claim SQL:

```bash
APP="/Users/sanghyunseong/Desktop/Z26 Glob NG consult/app 2 - chatbot/app2"
cd "$APP"
cp outputs/coreckoner.db outputs/coreckoner.db.recovery.bak
sqlite3 outputs/coreckoner.db "
  UPDATE sessions    SET user_id = NULL          WHERE user_id = 'usr_bb2f7e5a58a7';
  UPDATE uploads     SET user_id = NULL          WHERE user_id = 'usr_bb2f7e5a58a7';
  UPDATE core_topics SET user_id = 'default'     WHERE user_id = 'usr_bb2f7e5a58a7';
  UPDATE core_saves  SET user_id = 'default'     WHERE user_id = 'usr_bb2f7e5a58a7';
"
```

### Re-initiate prompt for Pass 2 next session

> Picking up CoReckoner Pass 2 of Phase 5 from
> `DEV_NOTE_phase5a.md`. State: Phase 5a installed and committed.
> Auth endpoints work; data was un-claimed back to `default` via SQL so
> Phase 4 UI remains visible.
>
> Pass 2 goals: scope every existing endpoint to `current_user` via the
> `get_current_user` dependency, replacing `CURRENT_USER_ID = 'default'`.
> Also add `auth_reclaim.reclaim_data_for_user()` to recover the
> `usr_bb2f7e5a58a7` account's owned data on first login after Pass 2.
>
> Files I'll paste at the start of Pass 2:
>   - `backend/main.py` (current v2.10.1 + Pass 1 edits, ~978 lines)
>   - `backend/db/session_store.py` (current v2.10.1, ~530 lines)
>   - `backend/routers/upload_router.py` (haven't seen yet, small)
>   - `backend/static/index.html` (if Pass 4 is bundled with Pass 2)
