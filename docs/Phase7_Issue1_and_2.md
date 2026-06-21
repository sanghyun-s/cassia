# CASSIA — Phase 7 · Issue 1 & 2

**Export / Download + Long-form Readability**
Pre-deployment hardening pass · frontend-only · completed 2026-06-21

---

## Summary

Two of the four pre-deployment hardening issues are complete. Both were done
entirely in the frontend (`backend/static/index.html`) with **no changes to
authentication, sessions, Core, uploads, SQL, RAG, BOTH, routing, prompts, the
database, or the Pydantic models.** Every change is additive, idempotent,
uniqueness-checked, and individually reversible from a `.bak` backup.

| Issue | Status | Risk | Files touched |
|-------|--------|------|---------------|
| 1 — Export / download | **Done** | Low | `backend/static/index.html` |
| 2 — Long-form readability | **Done** | Low | `backend/static/index.html` |
| 3 — Sensitive-data MVP | Pending (tomorrow) | Low | frontend + README |
| 4 — Permissions (docs) | Pending (tomorrow) | None | README |

---

## Issue 1 — Export / download

Three export paths, all client-side (`Blob` + `a[download]`), no backend
endpoint required.

- **Session export** — a floating **⤓ Export** button (visible in chat, hidden
  on the auth screen) offers *Session → Markdown* and *Session → HTML (print /
  PDF)*. It **re-fetches** the session from `GET /sessions/{activeSessionId}`
  and serializes the full persisted transcript — so it captures everything that
  happened, not just what's scrolled on screen. Each turn includes the answer,
  the **Generated SQL**, the **result table**, and **citations** (page numbers).
- **Result-table CSV** — a **⤓ CSV** button under every SQL result table,
  generated from the in-memory columns/rows.
- **Core-save export** — **⤓ MD / ⤓ HTML** buttons on each saved card.
- **HTML exports** are print-friendly (basic print CSS), so the user can
  Cmd-P → Save as PDF.

**Design note:** the frontend has no in-memory transcript array (messages are
appended straight to the DOM), so session export re-fetches from the backend
rather than scraping the DOM — authoritative and resilient.

**Sentinel:** `CASSIA_EXPORT_MVP` · **Applier:** `apply_export_mvp.py` ·
**Backup:** `index.html.pre-export-<ts>.bak`

**Acceptance criteria — met:** final answer exportable in readable form ✓ ·
Core item exportable ✓ · SQL table → CSV ✓ · citations + generated SQL included
✓ · existing chat / save / recall / SQL / RAG / upload flows unaffected ✓.

---

## Issue 2 — Long-form readability

**Part A — paragraph breaks (CSS only).** Added `white-space:pre-wrap` to the
`.msg-text` rule. The model was already emitting `\n\n` paragraph breaks; the
browser was collapsing them. One property restores memo / letter / list
structure in chat. (`.core-save-content` and `.sql-query-text` already had
pre-wrap.)

**Polish — bold rendering + per-answer export.**

- `**bold**` now renders as real **bold** in chat answers and Core save
  previews. It is applied to already-HTML-escaped text (safe), and is
  **display-only** — the stored text and the Markdown export keep their `**`,
  so Markdown still renders bold in any viewer.
- **Per-answer export** — **⤓ MD / ⤓ HTML** buttons appear under each
  substantial answer (>160 characters). They export *just that answer* (with
  its SQL, table, and citations), bold-clean in both formats. **No Core save is
  required to export a single answer** — Core remains for things you want to
  keep and recall.
- Short factual answers and user messages are left untouched.

**Sentinel:** `CASSIA_EXPORT_POLISH` · **Applier:** `apply_export_polish.py` ·
**Backup:** `index.html.pre-polish-<ts>.bak`
(Part A applier: `apply_readability_prewrap.py` · backup
`index.html.pre-readability-<ts>.bak`)

**Acceptance criteria — met:** memos/letters no longer one dense paragraph ✓ ·
readable sections ✓ · client email copy-ready ✓ · short answers not
over-formatted ✓ · Core item preserves formatting ✓ · export preserves
formatting ✓.

---

## Verification performed

- Session export (MD + print-HTML), table CSV, Core MD/HTML, and per-answer
  MD/HTML all produced clean, well-formed files; tables, generated SQL, and
  citations preserved.
- Bold renders correctly in chat and in Core previews; per-answer HTML export
  shows real `<strong>`, MD keeps `**`.
- Regression spot-check: normal chat, save to Core, Core recall, RAG with
  citations, CSV/Excel upload + query, topic move — all unchanged.
- The four demo simulations were **not modified** (no backend/prompt/routing
  change was made).

---

## Rollback

Each patch left a timestamped backup of `index.html`. To revert any single
patch:

```
cp "backend/static/index.html.pre-polish-<ts>.bak"      "backend/static/index.html"
cp "backend/static/index.html.pre-readability-<ts>.bak" "backend/static/index.html"
cp "backend/static/index.html.pre-export-<ts>.bak"      "backend/static/index.html"
```

(`.bak` files are gitignored.) The appliers are also idempotent — re-running a
patch that's already applied is a safe no-op.

---

## Known trivial cosmetics (open · optional)

1. Single-asterisk `*italic*` (e.g. a trailing `*Source: …*`) still shows
   literal asterisks — the renderer handles `**bold**` only. Low value, slightly
   risky to extend (single `*` appears in other contexts); left as-is.
2. The Core-*save* export H1 can inherit a stray line break from the stored save
   title. Heading only; body is fine. A one-line title trim would clean it.

Neither blocks deployment.

---

## Pending — tomorrow, before the deployment session

- **Issue 3 — Sensitive-data MVP** (frontend + README, low risk, no encryption
  claim): detect dashed SSN (`###-##-####`) / EIN (`##-#######`) in assistant
  output, warn on detection, optional masking (`***-**-1234`, `**-***1234`) in
  display and export, a static demo warning near upload, and an honest README
  security boundary.
- **Issue 4 — Permissions (docs only):** document the current model as
  *single-user workspace isolation* (per-user auth, sessions, saves, uploads;
  vector filtering by `user_id` + `session_id`). RBAC → Phase 7.
- Optional cleanup of the two cosmetics above.
- Final regression including the four demo simulations; remove debug logs if safe.

---

## Phase 7 — deferred (post-deployment roadmap)

- DOCX / XLSX-workbook / ZIP packet export; server-side (backend) export
  endpoints; bold rendering inside the *session/Core* HTML exports.
- Persistent "sensitive" lock (DB flag + confirm-on-open) and encryption at
  rest across files, extracted text, vector chunks, saves, and exports.
- Organization / team RBAC: workspaces, roles (owner/admin/member/viewer),
  sharing, permission checks across endpoints, audit log.
- Full Markdown rendering in the app (headings, italics, lists).

---

## Files produced this pass

| File | Purpose |
|------|---------|
| `apply_export_mvp.py` | Issue 1 applier (frontend export) |
| `apply_readability_prewrap.py` | Issue 2 Part A applier (pre-wrap) |
| `apply_export_polish.py` | Issue 2 polish applier (bold + per-answer export) |
| `locate_frontend_export.py`, `locate_frontend_export_detail.py` | read-only locators |
| `index.html.pre-export-<ts>.bak` / `.pre-readability-<ts>.bak` / `.pre-polish-<ts>.bak` | rollback backups (gitignored) |
