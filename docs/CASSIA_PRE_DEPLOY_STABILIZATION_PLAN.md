# CASSIA Pre-Deployment Stabilization Plan

**Scope:** Three narrow, demo-affecting fixes before deployment this week.
Not a feature phase, not a refactor.
**Posture:** Smallest safe change per issue. Backup, patch, verify, ship.

---

## Plan summary

| # | Fix | Files (likely) | Risk | Defer if … |
|---|---|---|---|---|
| 1 | Chart column selection — prefer accounting measures, avoid identifiers/dates | `backend/pipelines/sql_pipeline.py` or `backend/charts/*.py` (need to confirm location) | **Medium** | Chart builder turns out to be tightly coupled to chart_spec consumers (unlikely) |
| 2 | BOTH-route stub guard — don't treat "no uploaded data" SQL stubs as evidence in synthesis | Synthesizer module (need to locate) + possibly SQL pipeline | **Medium** | Synthesis is constructed in many places (unlikely — usually a single prompt template) |
| 3 | RAG not-found message — action-oriented wording | `backend/pipelines/rag_pipeline.py` or wherever the string lives | **Very low** | Never — this is a one-line string change |
| 4 (opt.) | Welcome / quick-question wording | `frontend/` (Vue or React component) | Low if isolated, skip if not | Touches multiple frontend files |

I recommend doing 1, 2, 3 sequentially with verification between each, and
treating 4 as a separate decision after 1-3 ship.

---

## What I need before I can write patches

Three files I have not seen in this session and whose paths I don't know
for certain. To avoid guessing wrong (the way I did with the
`backend.utils.json_safe` vs `utils.json_safe` import-style mismatch), I'd
rather identify them precisely first.

I propose a small **locator script** — read-only, runs in ~10 seconds —
that scans the project for:

- Chart-spec construction logic (function names like `build_chart_spec`,
  `chart_spec`, references to "chart" + columns selection)
- The synthesis prompt template (long string templates referencing both
  SQL results and RAG content, or the LLM call that produces the final
  BOTH-route answer)
- The literal string `"I couldn't find that in the available documents"`
- The literal string `"No uploaded data in this session"` to confirm
  exactly which file emits the stub

The script tells me file:line for each. I write the patches surgically
from there.

**Alternative if you'd rather not run another scan:** paste the contents
of `backend/pipelines/sql_pipeline.py` and any file under
`backend/pipelines/` or `backend/charts/` that looks chart-related, and
I'll find them by reading. Either path works.

---

## Priority 1 — Chart column selection

### Problem
Chart builder treats every numeric-typed column as a chartable series.
On the GL payroll query in Sim 2, this meant `date`, `account_code`, and
`period` rendered as near-zero bars alongside `debit` and `credit`. On
the AR past-due query in Sim 1, `due_date` and `days_outstanding`
appeared as series alongside `balance_due`. Visually noisy; reduces demo
credibility.

### Proposed fix (heuristic, not BI)

Add column-priority logic to the chart builder. Two named lists drive
selection:

```python
PREFERRED_MEASURE_COLUMNS = {
    # ordered by priority — first match wins for primary measure
    "balance_due", "amount", "debit", "credit", "revenue", "expense",
    "total", "net_income", "ytd_total", "payment_amount",
    "invoice_amount", "cash_balance", "outstanding_balance",
}

AVOID_AS_MEASURE_COLUMNS = {
    # never chart these even if numeric
    "date", "due_date", "invoice_date", "payment_date", "period",
    "account_code", "customer_id", "vendor_id", "client_id",
    "days_outstanding", "aging_bucket", "txn_id", "id",
}
```

Selection algorithm:

