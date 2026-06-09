# CASSIA Demo Sims — Expected Outputs & Failure Triage

A keep-open reference for the run. For each prompt: the expected route, what a good
result looks like (anchored to your real DB data), and — most importantly — whether a
wobble is a **✓ pass**, a **note & continue**, or one of the few **STOP** cases.

---

## The one rule that removes the stress

**You do not fix anything mid-run.** The stabilization patches exist precisely so that
when something goes sideways, it degrades into a clean, presentable state instead of
breaking:

- A bad SQL query → P2/P2b turn it into a clean fallback sentence, not an error.
- A slow Core Recall → P4 returns a controlled message within 30s, no hang.
- A question outside the IRS corpus → P3 returns an honest "not found," which is a
  *designed* demo moment, not a failure.

So your decision rule is simple:

> If you see a chart, a real answer, or a clean fallback sentence → **it's working. Move on.**
> If something looks shallow, narrow, or imperfect → **note it, screenshot, continue.**
> Only **STOP** for the two true blockers below. Everything else is parked for *after* the
> run, calmly — never mid-sim.

**The only two real STOP cases:**
1. **An upload won't ingest at all** (the file you attached produces no summary / the model
   acts as if no file was given). Fix = just re-upload it; if it still fails, switch to a
   fresh session. Not a code fix.
2. **A Save won't persist** (you save, but My Core stays empty / it vanishes on refresh).

If you ever see a **raw stack trace or 500 error page in the chat** (the patches should
prevent this): screenshot it, skip that prompt, keep going with the rest. We look at it
*after* the run. It does not stop the sim.

---

## Sim 1 — AR Year-End Cleanup

Real overdue AR anchors: Frontier $31,000, NorthStar $19,500, Quest $16,500, Liberty
$14,000, Titan $9,400, Pacific $8,800, BlueStar $8,200, KLM $4,800, Union Pacific $2,800
(≈ $115K across 9 customers; the three 90+ are Titan, KLM, Union Pacific).

| # | Prompt | Route | Expected | If off → |
|---|---|---|---|---|
| 1 | Read Jennifer's email | RAG (upload) | Summary naming the 3 questions + Titan/Union Pacific/KLM | **STOP only if** no summary at all → re-upload |
| 2 | "all overdue AR" bar chart | SQL + bar | ~9 customers, single-measure bars, Frontier highest | If only 3 bars → it narrowed to 90+; re-ask "all aging buckets". note & continue |
| 3 | AR by aging bucket, pie | SQL + pie | 4 slices: Current / 31-60 / 61-90 / 90+ | Cosmetic oddities → note & continue |
| 4 | IRS on bad-debt deduction | RAG | **Likely honest "not found"** (corpus is payroll Pub 15, not Pub 535) | ✓ This is the designed honest-limit moment — NOT a failure |
| 5 | Compare credit memos vs AR | SQL + upload | Flags ~5 unapplied credits (Quest, Titan, Union Pacific, Liberty, KLM) | If SQL hiccups → P2b clean fallback. note & continue (this is the "partial" path) |
| 6 | BOTH: write-off candidates + docs | **BOTH** | Reasons across all 3 sources; Union Pacific/KLM as write-offs, Titan as disputed | If shallow → note (partial). If it echoes a stub → note; shouldn't happen (P2) |
| 7 | Draft response to Jennifer | conversational | Client-ready email draft | Always works (pure LLM) |
| 8 | Save → topic → "also move session" | save | Toast confirms save + topic + "session also moved" | **STOP only if** save doesn't persist |

Topic: *AR Collection Follow-up — BlueRiver Q4 close*

---

## Sim 2 — Vendor Strategy Under Cash Constraint

Anchors: Oracle = INV-038, $15,000, Overdue. Bank statement ends ~$8,800 (tight).

| # | Prompt | Route | Expected | If off → |
|---|---|---|---|---|
| 1 | Summarize Oracle's claim | RAG (upload) | ~$15K, ~57 days overdue, payment demand | STOP only if no ingest → re-upload |
| 2 | Summarize cash from bank CSV | SQL on upload | Weekly cash, ending ~$8,800 | note & continue |
| 3 | Overdue AP by vendor, bar | SQL + bar | Vendors ranked; Oracle near top at $15K | note & continue |
| 4 | Find Oracle invoices in AP | SQL | INV-038, $15K, dates, Overdue | ✓ Already verified working |
| 5 | IRS/guidance on AP prioritization | RAG | **Likely honest "not found"** (cash mgmt not in Pub 15) | ✓ Designed honest-limit — not a failure |
| 6 | Weekly cash line chart | SQL on upload + line | Clean downward trend | note & continue |
| 7 | BOTH: prioritize + Oracle reply + action list | **BOTH** | Real prioritization (pay critical, defer others) + draft | If shallow → note (partial) |
| 8–9 | Save → topic → checkbox | save | Persists; toast confirms | STOP only if save fails |

