# CASSIA Pre-Deployment Stabilization Plan (v2)

**Supersedes:** v1 (the earlier document of the same name)
**Updated to reflect:** Phase 6 Sims 3-6 findings + feature-to-workflow
positioning + Final Demo Simulation Set v4 sequencing.
**Scope:** Four narrow, demo-affecting fixes before deployment this week.
Not a feature phase, not a refactor.
**Posture:** Smallest safe change per issue. Backup, patch, verify, ship.

---

## What changed from v1

For anyone re-reading v1: three deltas.

| Item | v1 | v2 |
|---|---|---|
| Priority 2 scope | Detect "No uploaded data" canned stub only | **Expanded:** detect any unusable SQL output (canned stubs + execution errors + multi-statement errors + missing-column errors) |
| Priority 4 | (Optional) welcome / quick-question wording | **Replaced:** Core Recall timeout + user-visible error message |
| Welcome wording | Was Priority 4 | **Deferred** to post-deploy polish patch |

Everything else carries forward unchanged.

---

## Plan summary

| # | Fix | Files (likely) | Risk | Defer if … |
|---|---|---|---|---|
| 1 | Chart column selection — prefer accounting measures, avoid identifiers/dates | `backend/pipelines/sql_pipeline.py` or `backend/charts/*.py` (locator script confirms) | **Medium** | Chart builder turns out tightly coupled to consumers (unlikely) |
| 2 | BOTH-route SQL-unusable guard — don't treat stubs OR execution errors as evidence in synthesis | Synthesizer module + possibly SQL pipeline (locator script confirms) | **Medium** | Synthesis constructed in many places (unlikely — usually a single prompt template) |
| 3 | RAG not-found message — action-oriented wording | `backend/pipelines/rag_pipeline.py` or wherever the string lives | **Very low** | Never |
| 4 (opt.) | Core Recall timeout (30s) + user-visible error | Core Recall handler (locator script confirms) | **Low** | Handler turns out to be sprawled across files (unlikely) |

Sequence: **3 → 1 → 2 → 4**. Easiest first, riskiest last. If time
runs short, dropping Priority 4 leaves the core fixes shipped.

---

## What I need before writing patches

A small **locator script** — read-only, runs in ~10 seconds — that
scans for:

- Chart-spec construction (function names like `build_chart_spec`,
  references to "chart" + column selection)
- The synthesis prompt template (long strings referencing both SQL +
  RAG content, or the LLM call that produces the final BOTH-route
  answer)
- The SQL stub emission point (`"No uploaded data in this session"`
  literal)
- The literal `"I couldn't find that in the available documents"`
- The Core Recall handler (function handling `/core/recall` or the
  recall pipeline)

The script outputs file:line for each. Patches written surgically
from there. **No guessing about file locations** (the lesson from the
`backend.utils` vs `utils` import-style mismatch in the NaN fix).

---

## Priority 1 — Chart column selection

### Problem (unchanged from v1)
Chart builder treats every numeric-typed column as a chartable series.
GL payroll: `date`, `account_code`, `period` render as near-zero bars
next to `debit`/`credit`. AR past-due: `due_date`, `days_outstanding`
appear next to `balance_due`. Visually noisy.

### Sims 3-6 update
Sim 3's revenue-by-service-line chart (Image 1) was **clean** —
single series. So the bug is column-specific: tables with mixed
identifier/date numeric columns (GL, AR, AP) trip it; tables with
pure-measure columns (revenue) don't. Heuristic still warranted —
we don't want demo charts depending on which table the query hits.

### Proposed fix (same as v1)

Add column-priority logic. Two named lists:

```python
PREFERRED_MEASURE_COLUMNS = {
    "balance_due", "amount", "debit", "credit", "revenue", "expense",
    "total", "net_income", "ytd_total", "payment_amount",
    "invoice_amount", "cash_balance", "outstanding_balance",
}

AVOID_AS_MEASURE_COLUMNS = {
    "date", "due_date", "invoice_date", "payment_date", "period",
    "account_code", "customer_id", "vendor_id", "client_id",
    "days_outstanding", "aging_bucket", "txn_id", "id",
}
```

