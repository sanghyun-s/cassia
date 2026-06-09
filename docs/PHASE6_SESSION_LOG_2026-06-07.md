# Phase 6 Session Log — Sims 1+2 Complete, NaN Bug Resolved

**Session date:** 2026-06-07
**Banner version at session start:** v2.12.1 (Phase 5 closed)
**Session outcome:** Sims 1 + 2 completed. One latent bug (NaN in stored
JSON) was discovered, cleaned, and patched. Sims 3-6 deferred to next
session.

---

## Executive summary

Phase 6 testing began with the first two simulations from the v3 test
plan. Sim 1 (AR Collection & Recordkeeping Risk) passed cleanly,
including the critical graceful-fallthrough test where CASSIA correctly
admitted Pub 15's scope didn't cover AR recordkeeping. Sim 2 (Missing
Payroll Tax Deposits, pivoted from the original "late deposits"
framing) exposed two findings — one expected (a BOTH-route synthesis
ceiling) and one unexpected (a latent NaN-in-JSON storage bug that
surfaced only because the GL has sparse numeric columns).

The bug was diagnosed, corrupted records were cleaned, and a five-site
prevention patch was applied with verification. Sims 1 + 2 are journal-
worthy as-is. No new features were added.

---

## Simulations completed

### Sim 1 — AR Collection & Recordkeeping Risk

**Verdict: PASS**

| Prompt | Capability tested | Outcome |
|---|---|---|
| 1. Past-due invoices | SQL | ✅ Returned 10 overdue invoices with notes column |
| 2. Overdue chart | SQL + chart | ✅ Bar chart rendered, descending order |
| 3. IRS recordkeeping | RAG | ✅ **"Not found in docs" badge — graceful fall-through** |
| 4. Collection summary | Synthesis | ✅ Client-facing summary named specific accounts (NorthStar $19,500, Liberty $14,000, Titan $9,400, KLM $4,800, Union Pacific $2,800) |
| 5. Save | save | ✅ Persisted |
| 6. Organize | topic + move | ✅ Topic "AR collection risk" created with the save |

**Critical observation:** Prompt 3 returned the orange "Not found in
docs" badge instead of hallucinating AR-specific guidance from Pub 15
(which is an employment-tax document). This is the most important
reliability test in Phase 6, and CASSIA passed it. The failure-mode
behavior was honest rather than fabricated.

Saved evidence: screenshots of full chart, the "Not found in docs"
badge, and the client summary with specific account names.

### Sim 2 — Missing Payroll Tax Deposits (pivoted)

**Verdict: PARTIAL** — direct retrieval prompts passed; synthesis
prompts failed in an informative way.

| Prompt | Capability tested | Outcome |
|---|---|---|
| 1. GL payroll activity | SQL | ✅ Returned semi-monthly payroll entries, the lonely Jan 15 $8,653 withholding accrual, chart rendered |
| 2. IRS deposit rules | RAG | ✅ Returned Pub 15 deposit schedule content with citations |
| 3. What's wrong/missing | BOTH synthesis | ❌ Router classified BOTH correctly; SQL branch fell through to "No uploaded data in this session" stub |
| 4. Client note draft | Conversational | ❌ Inherited the wrong premise from Prompt 3 — drafted a note saying "no data uploaded" |
| 5. Save | save | ✅ Persisted as "Payroll tax exposure" |
| 6. Organize | topic + move | ✅ Topic "Payroll Compliance" created with 4 saves total |

**Critical observation:** the synthesis failure is the BOTH-route
synthesis ceiling. The router did its job (BOTH classification badge
visible). The SQL pipeline retrieved correctly on Prompt 1. The RAG
pipeline retrieved correctly on Prompt 2. But when Prompts 3 and 4
asked CASSIA to *reason across the two retrievals* rather than fetch
new information, the SQL pipeline's prompt-to-SQL translator failed to
generate a real query and emitted its canned "No uploaded data" stub —
which the final synthesizer then incorporated as if it were data.

The three saves in the Payroll Compliance topic stand as direct
evidence of this ceiling: two are the failed synthesis outputs, one is
the working RAG retrieval.

---

## The NaN bug — discovery to resolution

### How it surfaced

