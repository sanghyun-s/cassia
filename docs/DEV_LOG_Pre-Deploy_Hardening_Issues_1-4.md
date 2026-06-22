# CASSIA — Pre-Deployment Hardening Log (Issues 1–4)

**A two-day development log · 2026-06-21 → 2026-06-22**
Prepared for mentor review · CASSIA (App 2) v2.12.1

---

## Executive summary

The deployment date slipped by a few days. Rather than expand scope, I used the
window for a **pre-deployment hardening / follow-up-readiness pass** driven by
practical feedback from an experienced business operator ("A"). A's question was
not "does it look impressive" but "could a real business user safely use this
with client files and follow-up work."

Four issues were addressed over two days:

1. **Export / download** — get work out of the chat (must-have).
2. **Long-form readability** — drafts read like memos, not one dense block (must-have).
3. **Sensitive-data MVP** — detect/warn/mask SSN & EIN (should-have).
4. **Permissions / security model** — document the boundary honestly (docs).

**Result:** CASSIA is a deployable, portfolio-grade, **single-user** accounting
support workspace with readable long-form output, four export paths, optional
sensitive-identifier masking, and an honest, well-bounded security story.
Enterprise-grade items (encrypted document export, organization RBAC, MFA, audit
log) were **deliberately scoped to Phase 7** — not skipped, and explicitly *not*
shipped as half-measures, because a partial implementation would create false
confidence.

Every change was surgical, additive, reversible, and — except where noted —
**frontend-only**. No change was made to authentication, sessions, Core,
uploads, SQL, RAG, BOTH, routing, prompts, the database, or the Pydantic models.
The four demo simulations and all core flows were preserved and re-verified.

---

## Engineering approach (applied to every patch)

- **Backup before edit** — each applier writes a timestamped `.bak` and can be
  reverted with a one-line `cp`.
- **Additive, not rewriting** — new functions and buttons inserted at unique
  anchors; existing render/flow code left in place.
- **Idempotent** — re-running a patch that's already applied is a safe no-op
  (sentinel check); each anchor is uniqueness-checked before replacement.
- **Verified before delivery** — every injected block was syntax-checked
  (`node --check`) in isolation and again in context before it left my hands.
- **Reversible per item** — issues were split across separate patches, so any
  one can be rolled back without disturbing the others.

---

## Day 1 — 2026-06-21 · Follow-up output readiness (Issues 1 & 2)

### Issue 1 — Export / download

The frontend holds no in-memory transcript (messages append straight to the
DOM), so session export **re-fetches** from `GET /sessions/{id}` and serializes
the full *persisted* transcript — authoritative, not a DOM scrape. Delivered:

- **Session export** → Markdown or print-friendly HTML (Cmd-P → PDF), with each
  turn's answer, generated SQL, result table, and citations.
- **Per-answer export** → `⤓ MD` / `⤓ HTML` under each substantial answer, so a
  single memo can be downloaded **without** saving it to Core first.
- **Core-save export** → `⤓ MD` / `⤓ HTML` on each saved card.
- **Result-table CSV** → `⤓ CSV` under every SQL table.

All client-side (`Blob` + `a[download]`). No backend endpoint, no DB change.

### Issue 2 — Long-form readability

- **Root cause:** the model already emitted paragraph breaks; the `.msg-text`
  CSS lacked `white-space:pre-wrap`, so the browser collapsed them. **One CSS
  property** restored memo/letter/list structure in chat.
- **Polish:** `**bold**` now renders as real bold in chat and Core previews
  (display-only; stored text and Markdown export keep `**`). Per-answer exports
  are bold-clean in both formats. Short factual answers are left untouched.

**Committed:** `56f269b` — *"Pre-deploy hardening (Issue 1 & 2): export +
long-form readability."*

---

## Day 2 — 2026-06-22 · Sensitive data + access honesty (Issues 3 & 4)

### Issue 3 — Sensitive-data MVP (frontend, no encryption claim)

- **Detection** — conservative, dashed-pattern only: SSN `###-##-####` and EIN
  `##-#######`. Verified it flags real identifiers but **not** phone numbers or
  plain financial figures.
- **Warning** — an amber chip appears under any answer containing a detected
  pattern (works on new and restored messages, any pipeline).