Selection:

1. Explicit user request ("only balance_due") → honor, skip heuristic
2. Preferred-list match → use as series; avoid-list excluded
3. No preferred column found → return table only with a note, no
   misleading multi-series chart
4. Multiple preferred columns (e.g. `debit` + `credit`) → chart both

### Test checklist (extended)
- [ ] "Show overdue balances by customer as a bar chart" → AR chart
      shows only `balance_due`, no `due_date` / `days_outstanding`
- [ ] "Show me the first 10 rows of the general ledger" → only
      `debit` and `credit`, no `date` / `account_code` / `period`
- [ ] "Show revenue by service line as a bar chart" → existing
      behavior preserved (Sim 3 confirmed working)
- [ ] **Sim 1 Demo P3:** pie chart of AR by aging bucket → renders
      correctly with aging bucket as category, balance_due as measure
- [ ] **Sim 2 Demo P3, P6:** vendor bar + cash line → both clean
- [ ] **Sim 3 Demo P2, P5:** payroll line + gap bar → both clean
- [ ] Existing chart artifacts in Core (Sims 1, 2 from Phase 6) →
      still render (existing artifacts unchanged; only new charts use
      new heuristic)

### Risk and rollback
Same as v1. Single-file change, backed up. Restore .bak to revert.

---

## Priority 2 — BOTH-route SQL-unusable guard (EXPANDED)

### Problem (expanded)
The original Priority 2 was scoped to the "No uploaded data in this
session" canned stub. Phase 6 Sims 3-6 revealed the same downstream
problem with different upstream sources:

| Source | Example error text | Sim |
|---|---|---|
| Canned stub | `"No uploaded data in this session"` | Sim 2 |
| Multi-statement SQL | `"only one SQL statement can be executed at a time"` | Sim 5 P8 |
| UNION column mismatch | `"SELECTs to the left and right of UNION do not have the same number of result columns"` | Sim 4 P2 |
| Missing column | `"no such column: status"` | Sim 4 P2 |
| Generic exec failure | `"Execution failed on sql ..."` | Sim 4 P2 |

All of these get passed to the synthesizer as if they were data. The
synthesizer faithfully incorporates the error text into client-facing
answers. **This is the worst trust issue in the demo** — the user
sees apologetic technical-error language where they should see
either an answer or an honest "I couldn't get that comparison."

### Proposed fix (broader pattern set, same architecture)

**A. Unified detector** — one helper recognizing all SQL-unusable
shapes:

```python
STUB_PATTERNS = (
    "No uploaded data in this session",
    "No uploaded data",
    "This data is not in the uploaded files",
    "no data available",
)

ERROR_PATTERNS = (
    "only one SQL statement can be executed",
    "SELECTs to the left and right of UNION",
    "no such column",
    "Execution failed on sql",
    "syntax error",
    "no such table",
)

def is_sql_unusable(sql_result):
    """True if the SQL result is a stub message or an execution error."""
    # Case 1: error field set
    if sql_result.get("error"):
        return True
    # Case 2: single-row result with one message-like column
    rows = sql_result.get("rows", [])
    if len(rows) == 1 and isinstance(rows[0], dict) and len(rows[0]) == 1:
        val = str(list(rows[0].values())[0]).lower()
        if any(p.lower() in val for p in STUB_PATTERNS):
            return True
    # Case 3: result content contains error language
    content = str(sql_result.get("content", "")).lower()
    if any(p.lower() in content for p in ERROR_PATTERNS):
        return True
    return False
```

**B. Synthesis prompt update** — when `is_sql_unusable()` returns True,
the SQL result is **not** injected as evidence. Instead the prompt
receives an explicit signal:

```
[SQL retrieval: no usable structured-data result was produced for this
question. Do not infer presence or absence of data from this. If your
answer requires structured data, acknowledge that you couldn't form a
reliable query and recommend the user ask for the specific table,
amount, or reconciliation rule they want examined.]
```

And the synthesizer is instructed (in its system prompt addition):

