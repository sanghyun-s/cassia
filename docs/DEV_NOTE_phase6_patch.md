# CASSIA — Dev Note: Phase 6 Patch + Demo Prep

**Date:** 2026-06-08 (evening session)
**Continues from:** `HANDOFF_README_v4.md`, `DEV_NOTE_through_Phase5.md`
**Status:** Stabilization slate complete (6 patches). Core cleaned. Demo upload
fixtures generated and organized. **Sims not yet run** — that is the next session.

---

## Context

The prior session applied five stabilization patches from the Phase 6 six-simulation
findings (P3, P1, P2, P4, P1b) and produced the pre-deploy plan. This session:

1. Shipped the remaining guard (**P2b**).
2. Verified the stabilization slate in a live smoke test.
3. Discovered and remediated a **polluted Core**.
4. Built **Core-hygiene tooling**.
5. Generated the **7 demo upload fixtures** keyed to real DB data.
6. Organized the repo (`applied patch/`, `demo_uploads/`) for a checkpoint push.

---

## 1. P2b — SQL-only route SQL-unusable guard (shipped + verified)

**Problem:** the existing P2 guard only covered the `BOTH` route. The Phase 6 Sim 4
(Image 4) Oracle cross-table query was **SQL-routed**, so a raw SQLite error
(`no such column` / UNION mismatch) leaked straight to the user.

**Fix:** mirror the P2 detection into the `elif route == "sql":` branch of `/chat`
in `backend/main.py` (was lines 579–580). The SQL branch now gets its own
self-contained `_p2b_unusable_patterns` tuple (same 11 patterns as P2 — the P2 copy
is defined inside the `both` block and is out of scope here) plus a clean fallback:

> "I couldn't form a reliable data query. Could you specify which table, amount, or
> comparison target you'd like me to look at?"

- **Applier:** `apply_p2b_sql_guard.py` (backup + idempotent + uniqueness-checked;
  recompiles `main.py` after writing and auto-restores the backup on any compile error).
- **Backup:** `main.py.pre-p2b-<timestamp>.bak`
- **Verification (both paths):**
  - Valid SQL ("Find Oracle invoices in our AP") → real answer (INV-038, $15K, Overdue);
    guard correctly stays out of the way (**no false-fire**).
  - Failing SQL ("combined AP + AR list … ranked by amount") → UNION mismatch caught,
    clean fallback returned, **no raw error text leaked**.

**Stabilization slate is now closed:** P3, P1, P2, P2b, P4, P1b (+ the earlier NaN-in-JSON fix).

---

## 2. Pre-sim smoke test

| Check | Prompt | Result |
|---|---|---|
| SQL + chart | "Show overdue AR by customer as a bar chart" | **PASS** — single-measure bar on first render (P1/P1b confirmed live) |
| RAG | "What does the IRS say about late payroll deposits?" | **PASS** — Pub 15 penalty tiers (2/5/10/15%), page-36 citations |
| Core Recall | "Recall the saved note about payroll tax exposure" | Surfaced the **Core-pollution** problem (see §3) |

Note for Sim 1: the text-to-SQL narrowed plain "overdue" to **90+ days only**. Phrase
that prompt as **"all overdue AR"** during the sim.

---

## 3. Core pollution — found + remediated

The recall test returned saved *error strings* as the top matches (relevance 0.52 / 0.44),
ahead of real findings. A full Core inventory (`dump_for_sims.py`) showed **47 saves
total, 46 active**, in three bad buckets:

1. **Junk stubs/errors** — "I couldn't find that…", "I have related saves but…",
   "there is no uploaded data…", "query execution failed…", plus Apple-10K and "pizza" tests.
2. **Old ad-hoc test saves** — duplicate "net income $101,491" and "revenue by service
   line" saves under topics *Chart fix test*, *Net Income*, *Q1 Tax Work*.
3. **A prior "Simulations v1" run** (topic `top_f3a7f2e9d0d3`) — AR/vendor/Oracle/payroll
   saves that are near-duplicates of what the new Demo Sims will produce, and would
   directly compete in Sim 4's recall.

**Remediation:** archived all 46 active saves with `archive_core_saves.py` (clean slate
so Sim 4 recalls only the fresh Sim 1–3 saves). Backup: `coreckoner.db.pre-archive-<ts>.bak`.
`core_health.py` now reports `0 active`.

**Assumption to confirm in next session:** archiving (setting `archived_at`) excludes a
save from recall. Verify with a recall prompt after restart; if junk still surfaces, the
recall query needs an `archived_at IS NULL` filter.

**Root cause for the backlog:** CASSIA lets any assistant message be saved, including
errors/stubs, and My Core shows only auto-titles with no quality flag — so pollution
accumulates invisibly. See post-deploy backlog.

---

## 4. New tooling (in `applied patch/`)

| Script | Purpose | Safety |
|---|---|---|
| `locate_p2b.py` | Read-only locator: dumps the `/chat` route-dispatch + P2 guard region | read-only |
| `apply_p2b_sql_guard.py` | Applies the P2b SQL-only guard | backup + idempotent + uniqueness + compile-check/restore |
| `dump_for_sims.py` | Read-only inventory of all DBs (accounting data for fixture alignment + Core inventory) | opens every DB `mode=ro` |
| `archive_core_saves.py` | Bulk-archives all active Core saves (clean slate) | backup + idempotent + confirm prompt; reversible |
| `core_health.py` | Read-only audit: flags junk/stub/error saves and duplicates among active saves | read-only |