Topic: *Vendor Follow-up — BlueRiver April cash*

---

## Sim 3 — Payroll Compliance (CP220)

Anchors: 3 late deposits (Feb 16–28: 8 days → 5%; Mar 1–15: 18 days → 10%; Mar 16–31:
3 days → 2%). Total FTD penalty ≈ **$3,707.87**.

| # | Prompt | Route | Expected | If off → |
|---|---|---|---|---|
| 1 | Read the IRS notice | RAG (upload) | CP220, Q1 2026 Form 941, FTD penalty ~$3,708 | STOP only if no ingest → re-upload |
| 2 | Deposit history line chart | SQL on upload + line | 6 periods over time | note & continue |
| 3 | IRS deposit schedule + penalty tiers | RAG | **Strong answer** — 2/5/10/15% tiers, page 36 | ✓ Already verified working |
| 4 | BOTH: actual vs required, what missed, penalty | **BOTH** | Names the 3 late deposits; penalty ≈ $3,708 | **The key test.** If clean → P2 confirmed. If it echoes a stub/error → note (shouldn't happen) |
| 5 | Gap chart by month, bar | SQL + bar | Gaps visible in Feb & Mar | note & continue |
| 6 | Draft IRS response | conversational | IRS-ready reply | Always works |
| 7 | Draft internal note for Jennifer | conversational | Client-internal note | Always works |
| 8–9 | Save → topic → checkbox | save | Persists; toast confirms | STOP only if save fails |

Topic: *IRS/Agency Notice — CP220 Q1 payroll*
Watch: if P4 cites a penalty number, it should be near **$3,708** (it reconciles to the
register on purpose). A wildly different invented number = note it.

---

## Sim 4 — Quarterly Continuity (the workspace-identity sim)

Run last. Forecast anchors (Q1): Consulting $95K, Audit $70K, Accounting $45K, Tax $38K,
Bookkeeping $22K.

**Phase A — logout/login**

| Step | Expected | If off → |
|---|---|---|
| Log out → wait ~30s → log back in | Sessions + topics restored | **STOP only if** everything is gone after re-login (persistence break) |
| Check My Core | AR / Vendor / IRS-Notice topics from Sims 1–3 present | If a topic is missing → note; check you completed that sim's save |

**Phase B — review session**

| # | Prompt | Route | Expected | If off → |
|---|---|---|---|---|
| 1 | Read Q4 2025 board memo | RAG (upload) | Q4 context summary (~$340K rev, AR/cash/payroll threads) | STOP only if no ingest → re-upload |
| 2 | Q1 revenue by service line, bar | SQL + bar | 5 lines ranked, Consulting likely top | note & continue |
| 3 | Actual vs forecast variance (upload forecast) | SQL on upload | Variance by service line vs the forecast | Cross-source → if SQL hiccups, P2b fallback. note & continue |
| 4 | QoQ revenue trend line | SQL + line | Q4→Q1 trend | note & continue |
| 5 | Recall AR collection risk | **Core Recall** | Returns your **Sim 1** save | If slow → P4 returns a message in 30s; refresh & retry once, then note |
| 6 | Recall vendor strategy | **Core Recall** | Returns your **Sim 2** save | same as above |
| 7 | Recall payroll/IRS notice | **Core Recall** | Returns your **Sim 3** save | same as above |
| 8 | BOTH: combine 3 recalls + current data → memo | **BOTH** | Coherent memo weaving all 3 + revenue/variance | If it references fewer than 3 → note (partial), still presentable |
| 9 | Top 3 priorities for Q2 | conversational | Prioritization | Always works |
| 10–11 | Save → topic → checkbox | save | Persists; toast confirms | STOP only if save fails |

Topic: *Client Review — BlueRiver Q1 2026*

**Because you cleaned Core**, prompts 5–7 have nothing to compete with, so the right save
should surface for each. If a recall returns *nothing*, that's the archive→recall
assumption to check (note it; don't fix mid-run).

---

## After the run

Park anything you noted. None of it needs a same-day fix. Bring the notes + screenshots
back and we triage calmly: most "notes" will be passes-on-reflection (honest limits,
graceful fallbacks), and anything genuinely worth a patch gets the same careful
locate → backup → apply → verify treatment as P2b — never rushed, never mid-demo.