During Sim 2, the UI began returning 500 errors when loading My Core
(`/core/saves/list`), Unsorted saves (`/core/saves/list?topic_id=__none__`),
and the Sim 2 session itself (`/sessions/b7a25b6f-...`). The chat and
queries themselves continued to work. Other sessions and most topics
loaded fine.

### Root cause

Server logs showed:

```
ValueError: Out of range float values are not JSON compliant: nan
```

raised by Starlette's `JSONResponse.render()` (which uses
`allow_nan=False` strictly). Python's default `json.dumps()` uses
`allow_nan=True`, so the writer was permissive and the reader was
strict.

The NaN values came from the SQL pipeline processing GL queries:

```
GL-0001,2026-01-02,3100,Retained Earnings,,125000.00,...   ← empty debit
GL-0021,2026-01-15,5000,Salaries - Professional Staff,68000.00,,...   ← empty credit
```

Double-entry bookkeeping means each row has *either* a debit *or* a
credit, never both. The empty cells became NULL in SQLite, were
converted to `float('nan')` during pandas processing, and got
serialized through to artifact storage.

This bug had existed all along — Sims 1, 3, 4, 5 wouldn't have
surfaced it because AR/revenue/AP queries return dense numeric columns
(no empty cells). **Sim 2's pivot to a GL-anchored scenario was the
first realistic query against a sparse-numeric table.** Realistic data
revealed a latent bug. This is textbook simulation-testing value.

### Cleanup (3 records sanitized)

Affected records (all from the same Sim 2 message
`8d996a17-dcef-4f...`):

| Record | Type | Where NaN was |
|---|---|---|
| `sav_3668d2585acc...` | "Payroll tax exposure" save | `metadata_json.sql_result.rows[*].credit/.debit` |
| `d6f12ed2-b222-4e...` | sql_result artifact | `content_json.rows[*].credit/.debit` |
| `e9d17b4f-fb16-4a...` | chart_spec artifact | `content_json.rows[*].credit/.debit` |

Cleanup script (`cassia_nan_cleanup.py`) backed up the DB to
`outputs/coreckoner.db.pre-nan-cleanup-2026-06-07_204944.bak`, then
replaced NaN values with `null` in place. Sim 2 work was preserved —
the save remained in Payroll Compliance and the chart now renders
correctly (empty bars for empty cells, which is honest representation
of how a double-entry row looks).

### Prevention (5 storage sites patched)

New utility module at `backend/utils/json_safe.py` exposes:

- `sanitize_for_json(obj)` — recursively converts NaN/Inf to None
- `safe_json_dumps(obj, **kwargs)` — drop-in replacement for
  `json.dumps()` that enforces `allow_nan=False` after sanitization

Patched call sites:

| File | Line | Site | Priority |
|---|---|---|---|
| `backend/db/session_store.py` | 385 | artifact `content_json` write | CRITICAL |
| `backend/db/session_store.py` | 729 | save `metadata_json` write | CRITICAL |
| `backend/db/session_store.py` | 463 | upload `summary_json` write | defensive |
| `backend/db/session_store.py` | 474 | `table_names` list write | defensive |
| `backend/main.py` | 319 | embedding vector write | defensive |

Patch applier (`apply_nan_fix_step2.py`) backed up both files and
swapped `json.dumps(...)` → `safe_json_dumps(...)` at the five sites,
plus the import. A subsequent hot-fix
(`apply_nan_fix_step2_importfix.py`) corrected the import path style
from `backend.utils.json_safe` to `utils.json_safe` to match the
project's existing entry-point script execution model.

### End-to-end verification

After all patches applied:

1. ✅ Import smoke test: `from backend.utils.json_safe import safe_json_dumps` works
2. ✅ Server starts cleanly via `python3 backend/main.py`
3. ✅ Fresh GL query (`SELECT * FROM general_ledger LIMIT 10`) ran cleanly,
   chart rendered with correct empty-cell handling
4. ✅ Save executed; diagnostic re-ran post-save reports 0 NaN across
   all four scan phases

The patch is locked in. Sims 3, 4, 6 (which query AP with NULL
`payment_date` or further GL queries with sparse columns) are now
protected from the same bug class.

---

## Phase 6 journal-worthy findings (capture before continuing)