All appliers follow the project pattern: locate → backup → idempotent + uniqueness-checked
edit → verify (compile) → reversible via `.bak`.

---

## 5. Data layout discovered

`outputs/accounting.db` — the demo DB — has 7 tables:

| Table | Rows | Notes |
|---|---|---|
| accounts_payable | 45 | Oracle = INV-038, $15,000, Overdue, due 2026-03-03 |
| accounts_receivable | 14 | overdue 90+: Titan $9,400 (disputed), Union Pacific $2,800 (bad-debt likely), KLM $4,800 (non-responsive) |
| balance_sheet | 28 | |
| chart_of_accounts | 59 | revenue 4000–4040; payroll 5000/5010/5020, accrued 2020 |
| general_ledger | 139 | semi-monthly payroll: gross ~$86K, employer FICA $6,579, fed withheld $8,653 |
| profit_loss | 36 | monthly columns Jan–Apr 2026 |
| revenue | 53 | 5 service lines: Accounting Services, Tax Preparation, Audit Services, Bookkeeping, Consulting |

`outputs/sessions/*.db` hold **uploaded copies** of these tables (e.g. `accounts_receivable`,
`general_ledger`, `revenue_2`) — this is why the smoke-test SQL queried
`user_data.accounts_receivable`: that session had AR uploaded into the per-session namespace.

---

## 6. Demo upload fixtures (in `demo_uploads/`)

7 files generated this session + the pre-existing Oracle email, keyed to real DB entities
so the cross-reference prompts land. See `demo_uploads/README.md` for the per-sim mapping.

Internal-consistency notes worth verifying on camera:
- **CP220 penalty = $3,707.87**, derived from the `payroll_register_q1.csv` late deposits
  (8 / 18 / 3 days late → 5% / 10% / 2% tiers). Sim 3 P4's BOTH synthesis should land near $3,708.
- **`credit_memo_log.csv`** has 5 "Issued – Not Applied" credits against overdue invoices
  (Quest, Titan, Union Pacific, Liberty, KLM) — the P5 cross-reference targets.

These are **upload fixtures, not app-loaded data** — fed through the UI during sims; the
app never reads them on its own. Kept out of `data/`, `sql/`, and load paths on purpose.

---

## 7. Repo organization

- `applied patch/` — all applier + utility scripts (NaN fix, P1–P4, P2b, locators, Core hygiene).
- `demo_uploads/` — Sim 1–4 fixtures, grouped by sim subfolder.
- `.gitignore` hardened: `*.bak`, `__pycache__/`, `*.pyc`, `.DS_Store`, `venv/`, `.env`,
  `outputs/coreckoner.db`, `outputs/sessions/`, `outputs/chroma_db/`.
- Checkpoint commit captures stabilization + prep (sims/screenshots/journal are a later commit).

---

## Current state / deploy readiness

- ✅ Stabilization slate closed (6 patches, verified)
- ✅ Core clean (0 active saves)
- ✅ Demo upload fixtures generated + organized
- ✅ Repo organized + checkpoint push
- ⬜ Demo Sims 1–4 not yet run
- ⬜ Final deploy (internal target Wednesday 2026-06-10)

---

## Outstanding / next session

1. **Run Demo Sims 1–4 in order** (Sim 4 depends on Sims 1–3 saves). Capture screenshots.
   Use `CASSIA_FINAL_SIMULATION_SET_v4.md` for the per-prompt sequences.
2. Verify the archive→recall assumption (§3) right after the first restart.
3. Optional pre-deploy tidy: remove the two `[P1 DEBUG]` prints in `chart_builder.py`
   (console-only; harmless if left).
4. Selective chat cleanup; final deploy.
5. Journal / portfolio write-up draws from the Sim 1–4 evidence.

---

## Post-deploy backlog (carried + new)

- **Save-button junk guard (NEW):** stop letting error/stub messages be saved to Core —
  soft warning ("this looks like an error — save anyway?"), reuse the P2 pattern list. This
  is the root-cause fix for the pollution found this session.
- SQL schema-awareness (real fix for cross-table UNION issues; P2/P2b only mask them).
- Multi-statement SQL prevention.
- Core Recall synthesis tuning (the "I have related saves but…" false-fire).
- Chart-filter duplication: consolidate backend P1 + frontend P1b into one source.
- Remove `[P1 DEBUG]` prints if not done pre-deploy.
- Confirm recall excludes archived saves (else add `archived_at IS NULL` filter).

---

## Gotchas learned this session

- **zsh + heredocs** — avoid; use file-based scripts or `printf`/append.
- **Placeholder angle brackets** — `<path>` in instructions means "fill in"; do not type
  the `< >` (they are shell redirection and error out).
- **Repo lives in iCloud Drive** — if git ever behaves oddly, iCloud sync of `.git` is a
  common culprit; pausing sync during git ops avoids it.
- **Never commit** `.env` (OpenAI key + invite code) or `outputs/coreckoner.db` (password
  hashes + session tokens).
- **Data exists in two places** — the demo DB (`outputs/accounting.db`) and per-session
  upload DBs (`outputs/sessions/*.db`); the `user_data.*` SQL namespace points at the latter.