- **Masking** — one **🔒 Mask SSN/EIN** toggle that masks both the on-screen
  view *and* every export (`***-**-1234`, `**-***6789`, last 4 kept). Export
  masking is applied at a single chokepoint (`_expDownload`), so it covers
  session/per-answer/Core MD+HTML **and** table CSV at once.
- **Demo guardrails** — a one-time reminder when a file is selected, plus a
  standing note in the export menu.

**Deliberate non-decision:** A suggested locking exported documents with a
4-digit code (SSN/EIN last digits). I did **not** build this, because (a) a code
that doesn't actually encrypt the file's bytes is cosmetic, and (b) four digits
is low-entropy and SSN/EIN digits are identifiers *about the protected party* —
using them as a secret is unsafe. The in-scope answer is masking (remove the PII
from the export); the correct Phase 7 answer is a **password-protected PDF** with
a real passphrase.

### Issue 4 — Permissions / security model (documentation)

Added a **"Security & data handling"** section to the README that states the
current model honestly as **single-user workspace isolation** (invite-only
signup; per-user sessions, saves, uploads; retrieval filtered by `user_id` +
`session_id`), and explicitly lists what is **not** implemented:

- No encryption at rest (masking is display/export only, never stored data).
- No organization / team roles or permissions (RBAC).
- No persistent "sensitive" lock, audit log, or MFA / device control.

A's deeper authentication concern — a personal login becoming a shared company
credential — is answered in principle: **don't share one login.** The correct
model is per-person accounts under an organization, with roles
(owner/admin/member/viewer), plus MFA and new-device/IP verification. All of
that is named as Phase 7. The README also refreshed the feature list, Status
table, and Roadmap to reflect this pass.

**Committed:** `7edead4` — *"Sensitive-data MVP (Issue 3) + security-model docs
(Issue 4)"*, followed by a docs-only commit for the README feature refresh.

---

## The scope decision (the part worth aligning on)

The honest framing of what's *not* in this release is not "we ran out of time."
It is:

> **Enterprise-grade security — encrypted exports, RBAC, MFA, audit logs — is
> correctly scoped as Phase 7 production hardening, because a partial version
> would be misleading and unsafe.**

For real client PII, the realistic deployment posture is also more natural than
"the app does everything": CASSIA exports review material in portable formats and
can mask sensitive identifiers; the organization then stores and shares those
outputs under its own security policy. That division of responsibility is how
most real back-office work actually operates.

---

## Verification (six-point close-out)

1. Exported files open correctly (MD / HTML / CSV). ✔
2. MD/HTML formatting is intact (tables, SQL, citations, paragraph breaks). ✔
3. Long memos wrap and read cleanly. ✔
4. SSN/EIN masking is reflected in exports when the toggle is on. ✔
5. **The four demo simulations still pass** (regression complete). ✔
6. README states the current security scope without exaggeration. ✔

---

## Deferred to Phase 7 (post-deployment hardening)

- Password-protected / encrypted document export (PDF or AES-zip, real passphrase).
- Encryption at rest across files, extracted text, vector chunks, saves, exports.
- Organization / team RBAC: workspaces, roles, sharing, permission checks, audit log.
- MFA + new-device / new-IP verification; SSO for company environments.
- Persistent per-session / per-save "sensitive" lock.
- DOCX / XLSX-workbook / ZIP packet export; full in-app Markdown rendering.

---

## Commits & artifacts

| Item | Reference |
|------|-----------|
| Issues 1 & 2 | commit `56f269b` |
| Issues 3 & 4 (sensitive + security docs) | commit `7edead4` |
| README feature refresh | docs-only commit (latest on `main`) |
| Appliers + locators | `applied patch/` (tooling; backups gitignored) |
| Day-1 detail companion | `docs/Phase7_Issue1_and_2.md` |

**Known trivial cosmetics (open, optional, non-blocking):** single-asterisk
`*italic*` shows literally (renderer handles `**bold**` only); the HTML session
export prints "Result (1 rows)" (plural not mirrored from the MD path); the
Core-save export H1 can inherit a stray newline from the stored title.

---

## Current state

CASSIA v2 is **deploy-ready**: a follow-up-ready, single-user accounting support
workspace whose answers are readable, exportable, and reusable, with honest
handling of sensitive identifiers and a clearly bounded security model. The
hardening pass strengthened exactly the part of the pitch that matters — moving
the user from scattered inputs to follow-up-ready output — without drifting into
enterprise-SaaS scope.