Three findings emerged from Sims 1-2 that the eventual journal can
draw on directly. Each is grounded in screenshots and saved records,
not just claims.

### 1. CASSIA passed the graceful-fallthrough test (Sim 1, Prompt 3)

When asked an out-of-scope question (AR recordkeeping rules from a
document that only covers employment tax recordkeeping), CASSIA
returned the orange "Not found in docs" badge with the text "I couldn't
find that in the available documents" — instead of confidently
fabricating an answer.

**Journal framing:** *"CASSIA's RAG layer admits scope boundaries
honestly. When the IRS Pub 15 corpus doesn't cover the user's
question, the response carries a visible 'Not found in docs' badge
rather than hallucinating an answer dressed up with plausible-sounding
page citations."*

### 2. CASSIA's BOTH-route synthesis is the current architectural ceiling (Sim 2, Prompts 3-4)

The router correctly classifies questions that need both data and
rules. The individual SQL and RAG pipelines retrieve their portions
reliably. But when the same BOTH-routed prompt asks the model to
*reason across the two retrievals* rather than fetch new information,
the SQL branch falls through to its no-data short-circuit instead of
using the prior turn's data as context.

**Journal framing:** *"CASSIA reliably retrieves both sides of a
BOTH-classified question. Coordinating those retrievals into reasoned
synthesis — particularly when the user is asking what's wrong or
missing rather than what exists — is where the current ceiling sits.
Phase 6 surfaced this through a payroll-tax review scenario in which
the data and the rules were each retrieved correctly, but the
synthesis prompt asking 'what looks wrong or missing' received a
canned no-data response."*

### 3. Realistic data exposed a latent NaN-in-JSON storage bug (Sim 2)

The bug existed since Pass 3 of the SQL pipeline. It never surfaced
during Phases 3-5 testing because earlier queries used tables with
dense numeric columns. The first realistic GL query — anchored to the
sparse double-entry debit/credit pattern of an accounting general
ledger — triggered it within the first response.

**Journal framing:** *"Phase 6's value as a simulation phase is best
demonstrated by what it found that earlier testing couldn't. Sim 2's
GL query produced empty debit-or-credit cells (standard double-entry
behavior) that became NaN values in the SQL pipeline's pandas
processing, which serialized through to the database, which then
broke Starlette's strict JSON response renderer on subsequent reads.
Realistic data caught what synthetic test scenarios had missed."*

---

## Deferred work (intentionally not addressed)

The following observations were noted but not fixed during this
session. Each has a clear scope boundary explaining why.

### Architectural — defer to Phase 7

**BOTH-route synthesis ceiling fix.** Two cleanest options would be
(a) a stub-recognition filter in the synthesizer that ignores SQL
results matching the no-data pattern, and (b) making the SQL pipeline
conversation-aware so it can reuse the prior turn's retrieval. Either
or both would resolve the Sim 2 Prompt 3/4 failure mode. **Not
implemented because Phase 6 is testing-only and the failure mode is
journal-worthy evidence.**

**Chart builder over-inclusion.** The chart builder treats every
numeric-typed column as a chartable series, which means date columns
(parsed as integers/timestamps), account_code, and period appear as
near-zero bars in charts that should only show debit/credit or
balance_due/etc. Visible in Sim 1's past-due chart (`due_date` as a
series), Sim 2's GL payroll chart (`date`, `account_code`, `period`),
and the post-patch GL test (same). A column-selection heuristic in
the chart builder would fix this. **Same scope reason as above.**

### Data — defer decision

**`journal_entries.csv` orphaned table.** Uses account codes
inconsistent with chart_of_accounts.csv. The v3 test plan routes
around it by phrasing prompts to use "general ledger" explicitly. No
prompts in Sims 1-2 referenced it. Decision deferred: leave / drop /
rebuild — pending whether any later sim accidentally hits it.

### Scope — out of session

**Sims 3-6.** Not started. Sim 3 (Revenue + Q1 net income recall) is
ready to run from v3 of the test plan. Sim 4 needs a mock Oracle email
PDF prepared first. Sim 5 needs Sims 1-3 saves in place (which they
are). Sim 6 is self-contained.

---

## Files created during this session