```
If the SQL retrieval was unavailable, do not say things like "there
is no uploaded data," "the query execution failed," "we found no
records," or technical error messages. Instead, either:
  (a) answer from the RAG retrieval alone if it's sufficient, or
  (b) ask the user to specify the table, amount, or comparison target
      they want examined.
Never quote technical SQL error text to the user.
```

### Sims 3-6 update — what to verify

This priority now defends against four observed failure modes. Tests
must cover all four:

| Failure mode | Test prompt | Pass criteria |
|---|---|---|
| Canned stub (Sim 2) | "Using the payroll table shown above, what should we review next?" | No "no uploaded data" language in answer |
| Multi-statement (Sim 5) | Any BOTH-routed synthesis prompt | No "only one SQL statement" language |
| UNION mismatch (Sim 4) | "Find Oracle invoices in our AR, revenue, and AP tables" | Either graceful fallback or honest "couldn't form that query" |
| Missing column (Sim 4) | "Find Oracle invoices with status field" against AP | Same — no raw SQLite error visible |

### Risk and rollback (slightly elevated from v1)
Pattern list larger → slightly more chance a legitimate result gets
filtered (false positive). Mitigation: patterns are intentionally
distinctive error phrases unlikely to appear in real data. Plus a
defensive log of every filter trigger so we can tune later if needed.
Rollback unchanged — restore .bak.

### Critical: this is the only priority where v2 testing differs from v1
Run the four Phase 6 stress prompts after patching, not just one.
This is the priority most likely to need pattern tuning, so spending
15 extra minutes verifying all four modes is well-spent.

---

## Priority 3 — RAG not-found message

**Unchanged from v1.** One-line string replacement:

> "I couldn't find support for that in the currently indexed
> documents. Try uploading a relevant policy, client memo, agency
> notice, or source document — I can search anything you add to the
> session."

Risk: very low. Test: re-run Sim 1 P3 ("AR recordkeeping in Pub 15"),
confirm orange "Not found in docs" badge still appears with the new
message text.

---

## Priority 4 — Core Recall timeout (NEW, replaces v1's welcome wording)

### Problem
Phase 6 Sim 3 P3 ("Recall what I saved about Q1 net income") hung
for ~5 minutes with no progress indicator and no error. User
restarted the server to recover. The retry with a reworded prompt
worked.

Root cause is almost certainly the embedding API call (used to
embed the query for semantic search across saves) hanging without
a client timeout. Default OpenAI client may have no timeout or a
very long one.

This matters for Demo Sim 4 specifically — three consecutive Core
Recall prompts (P5, P6, P7) all in the most important sim for the
workspace identity claim. If any hang, the demo stops.

### Proposed fix

In the Core Recall handler, wrap the embedding API call with an
explicit timeout (30 seconds) and catch any timeout/error to return
a user-visible message:

```python
import asyncio

async def recall_with_timeout(query, user_id, timeout=30.0):
    try:
        return await asyncio.wait_for(
            _recall_pipeline(query, user_id),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return {
            "route": "CORE_RECALL",
            "content": (
                "Searching your saved work took longer than expected. "
                "Try rephrasing the question or asking again — if this "
                "keeps happening, the embedding service may be slow."
            ),
            "results": [],
            "timed_out": True,
        }
    except Exception as e:
        # Log for diagnostics; user-facing message stays generic
        logger.warning(f"Core Recall failed: {e}")
        return {
            "route": "CORE_RECALL",
            "content": (
                "I couldn't search your saved work right now. "
                "Try again in a moment."
            ),
            "results": [],
            "error": True,
        }
```

If the recall function isn't async, equivalent sync version with
`requests.post(..., timeout=30)` or similar.

### Files
Core Recall handler (locator script confirms — likely in
`backend/pipelines/recall_pipeline.py` or `backend/main.py`).

### Risk: Low
- Worst case: timeout fires falsely on a slow-but-legitimate query.
  User retries; works second time.
- 30s is well above typical embedding latency (~500ms), so false
  positives extremely unlikely.
- No state changes — failed recall doesn't corrupt anything.

### Rollback
Restore .bak.

### Test checklist
- [ ] After patch, run a normal Core Recall prompt → completes in
      ~1-2 seconds, no message change