1. If user prompt explicitly names columns ("only balance_due", "show
   debit and credit") → honor that, skip heuristic
2. Else: pick columns whose names are in `PREFERRED_MEASURE_COLUMNS` for
   chart series; ignore `AVOID_AS_MEASURE_COLUMNS` even if numeric
3. If no preferred measure column found → return table only, no chart,
   with an explanation rather than a misleading multi-series chart
4. If multiple preferred columns exist → chart all of them (e.g.
   `debit` + `credit` is a legitimate two-series chart)

The "explicit user request" detection is the only LLM-touching piece;
everything else is string matching against column names. Low risk.

### Files
- Most likely: a chart-spec builder inside `backend/pipelines/` (need to
  confirm via locator script)
- The frontend chart renderer is **not** touched — same chart_spec
  shape, just fewer/better series

### Risk: Medium
- Existing working charts (AR balance bar chart, revenue by service
  line) must still render
- A chart that previously had 5 series and now has 1-2 is an
  improvement, not a regression
- Edge case: if some prompt deliberately wants to chart `date` or
  `aging_bucket` as a category, the avoid-list blocks it. The fix:
  honor explicit user requests (point 1 above), which handles this.

### Rollback
Single file change, backed up before edit. To revert: copy
`.pre-chartfix-*.bak` back over. No DB changes.

### Test checklist
After patching, run these in order. Each is a separate chat prompt:

- [ ] "Show overdue balances by customer as a bar chart" → AR chart
      should show **only** `balance_due` series (single color), not
      include `due_date` or `days_outstanding`
- [ ] "Show me the first 10 rows of the general ledger." → chart should
      show only `debit` and `credit` series, not `date` `account_code`
      `period`
- [ ] "Show revenue by service line as a bar chart." → existing
      behavior preserved (revenue column only)
- [ ] "Show only balance_due by customer as a bar chart, sorted
      descending" → explicit request honored
- [ ] "Chart account_code by date" → if heuristic refuses, message says
      "no clear accounting measure found, returning table" instead of
      producing a confusing chart
- [ ] Existing saves in My Core that have chart_spec artifacts → still
      render (existing artifacts unchanged; only new charts use the new
      heuristic)

---

## Priority 2 — BOTH-route stub guard

### Problem
The SQL pipeline emits a canned `SELECT 'No uploaded data in this session.' AS message;`
stub when prompt-to-SQL can't generate a real query (e.g. synthesis
questions like "what's wrong or missing"). The final synthesizer then
incorporates that stub text as if it were evidence. User-facing result:
CASSIA produces a confident-sounding answer that contradicts itself
("we found that there is no uploaded data in this session").

This is the trust risk you flagged. It's also narrow — there are
specific known stub patterns the SQL pipeline emits.

### Proposed fix (narrow stub detection + cautious fallback)

Two changes:

**A. Stub detector** — a small helper that recognizes known canned
no-data SQL results. It checks:

```python
STUB_PATTERNS = (
    "No uploaded data in this session",
    "No uploaded data",
    "This data is not in the uploaded files",
    "This data isn't in the demo tables",
    "no data available",
)

def is_sql_stub(sql_result):
    # Single-row result with a 'message' column matching a stub pattern
    rows = sql_result.get("rows", [])
    if len(rows) != 1:
        return False
    first = rows[0]
    if not isinstance(first, dict) or len(first) != 1:
        return False
    val = str(list(first.values())[0])
    return any(p.lower() in val.lower() for p in STUB_PATTERNS)
```

**B. Synthesis prompt update** — in the BOTH-route final synthesis
prompt, when `is_sql_stub(sql_result)` is True, the SQL result is
*not* injected as evidence. Instead the prompt receives an explicit
signal:

```
[SQL retrieval: no usable structured-data result was produced for this
question. Do not infer presence or absence of data from this. If
synthesis would require structured data, say so explicitly and
recommend the user ask for the specific table, amount, or
reconciliation rule they want compared.]
```

And the synthesizer is instructed (in its system prompt or template
addition):

```
If the SQL retrieval was unavailable, do not say things like "there is
no uploaded data" or "we found no records." Instead, either:
  (a) answer from the RAG retrieval alone if it's sufficient, or
  (b) ask the user to specify the table, amount, or comparison target
      they want examined.
```

This is a prompt-engineering change, not a router rewrite. The router
still classifies as BOTH; both pipelines still run; only the synthesis
layer changes how it handles a stub-shaped SQL output.

### Files
- Synthesizer module (need to locate — likely in `backend/pipelines/` or
  embedded in `main.py`)
- Possibly the SQL pipeline if the stub is constructed there and we'd
  rather have it emit a structured marker instead of a query result

### Risk: Medium
- Prompt template changes can shift LLM behavior in unintended ways.
  Mitigation: test against the exact Sim 2 sequence + 2-3 normal BOTH
  questions to confirm the working cases still work.
- The stub patterns are a fixed list — if SQL pipeline emits a stub
  with different wording, detector misses it. Mitigation: log uncaught
  stub-like patterns for future tuning.

### Rollback
Synthesizer template change is reversible by restoring the prompt
string. SQL pipeline (if touched) is reversible from .bak.

### Test checklist
The exact Sim 2 sequence:

- [ ] "Show me the payroll-related activity in our general ledger" →
      SQL retrieves correctly (Sim 2 Prompt 1 — must still work)
- [ ] "What does the IRS say about payroll deposit schedules?" → RAG
      retrieves correctly (Sim 2 Prompt 2 — must still work)
- [ ] **"Based on what's actually in our books and what the IRS
      requires, what looks wrong or missing in how we're tracking
      payroll taxes?"** → CASSIA must NOT say "there is no uploaded
      data." It should either reason from the prior turn's data + the
      IRS guidance, or say something like "I have the IRS guidance but
      need you to point to a specific reconciliation rule or expected
      schedule to compare against"
- [ ] **"Draft a short note to the client explaining what we found"** →
      should NOT inherit the broken premise; should either say it
      needs a specific comparison target or draft from the actual
      retrieved data

And normal BOTH-route questions (regression check):

- [ ] "What are the IRS rules for AR documentation and does our books
      show good documentation practices?" → both pipelines fire, both
      return real results, synthesis uses both