All delivered to `/mnt/user-data/outputs/` and downloadable. The ones
marked `[installed]` were actually run against the project; the ones
marked `[reference]` are tools that may be useful later.

| File | Purpose | Status |
|---|---|---|
| `PHASE6_TEST_PLAN_v3.md` | Updated test plan with data-informed pivots (Sim 2 reframed, Sim 4 anchored to Oracle, journal_entries flagged) | reference |
| `cassia_nan_check.py` | Diagnostic — scans DB for NaN/Inf across all relevant tables, four phases of progressively stricter checks | installed (kept) |
| `cassia_nan_cleanup.py` | One-time cleanup — sanitizes the 3 specific bad records, backs up first | installed (kept) |
| `backend/utils/json_safe.py` | New utility module added to the project tree — `sanitize_for_json` + `safe_json_dumps` | installed (committed candidate) |
| `apply_nan_fix.py` (Step 1) | Installs json_safe utility and scans likely call sites | installed (kept) |
| `apply_nan_fix_step2.py` (Step 2) | Patches 5 call sites: 4 in session_store.py, 1 in main.py | installed (kept) |
| `apply_nan_fix_step2_importfix.py` | Hot-fix correcting `backend.utils...` → `utils...` import path | installed (kept) |

### Backup files created

The project's `outputs/` directory and the affected source files have
the following backups, all dated 2026-06-07:

- `outputs/coreckoner.db.pre-nan-cleanup-2026-06-07_204944.bak` — full DB
- `backend/db/session_store.py.pre-nanfix-step2-*.bak`
- `backend/main.py.pre-nanfix-step2-*.bak`
- `backend/db/session_store.py.pre-importfix-*.bak`
- `backend/main.py.pre-importfix-*.bak`

These can be deleted once you're confident the patch is stable across
a few more sims, or kept indefinitely. They're small.

---

## Current project state

- **Sims completed:** 1 (PASS), 2 (PARTIAL)
- **Database integrity:** clean, 0 NaN, verified end-to-end
- **Code state:** patches applied to `backend/db/session_store.py` and
  `backend/main.py`; new module at `backend/utils/json_safe.py`
- **Git state:** patches not yet committed — working tree dirty
- **Server:** ready to run with `python3 backend/main.py`
- **Topics in My Core:** All saves (29), Unsorted (13), AR collection
  risk (4), Chart fix test (4), Net Income (2), Payroll Compliance (4),
  Q1 Tax Work (1)
- **Sessions:** original 11 + "SIM 1 - AR" + "SIM 2 - Payroll" +
  "PATCH VERIFY" (or whatever you named the GL test session)

---

## Next session pickup

When you return to this work, three options in order of recommendation:

1. **Commit the patches and continue Sim 3.** Recommended path. The
   patches are small, scoped, and verified. A single commit like
   `[phase6] add safe_json_dumps; patch sql_pipeline NaN bug` plus the
   utility module makes the bug fix a permanent part of the project.
   Then run Sim 3 from the v3 plan.

2. **Run Sim 3 first, then commit everything together.** Slightly more
   work tied up in working state, but lets you confirm Sim 3 doesn't
   surface another adjacent bug before committing.

3. **Write the journal now with Sims 1-2 + the bug story.** Possible
   but probably premature. Sim 5 (logout/login + multi-save recall) is
   the deepest workspace-identity test, and the journal is strongest
   with that evidence in hand.

My recommendation is path 1: commit, then Sim 3 fresh.

---

## What this session demonstrated about CASSIA

Not for the journal directly, but worth noting privately:

The fact that CASSIA exposed a latent bug *through realistic testing*
is exactly what Phase 6 was designed for. Phase 5 ended with a
feature-complete claim that was honest but unverified. Phase 6's first
hour of realistic testing produced:

- A confirmed graceful failure mode (Sim 1, Prompt 3)
- A documented architectural ceiling with screenshots (Sim 2, Prompts 3-4)
- A latent data-integrity bug found, fixed, and verified (the NaN issue)

That's three concrete journal entries from a single session. The
remaining sims will add more, but the foundation is already strong
enough that the journal can be written honestly regardless of how
Sims 3-6 go. The project has moved from "feature-complete by claim"
to "feature-complete by evidence" for the parts tested so far.

End of session log.