- [ ] (Optional) artificially induce timeout by temporarily setting
      the timeout to 0.1s → confirm user-visible error message
      appears, no hang
- [ ] Demo Sim 4 P5, P6, P7 all complete (the three-recall sequence)

---

## Out of scope, defer post-deploy

Same list as v1, augmented with what Sims 3-6 surfaced:

- **SQL schema-awareness** (real fix for Sim 4 cross-table UNION/column errors). Output is shielded by expanded Priority 2; generation itself is feature work.
- **Multi-statement SQL prevention.** Same: output shielded, source-fix deferred.
- **Core Recall synthesis prompt tuning** (the "I have related saves but nothing directly answers" inappropriate-fire pattern). Partial cause is Sim 2's contaminated save flowing through (downstream of Priority 2 fix); partial cause is prompt design. Defer.
- **Welcome / quick-question wording.** Useful polish for the
  positioning, but a v2.13.1 patch a few days post-launch is fine.
- **Chart builder polish beyond column selection.** Series colors,
  axis labels, legend behavior. All polish, all post-deploy.
- **Router rewrite, BI dashboard features, EDD/FTB corpus, new
  workflows, frontend redesign** — same as v1, still out.

---

## Backup and rollback strategy

Same pattern as the NaN fix:

- Every patched file backed up with timestamped `.pre-deploy-stab-v2-<ts>.bak`
- Each priority gets its own applier — install and rollback independently
- Idempotent appliers — re-running on a patched tree is a no-op
- Post-patch: full regression smoke (login → SQL → RAG → BOTH → upload → save → recall → logout/login)
- If anything sideways: restore .bak files, project back to pre-stabilization state with no DB or state loss

---

## Sequencing and time estimate

| Phase | What | Estimated time |
|---|---|---|
| 0 | Locator script — confirm all five file paths | 5 min |
| 1 | Priority 3 (RAG message) — fastest win | 10 min |
| 2 | Priority 1 (chart column selection) | 30-45 min |
| 3 | Priority 2 (SQL-unusable guard, broadened) | 60-90 min |
| 4 | Priority 4 (Core Recall timeout) | 20-30 min |
| 5 | Full regression check + verify all four Sim 3-6 failure modes are now shielded | 25 min |
| Total | | **~3.5-4 hours** |

If time runs short: P4 is the safest to drop (it's a UX safety net,
not a correctness fix). P1+P2+P3 cover every Phase 6 demo-affecting
finding.

---

## How this plan supports the Final Demo Simulation Set v4

For cross-reference. Each priority maps to a Sim it directly enables:

| Priority | Enables / verifies | Failure mode prevented |
|---|---|---|
| 1 (chart) | Demo Sims 1, 2, 3 all have ≥2 charts. Clean charts make the demo read as polished | Multi-series noisy chart |
| 2 (SQL-unusable guard) | Demo Sims 1 P6, 2 P7, 3 P4, 4 P8 — every BOTH synthesis | Stub-contaminated synthesis; SQL error text in client-facing answers |
| 3 (RAG message) | Demo Sim 1 P4 (Bad debt IRS guidance), Sim 3 P3 (Pub 15) | Dead-end "couldn't find" with no next step |
| 4 (Recall timeout) | Demo Sim 4 P5, P6, P7 — three consecutive Recalls | 5-minute hang during the most important sim |

If all four priorities ship cleanly, Demo Sims 1-4 should run as
designed. If P4 is dropped, Demo Sim 4 has slightly higher hang
risk but can still complete (refresh + retry).

---

## What I'd like from you to proceed

1. **Confirm v2 plan is acceptable** as-shaped, or any adjustments
2. **Authorize the locator script** for the next turn (read-only,
   ~10 seconds, finds all five file paths)
3. **Order preference** — recommended 3 → 1 → 2 → 4, open to
   reordering

Once locator runs, I ship each priority as its own applier package
with backup/idempotency/rollback in the same pattern as the NaN fix.
Total elapsed time from "go" to "stabilization complete" is roughly
4 hours of active work.

After stabilization: 30-45 min to generate the 7 new uploads for the
demo sims, then run Demo Sims 1-4 with evidence capture. Deploy
follows.
