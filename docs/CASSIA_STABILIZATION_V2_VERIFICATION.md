# CASSIA Stabilization v2 — Verification Plan

**Goal:** Confirm all four priorities are applied and behaving correctly,
before generating mock upload files for Demo Sims and proceeding to
deployment Wednesday.

**Estimated time:** 15-20 minutes (8 tests + 1 cross-check).

**Format:** For each test, mark **PASS** or **FAIL** as you go.
At the end, paste back a one-line summary per test — that's all I need
to confirm we're green for the next step.

---

## Step 0 — Pre-test: server startup smoke

Before any UI testing, confirm all patched files parse and the server
boots cleanly.

```bash
cd "/Users/sanghyunseong/Desktop/Z26 Glob NG consult/app 2 - chatbot/app2"

# 1. Syntax check across all patched files
python3 -m py_compile backend/pipelines/rag_pipeline.py     # P3
python3 -m py_compile backend/pipelines/chart_builder.py    # P1
python3 -m py_compile backend/main.py                       # P2 + P4

# Each should print nothing and return cleanly (exit code 0).

# 2. Kill any old server, start fresh
lsof -ti:8002 | xargs kill -9 2>/dev/null ; true
python3 backend/main.py
```

**Expected:** Server starts without import errors, ChromaDB telemetry
warning is fine (the cosmetic one we've seen before — ignore it),
"Uvicorn running on http://0.0.0.0:8002" appears.

**If startup fails:** stop the verification. Check the traceback —
likely an indentation issue from one of the patches. Roll back the
offending file from its `.bak`:

```bash
# Find the most recent .bak files
ls -lt backend/pipelines/*.bak backend/*.bak | head -10

# Restore (example for main.py):
cp backend/main.py.pre-p4-recall-2026-06-08_184606.bak backend/main.py
```

| Status | Outcome |
|---|---|
| ☐ PASS | Server started, ready to test |
| ☐ FAIL | (paste error back) |

---

## Step 1 — Priority 3: RAG "not found" message

**Setup:** Log in. Start a fresh session.

**Test 1.1 — RAG dead-end shows action-oriented wording**

Prompt:
```
What does the IRS say about reasonable cause for AR write-offs?
```

This routes RAG (no upload involved), and Pub 15 doesn't cover bad
debts at this depth.

**Expected:**
- Orange "Not found in docs" badge appears
- Message text mentions uploading a relevant document
- Specifically should contain something like:
  *"Try uploading a relevant policy, client memo, agency notice,
  or source document — I can search anything you add to the session."*

**Fail signs:**
- Old wording "I couldn't find that in the available documents" with
  no upload prompt → P3 may not have been applied to both sites

| Status | Notes |
|---|---|
| ☐ PASS | New wording confirmed |
| ☐ FAIL | (paste what you saw) |

---

## Step 2 — Priority 1: Chart column selection

These tests verify the new column-filtering logic. Three prompts cover
the three branches (preferred-column heuristic, AVOID list filtering,
existing-behavior preservation).

**Setup:** Same session is fine. No uploads needed (these query the
demo tables).

**Test 2.1 — General ledger chart (AVOID list excludes date/code/period)**

Prompt:
```
Show me the first 10 rows of the general ledger as a bar chart
```

**Expected:**
- Chart shows **only** `debit` and `credit` series
- No bars for `date`, `account_code`, `period`, `txn_id`
- Data table below still shows ALL columns (table is separate from chart)

| Status | Notes |
|---|---|
| ☐ PASS | Only debit + credit in chart |
| ☐ FAIL | (paste columns you saw) |

**Test 2.2 — AR aging chart (PREFERRED list picks balance_due)**

Prompt:
```
Show overdue balances by customer as a bar chart
```

**Expected:**
- Chart shows **only** `balance_due` as the measure series
- No `due_date`, `days_outstanding`, or `aging_bucket` bars
- `client_name` on the category axis

| Status | Notes |
|---|---|
| ☐ PASS | Only balance_due as measure |
| ☐ FAIL | (paste what you saw) |

**Test 2.3 — Revenue chart (existing behavior must be preserved)**

Prompt:
```
Show revenue by service line as a bar chart
```

**Expected:**
- Chart shows clean single series (revenue or ytd_total)
- Service line on category axis
- **Same look** as Sim 3 P1 from Phase 6 (Image 1) — no regression

| Status | Notes |
|---|---|
| ☐ PASS | Same as Sim 3 P1, no regression |
| ☐ FAIL | (paste what you saw) |

---

## Step 3 — Priority 2: BOTH-route SQL-unusable guard

These tests verify the synthesis-time stub/error detection. One test
exercises the new shield, one verifies the regression case.

**Setup:** Stay in the same session for the cross-table test (Test 3.1).
For Test 3.2 (regression), a fresh session is fine.

**Test 3.1 — Cross-table query that previously leaked SQL errors**

This was Sim 4 P2's failure mode. The router should classify this as
BOTH or SQL, and the SQL portion likely fails with a UNION mismatch
or missing column error.

Prompt:
```
Find Oracle Corporation invoices or payments in our accounting data — 
invoice dates, due dates, and current status across AR, AP, and revenue
```

**Expected:**
- The final answer does NOT contain:
  - "no such column"
  - "SELECTs to the left and right of UNION"
  - "execution failed"
  - "only one SQL statement"
  - "no uploaded data"
- Instead, you should see either:
  - A reasonable answer drawn from policy/guidance context, or
  - An honest "I couldn't form a reliable data query for this — could
    you specify which table or which Oracle-related field to check?"

**Fail signs:**
- Apologetic answer that mentions "execution failed" or quotes any
  technical SQL phrasing → P2's pattern list may need expansion

| Status | Notes |
|---|---|
| ☐ PASS | No raw SQL errors leaked |
| ☐ FAIL | (paste what you saw) |

**Test 3.2 — Standard BOTH route (regression — must still work)**

Prompt:
```
What overdue receivables do we have, and what does the IRS say about 
documenting bad debt write-offs?
```

**Expected:**
- Route badge shows BOTH (or whatever the router classifies it as,
  but synthesis should still combine data + policy)
- Answer weaves the AR numbers with the IRS guidance into a coherent
  3-5 sentence response
- Same quality as Phase 6 Sim 1 P5 — no regression

| Status | Notes |
|---|---|
| ☐ PASS | Clean blended answer, no regression |
| ☐ FAIL | (paste what you saw) |

---

## Step 4 — Priority 4: Core Recall timeout wrap

Two tests: normal-path verification (required) and induced-timeout
sanity check (optional but recommended for demo confidence).

**Test 4.1 — Normal Core Recall (must complete in 1-2 seconds)**

Setup: You'll need at least one save in your Core. The AR Collection
save from Sim 1 should still exist.

Prompt:
```
Recall what I saved about overdue AR
```

**Expected:**
- Answer arrives in 1-2 seconds
- Response shows Core Recall route + the AR collection content
- No UI change from prior behavior (timeout fix is invisible on the
  happy path)

| Status | Notes |
|---|---|
| ☐ PASS | Normal recall completes quickly |
| ☐ FAIL | (paste what you saw) |

**Test 4.2 — Induced timeout (OPTIONAL — skip if time-pressed)**

This is the only test that requires a code edit. It confirms the
timeout fallback message is reachable and readable.

```bash
# In backend/main.py, find the line:
#     core_result = _future.result(timeout=30.0)
# Change 30.0 to 0.1 temporarily.

# Restart server.
lsof -ti:8002 | xargs kill -9 2>/dev/null ; true
python3 backend/main.py
```

Then run any recall prompt. With timeout=0.1 the recall WILL exceed
0.1s, so the fallback fires.

**Expected:**
- User sees: *"Searching your saved work is taking longer than
  expected. Please try rephrasing your question, or try again in a
  moment."*

**After:** Change `timeout=0.1` back to `timeout=30.0`. Restart.

| Status | Notes |
|---|---|
| ☐ PASS | Fallback message appeared cleanly |
| ☐ SKIPPED | (no time) |
| ☐ FAIL | (paste what you saw) |

---

## Step 5 — Final cross-check (locator re-run)

Re-run the locator script. With all four patches applied, you should
see the new markers from each priority.

```bash
python3 ~/Downloads/cassia_v2_locator.py
```

**Expected new findings (in addition to the originals):**
- `PREFERRED_MEASURE_COLUMNS` and `_select_chart_columns` in chart_builder.py (P1)
- `_sql_unusable_patterns` in main.py (P2)
- `_cf.TimeoutError` and `concurrent.futures as _cf` in main.py (P4)
- New RAG wording in rag_pipeline.py (P3 — visible if the locator
  pattern matched the OLD string and it's now the NEW string, the
  locator may show 0 hits for P3's OLD pattern, which is also a PASS
  signal)

| Status | Notes |
|---|---|
| ☐ PASS | All markers present |
| ☐ FAIL | (paste output) |

---

## Summary template — paste this back when done

```
P0 startup:  PASS / FAIL
P3 RAG msg:  PASS / FAIL
P1 chart 2.1 (GL):       PASS / FAIL
P1 chart 2.2 (AR):       PASS / FAIL
P1 chart 2.3 (Revenue):  PASS / FAIL
P2 BOTH 3.1 (cross-table): PASS / FAIL
P2 BOTH 3.2 (regression):  PASS / FAIL
P4 recall 4.1 (normal):    PASS / FAIL
P4 recall 4.2 (timeout):   PASS / FAIL / SKIPPED
Locator re-run:  PASS / FAIL

Notes / anything weird:
- ...
```

---

## After verification

**If everything passes:** I generate the 7 mock upload files for Demo
Sims 1-4 in one batch. About 30-45 minutes of my output, then you can
run the Demo Sims.

**If anything fails:** paste the test output back, I'll diagnose and
ship a follow-up patch (or revise the failing one). Each priority's
rollback is independent via its `.bak` file, so a single failure
doesn't block the others.

**Rollback reference (in case you need it):**

```bash
# Each .bak filename includes the priority + timestamp.
# Examples (yours will have your own timestamps):
ls backend/main.py.pre-p2-both-*.bak       # rollback P2
ls backend/main.py.pre-p4-recall-*.bak     # rollback P4
ls backend/pipelines/chart_builder.py.pre-p1-chart-*.bak  # rollback P1
ls backend/pipelines/rag_pipeline.py.pre-p3-rag-msg-*.bak # rollback P3

# To roll one back, just cp the .bak over the live file:
cp backend/main.py.pre-p4-recall-*.bak backend/main.py
# Then restart the server.
```

---

## Time-budget note (Wednesday deadline)

- **Today (Mon):** verification (15-20 min), mock files generation (~45 min on my side, 0 on yours)
- **Tomorrow (Tue):** Demo Sims 1-4 execution (~2 hours with screenshots), any final tuning
- **Wednesday:** deploy

If verification takes longer than 30 minutes due to a fail, we cut
scope on the Demo Sims (drop the most ambitious one and run the
remaining three). The four priorities themselves are non-negotiable
for deploy — they fix the demo-critical failure modes from Phase 6.