- [ ] "Show overdue invoices and tell me what penalties might apply" →
      same

### Failure-mode visibility
After the fix, when SQL stub fires, the user sees something like:

> "I retrieved IRS guidance on payroll deposit schedules: [content].
> However, for the structured-data comparison you're asking about, I
> couldn't form a reliable query. To proceed, please point me to a
> specific schedule or reconciliation rule — for example, 'compare
> our Q1 payroll deposits against the monthly deposit schedule for
> $50k-$2.5M payroll'."

That's the trust-preserving fallback. The system is honest about what
it can't do.

---

## Priority 3 — RAG not-found message

### Problem
Current: "I couldn't find that in the available documents."
Reads as a dead-end. The architecture supports uploading documents to
expand the corpus, but the message doesn't say that.

### Proposed fix
String replacement. The new message:

> "I couldn't find support for that in the currently indexed documents.
> Try uploading a relevant policy, client memo, agency notice, or source
> document — I can search anything you add to the session."

The second sentence is the action-oriented part.

### Files
Wherever the literal string `"I couldn't find that in the available documents"`
lives. Could be in `backend/pipelines/rag_pipeline.py`, `backend/main.py`,
or a frontend display string. Locator script confirms.

### Risk: Very low
- It's a string. The only way this breaks anything is if the string is
  used as a parsing target somewhere downstream (extremely unlikely for
  a user-facing message).
- The orange "Not found in docs" badge state is preserved — the
  ROUTING behavior doesn't change, only the message text.

### Rollback
Restore from .bak.

### Test checklist
- [ ] Re-run Sim 1 Prompt 3: "What does the IRS say about recordkeeping
      requirements for receivables?" → orange "Not found in docs" badge
      still appears, new message visible
- [ ] Confirm the message includes the upload suggestion
- [ ] Confirm CASSIA does not start hallucinating policy content
      (regression check — the not-found behavior should be unchanged
      except for the wording)

---

## Priority 4 (optional) — Welcome / quick-question wording

### Recommendation: defer to a separate pass

Frontend touches I haven't seen in this session. The welcome text and
quick questions live in Vue or React components I haven't read. Risk of
breaking layout or compilation if I patch blind is non-trivial.

If you want to do this anyway, the cleanest path is: you tell me which
file the welcome text lives in, I write a tiny string-only patch (no
JSX/template changes), you apply it. But honestly, deferring this until
after deployment is fine — wording is the easiest thing to ship as a
v2.13.1 polish patch a few days after launch.

---

## Backup and rollback strategy

Same pattern as the NaN fix:

- Every patched file is copied to `<filename>.pre-deploy-stab-<timestamp>.bak`
  before any edit
- The applier script is idempotent — re-running on a patched tree is
  a no-op
- Each priority gets its own applier so they can be installed
  independently and rolled back independently
- After all three patches: a fresh `cassia_nan_check.py` run + a quick
  smoke test (login, open a session, ask a SQL question, ask a RAG
  question, save, recall) confirms no regression in the surrounding
  system

If anything goes sideways post-patch, restoring the .bak files brings
the project back to the pre-stabilization state with no DB or state
loss.

---

## Sequencing and time estimate

| Phase | What | Estimated time |
|---|---|---|
| 0 | Run locator script, confirm file paths | 5 min |
| 1 | Priority 3 (RAG message — fastest, safest first) | 10 min patch + verify |
| 2 | Priority 1 (chart column selection) | 30-45 min patch + 15 min verify |
| 3 | Priority 2 (BOTH stub guard) | 45-60 min patch + 30 min verify (most prompt-tuning risk) |
| 4 | Final regression check across all paths | 20 min |
| Total | | ~2.5 - 3 hours of focused work |

Suggested order: 3 → 1 → 2 (easiest-first, riskiest-last). That way if
time runs short before deployment, the highest-risk item is the only
one not shipped, and Priorities 1 and 3 are already live.

---

## What I'd like from you

To start writing patches I need:

1. **Confirmation this plan is acceptable** as-shaped, or any
   adjustments
2. **Permission to run the locator script** so I have exact file paths
   (or you paste the relevant files instead)
3. **Order preference** — my recommendation is 3 → 1 → 2 but you may
   want a different sequence

Once those three are in, I'll ship the locator script first, then each
priority as its own applier package with backup/idempotency/rollback in
the same pattern as the NaN fix.

---

## Out of scope reminder (per your directive)

The following are NOT in this pass and stay deferred:

- New accounting workflows
- EDD / FTB / agency notice source libraries
- Router rewrite or reasoning-agent
- BI dashboard features
- Multi-document upload comparisons beyond current capability
- Frontend UI redesign
- New Core features
- Sims 3, 4, 5, 6 from the v3 test plan (treat Sims 1+2 + this
  stabilization as Phase 6 closure)

If any of these show up as "while we're in there" temptations during
patching, I'll flag them and we defer.
