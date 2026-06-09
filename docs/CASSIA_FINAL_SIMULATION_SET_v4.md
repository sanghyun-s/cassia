# CASSIA Final Demo Simulation Set (v4)

**Context:** Final pre-deployment simulation set. Replaces Phase 6 Sims
3–6. To be run **after the stabilization patches have been applied**.
These four simulations double as the demo material for pitching, the
verification matrix for the stabilization fixes, and the journal
evidence for the workspace claim.

**Design principles** (all four sims meet these):

- Tells one **complete accounting workflow story** end to end
- Maps explicitly to the **Ask → Retrieve → Visualize → Save → Organize
  → Recall → Follow up** flow from the feature-to-workflow mapping
- Each simulation includes **at least one BOTH-routed hybrid prompt**
- Each simulation uses **at least two chart types** (bar, line, pie)
- Each simulation includes **at least two file uploads** (CSV / PDF /
  both)
- Each simulation **lands in a named topic** under the Outlook-folder
  pattern
- Each simulation has at least one moment where CASSIA's behavior
  **demonstrates honest limits** (graceful fall-through, sourced
  citations, or visible route badges) — this is what makes the demo
  trustworthy rather than magical

---

## Coverage matrix

| Capability | Sim 1 (AR Year-End) | Sim 2 (Cash-Constrained Vendor) | Sim 3 (Payroll Notice Response) | Sim 4 (Quarterly Continuity) |
|---|:-:|:-:|:-:|:-:|
| BOTH-route synthesis (≥1) | ✓ | ✓ | ✓ | ✓ |
| Bar chart | ✓ | ✓ | ✓ | ✓ |
| Pie / line / other chart | pie | line | line | line |
| PDF upload (≥1) | ✓ | ✓ (Oracle email — already created) | ✓ (mock IRS notice) | ✓ |
| CSV upload (≥1) | ✓ | ✓ | ✓ | ✓ |
| Save to Core | ✓ | ✓ | ✓ | ✓ |
| Topic organization | ✓ | ✓ | ✓ | ✓ |
| Core Recall (single save) | | | | ✓ |
| Core Recall (multi-save) | | | | ✓ |
| Logout/login continuity | | | | ✓ |
| Pass 5 "Also move source session" | ✓ | ✓ | ✓ | ✓ |
| Graceful fall-through / honest limit | RAG not-found on dispute resolution | RAG not-found on cash management | BOTH stub-guard verification | recall across topics |
| Maps to topic | AR Collection Follow-up | Vendor Follow-up | IRS/Agency Notice Research | Client-Specific Review |

---

## Required uploads — what to prepare before running

| File | Sim | Status |
|---|---|---|
| `oracle_invoice_followup_email.pdf` | Sim 2 | ✅ Already created |
| `client_year_end_request.pdf` | Sim 1 | Need to create (I'll draft when you say go) |
| `credit_memo_log.csv` | Sim 1 | Need to create (small, ~10 rows) |
| `bluerver_bank_statement.csv` | Sim 2 | Need to create (4 weeks of cash position) |
| `irs_notice_cp220.pdf` | Sim 3 | Need to create (mock CP220-style notice) |
| `payroll_register_q1.csv` | Sim 3 | Can derive from GL or create fresh |
| `q4_2025_board_memo.pdf` | Sim 4 | Need to create (1-page prior-quarter memo) |
| `revenue_forecast_2026.csv` | Sim 4 | Need to create (12-month forecast) |

I can draft each PDF/CSV in batch when you're ready — probably 30
minutes of generation work, all small files. Recommend doing them in
one pass after the stabilization patches ship.

---

# Sim 1 — AR Collection & Year-End Cleanup

**Topic on completion:** *AR Collection Follow-up — BlueRiver Q4 close*
**Estimated duration:** 8 prompts + organize. ~10-15 minutes.

### Business situation

It's late December. BlueRiver Consulting's VP Finance, Jennifer
Martinez, emails her accountant about year-end AR cleanup. She wants
to know which receivables should be written off as bad debt, which
should remain on the books, and what documentation she needs. She
also attaches her own credit-memo log to make sure those entries are
reflected. The accountant uses CASSIA to investigate, get IRS
guidance on bad debt deduction rules, and produce a year-end
recommendation.

### Workflow map (7 steps)

| Step | Sim activity |
|---|---|
| Ask | Prompt 1 — read client request |
| Retrieve | Prompts 2, 3, 4 — AR data, IRS guidance, credit memo cross-check |
| Visualize | Prompts 2, 3 — bar chart + pie chart |
| Save | Prompts 7 — save recommendation |
| Organize | Step 8 — create topic, move save + source session |
| Recall | (Demonstrated downstream in Sim 4) |
| Follow up | Prompt 6 — drafted client response |

### Required uploads (before starting)
- `client_year_end_request.pdf` — Jennifer's email asking for cleanup recommendations
- `credit_memo_log.csv` — small table (~10 rows) with credit memo IDs, dates, customer names, amounts

### Prompt sequence

| # | Prompt | Expected route | Expected output |
|---|---|---|---|
| 1 | (Upload PDF first) "Read Jennifer's email and summarize what she's asking for." | RAG (upload) | Summary of cleanup request, identifies the questions |
| 2 | "Show overdue AR balances by customer as a bar chart, highest to lowest." | SQL + bar chart | AR table + clean single-series bar chart of `balance_due` |
| 3 | "Show the distribution of total AR by aging bucket as a pie chart." | SQL + pie chart | Pie chart: Current / 31-60 / 61-90 / 90+ |
| 4 | "What does the IRS say about deducting business bad debts and the documentation required?" | RAG | Pub 15 + related sources, with citations |
| 5 | (Upload CSV) "Compare Jennifer's credit memo log to our AR records — are there any credits that should already have been applied but show as overdue?" | SQL + uploaded CSV | Cross-reference table |
| 6 | "Based on the AR data, the IRS rules, and Jennifer's credit memos, which receivables look like bad-debt write-off candidates, and what documentation should she gather?" | **BOTH** | Synthesis combining all three sources |
| 7 | "Draft a response to Jennifer that walks her through the candidates, the rationale, and the documentation she'll need." | Conversational | Client-ready email draft |
| 8 | (💾 Save) Save as "Year-end AR cleanup — BlueRiver" → create topic "AR Collection Follow-up — BlueRiver Q4 close" → check "Also move source session" | save + topic + Pass 5 | Topic created with save + session inside |

### Pass / partial / fail

| Outcome | Criteria |
|---|---|
| ✅ Pass | All 8 steps complete; both charts clean (single-measure series after Priority 1 stabilization fix); cross-reference (P5) correctly compares uploaded CSV to AR; BOTH synthesis (P6) draws from all three sources without falling into stub language; save persists; Pass 5 checkbox successfully moves source session |
| 🟡 Partial | Charts work, individual retrievals work, but BOTH synthesis (P6) is shallow — lists what's there without reasoning across; OR P5 cross-reference fails to find matches |
| ❌ Fail | Upload PDF doesn't ingest; OR P6 inherits a "no uploaded data" stub from broken SQL (this is what the stabilization fix should prevent); OR save doesn't persist |

### Pitch value
This is the strongest "complete client workflow" sim. One client
request → research across three sources (books, IRS, client's own
records) → defensible recommendation → drafted client response →
organized for follow-up. **This is the best opening simulation for
the demo video.**

---

# Sim 2 — Vendor Payment Strategy Under Cash Constraint

**Topic on completion:** *Vendor Follow-up — BlueRiver April cash*
**Estimated duration:** 9 prompts + organize. ~12-15 minutes.

### Business situation

Same client (BlueRiver Consulting). Tight cash month. Jennifer
forwards two things to her accountant: (1) the Oracle dunning email
demanding payment of an overdue $15,000 invoice, and (2) BlueRiver's
own bank statement showing limited cash. She asks her accountant to
figure out which vendor payments to prioritize, which to defer, and
draft response language for Oracle.

### Workflow map (7 steps)

| Step | Sim activity |
|---|---|
| Ask | Prompts 1, 2 — read both uploads |
| Retrieve | Prompts 3, 4, 5 — vendor data, internal verification, IRS/policy check |
| Visualize | Prompts 3, 6 — bar chart (vendor exposure) + line chart (cash projection) |
| Save | Prompt 8 — save strategy |
| Organize | Step 9 — create topic, move with source session |
| Recall | (downstream) |
| Follow up | Prompt 7 — Oracle response draft + internal action plan |

### Required uploads
- `oracle_invoice_followup_email.pdf` — **already created**
- `bluerver_bank_statement.csv` — weekly cash position, 4-8 weeks

### Prompt sequence

| # | Prompt | Expected route | Output |
|---|---|---|---|
| 1 | (Upload Oracle PDF) "Summarize what Oracle is claiming." | RAG (upload) | Summary of $15K, 57 days overdue |
| 2 | (Upload bank CSV) "Summarize our cash position from the bank statement." | SQL on upload | Cash by week with current balance |
| 3 | "Show our overdue AP balances by vendor as a bar chart, ranked descending." | SQL + bar chart | Vendor exposure ranking |
| 4 | "Find any Oracle Corporation invoices in our AP — confirm the dates, amount, and current status." | SQL | INV-038 cross-reference |
| 5 | "What does the IRS or general accounting guidance say about prioritizing accounts payable when cash is constrained, and any compliance considerations?" | RAG | General guidance with honest limits |
| 6 | "Plot our weekly cash position from the upload as a line chart so I can see the trend." | SQL on upload + line chart | Cash trend over time |
| 7 | "Given our cash position, the overdue AP exposure, and the Oracle claim — which vendor payments should we prioritize this month, and which can wait? Draft a brief Oracle response and an internal action list for Jennifer." | **BOTH** | Synthesis combining cash + AP + Oracle claim + guidance |
| 8 | (💾 Save) "Vendor payment strategy — April" | save | Save persists |
| 9 | Create topic "Vendor Follow-up — BlueRiver April cash" → check "Also move source session" | topic + Pass 5 | Topic + session move |

### Pass / partial / fail

| Outcome | Criteria |
|---|---|
| ✅ Pass | Oracle PDF + bank CSV both ingest; cross-reference confirms INV-038 (Priority 2 stabilization makes this work even if SQL has a hiccup); both charts (bar + line) render cleanly; BOTH synthesis (P7) produces a real prioritization with named vendors, not a generic deferral list; Pass 5 checkbox works |
| 🟡 Partial | Cross-reference fails on Oracle but RAG fallback still produces a usable answer (this is the "graceful degradation" story from Phase 6 Sim 4); OR P7 synthesis is shallow |
| ❌ Fail | Upload fails; OR P7 produces a stub-contaminated answer; OR cash trend chart shows wrong data |

### Pitch value
This is the **scenario that distinguishes CASSIA from any chatbot**:
client forwards two documents → the accountant uses both alongside
the books → produces a defensible strategy + drafted client
response. The "received an email, didn't leave the chat" story is
told most clearly here.

---

# Sim 3 — Payroll Compliance Response to IRS Notice

**Topic on completion:** *IRS/Agency Notice — CP220 Q1 payroll*
**Estimated duration:** 9 prompts + organize. ~15 minutes.

### Business situation

An IRS notice arrives at the client's office (mock CP220 — failure
to deposit payroll taxes timely). Jennifer forwards the notice to
her accountant. The accountant uploads the notice, pulls the payroll
register, cross-checks against IRS deposit rules, and produces a
remediation plan plus a draft response to the IRS.

### Workflow map (7 steps)

| Step | Sim activity |
|---|---|
| Ask | Prompt 1 — read the notice |
| Retrieve | Prompts 2, 3, 4 — payroll history, IRS rules, gap analysis |
| Visualize | Prompts 2, 5 — line chart + bar chart |
| Save | Prompt 8 — save compliance review |
| Organize | Step 9 |
| Recall | (downstream) |
| Follow up | Prompts 6, 7 — IRS response draft + client guidance |

### Required uploads
- `irs_notice_cp220.pdf` — mock notice referencing Q1 2026 payroll deposits
- `payroll_register_q1.csv` — quarterly payroll detail (could be derived from GL)

### Prompt sequence

| # | Prompt | Expected route | Output |
|---|---|---|---|
| 1 | (Upload IRS notice PDF) "Read this IRS notice and tell me what they're alleging and what they want from us." | RAG (upload) | Summary of CP220 allegation: missed Q1 deposits |
| 2 | (Upload payroll CSV) "Show our payroll tax deposit history as a line chart, by deposit period." | SQL on upload + line chart | Deposits over time line |
| 3 | "What does the IRS require for payroll tax deposit schedules and what are the penalty tiers for late deposits?" | RAG | Pub 15 deposit schedule + penalty tiers |
| 4 | "Looking at the deposits in our payroll register against what the IRS says we should have done, what did we miss and roughly how much penalty are we looking at?" | **BOTH** | Synthesis comparing actual vs required (this is the exact failure mode from Phase 6 Sim 2 — stabilization should fix it) |
| 5 | "Show the gap between required and actual deposits as a bar chart, by month." | SQL + bar chart | Gap visualization |
| 6 | "Draft a response to the IRS notice acknowledging receipt, requesting reconsideration where appropriate, and outlining the corrective steps we'll take." | Conversational | IRS-ready response draft |
| 7 | "Draft a separate note for Jennifer summarizing what happened, what the exposure is, and what she needs to do internally to fix the process going forward." | Conversational | Client-internal note |
| 8 | (💾 Save) "CP220 response and remediation — Q1" | save | Save persists |
| 9 | Create topic "IRS/Agency Notice — CP220 Q1 payroll" → Pass 5 checkbox | topic + Pass 5 | Topic with save + session |

### Pass / partial / fail

| Outcome | Criteria |
|---|---|
| ✅ Pass | Both uploads ingest; both charts (line + bar) render with correct measure columns only; P4 BOTH synthesis successfully compares actual vs required without falling into stub or error language; P5 gap chart visualizes the difference clearly; IRS response and client note both produced and saved |
| 🟡 Partial | Synthesis (P4) is structurally sound but misses one or two specific deposit gaps; OR gap chart shows correct shape but mislabeled |
| ❌ Fail | P4 says "no uploaded data" or echoes a SQL execution error (stabilization fix prevents this); OR IRS response includes fabricated penalty amounts not in the retrieved content |

### Pitch value
This is the **agency-notice workflow scenario** that the
positioning explicitly highlights. The Sim demonstrates the
architecture pattern: *upload notice → ask questions → connect to
books → save conclusion → organize by issue*. Worth filming as a
demo because it maps directly to a workflow accountants do all the
time and currently handle entirely outside any AI tool.

**Critical for stabilization verification:** P4 is the exact failure
mode from Phase 6 Sim 2. If P4 produces a clean synthesis here, the
Priority 2 stabilization fix is confirmed working in production.

---

# Sim 4 — Quarterly Continuity Review (the workspace identity sim)

**Topic on completion:** *Client Review — BlueRiver Q1 2026*
**Estimated duration:** 11 prompts + logout/login + organize. ~18-20 minutes.

### Business situation

It's now Q2 2026. Quarter-end. Jennifer has asked for a quarterly
client review covering Q1 performance, year-to-date trends, and key
follow-ups. The accountant logs back into CASSIA after a few days
away, recalls saved findings from Sims 1, 2, 3, pulls current data,
compares against the client's revenue forecast, and produces a
quarterly memo. This sim is **the proof of the workspace identity
claim** — work survives time and is findable by meaning.

### Workflow map (7 steps)

| Step | Sim activity |
|---|---|
| Ask | After logout/login, P1 — quarterly review request |
| Retrieve | P2, 3 — current revenue + forecast upload |
| Visualize | P2, P4 — bar + line |
| Save | P9, P10 — saves |
| Organize | Step 11 |
| **Recall** | P5, P6, P7 — recall AR, vendor, payroll saves (the multi-save recall) |
| Follow up | P8 — quarterly memo draft |

### Pre-requisites
Sims 1, 2, 3 must have run first so their saves exist in Core.

### Required uploads
- `q4_2025_board_memo.pdf` — one-page prior-quarter memo for context
- `revenue_forecast_2026.csv` — twelve-month forecast (or four-quarter)

### Prompt sequence

#### Phase A — Logout/login cycle

| Step | Action |
|---|---|
| A1 | Log out via header menu |
| A2 | Wait ~30 seconds (represents "a few days later") |
| A3 | Log back in; verify sessions and topics restored |
| A4 | Verify in My Core: AR, Vendor, IRS Notice topics all present |

#### Phase B — Quarterly review session

Create a new session: "Q1 2026 quarterly review — BlueRiver"

| # | Prompt | Expected route | Output |
|---|---|---|---|
| 1 | (Upload board memo PDF) "Read Jennifer's Q4 2025 board memo so we have context for the Q1 2026 review." | RAG (upload) | Q4 context summary |
| 2 | "Show our Q1 2026 revenue by service line as a bar chart." | SQL + bar chart | Revenue ranking |
| 3 | (Upload forecast CSV) "Compare our actual Q1 revenue against the Q1 forecast — show the variance by service line." | SQL on upload + table | Actual vs forecast variance |
| 4 | "Plot the quarter-over-quarter revenue trend from Q4 2025 to Q1 2026 as a line chart." | SQL + line chart | QoQ trend |
| 5 | "Recall what I saved about AR collection risk." | **Core Recall** | Returns Sim 1 save |
| 6 | "Recall what I saved about vendor payment strategy." | **Core Recall** | Returns Sim 2 save |
| 7 | "Recall what I saved about payroll compliance or the IRS notice." | **Core Recall** | Returns Sim 3 save |
| 8 | "Combine these three recalled saves plus the current quarter's revenue and variance into a brief quarterly memo for Jennifer. Cover: revenue performance, vendor exposure status, AR collection status, payroll compliance status." | **BOTH** synthesis across multi-source | Quarterly memo draft |
| 9 | "What should be the top three priorities for Jennifer in Q2 based on everything we just reviewed?" | Conversational | Prioritization |
| 10 | (💾 Save) "Q1 2026 quarterly memo — BlueRiver" | save | Save persists |
| 11 | Create topic "Client Review — BlueRiver Q1 2026" → Pass 5 checkbox | topic + Pass 5 | Topic with save + session |

### Pass / partial / fail

| Outcome | Criteria |
|---|---|
| ✅ Pass | Logout/login cycle clean; all three prior topics and saves visible after re-login; all three Core Recall prompts (P5, P6, P7) return the correct save with high relevance; P8 BOTH synthesis successfully weaves the three recalled findings with current data into a coherent memo; both charts render cleanly |
| 🟡 Partial | Logout/login works but one Core Recall returns a less-relevant save (similarity threshold issue); OR P8 synthesis is structurally sound but doesn't reference all three saves equally |
| ❌ Fail | Logout breaks persistence; OR a Core Recall returns nothing for one of the three; OR P8 hallucinates content not in the recalled saves |

### Pitch value
**This is the sim that proves CASSIA is a workspace, not a chatbot.**
A chatbot has no memory across logouts. A workspace remembers
sessions, topics, saves, and the relationships between them, and can
recall any of them by meaning. P5-P8 is the entire pitch in four
prompts. Worth keeping the demo video short and ending on this.

---

## Execution sequence

Recommended order, with rough time budgets:

| Phase | Activity | Time |
|---|---|---|
| 1 | Ship stabilization patches (Priorities 1, 2-expanded, 3, optional 4) | 3-4 hours |
| 2 | Smoke test: server up, login works, basic SQL + RAG queries fire cleanly | 15 min |
| 3 | Generate the 7 new uploads (PDFs + CSVs) in one batch | 30-45 min |
| 4 | Run Sim 1 → capture screenshots + Sim 1 verdict | 30 min |
| 5 | Run Sim 2 → capture + verdict | 30 min |
| 6 | Run Sim 3 → capture + verdict | 30 min |
| 7 | Run Sim 4 → capture + verdict (most important — workspace identity) | 30 min |
| 8 | If anything regresses post-stabilization, narrow patch + retest | reserve buffer |
| 9 | Final journal write-up draws from Sims 1-4 evidence + screenshots | next session |

**Total active time: ~6-7 hours of focused work to ship stabilization
+ generate uploads + run all four sims with evidence capture.**

---

## What to flag if it surfaces

These are pre-known risks worth watching for during execution:

1. **Cross-table SQL queries with schema mismatches** (Phase 6 Sim 4
   finding). Sim 2 P4 and Sim 1 P5 both involve cross-table or
   upload-vs-internal comparisons. The expanded Priority 2
   stabilization should catch resulting errors and produce a clean
   fallback. If it doesn't, **note and continue** rather than
   patching mid-sim.

2. **Core Recall hang** (Phase 6 Sim 3 finding). Sim 4 has three
   consecutive Recall prompts. If any hang, the optional Priority 4
   timeout fix would have addressed it. Without that fix, just
   refresh and retry; document as a known issue.

3. **BOTH synthesis ceiling** (Phase 6 Sim 2 finding). Sim 1 P6, Sim 2
   P7, Sim 3 P4, Sim 4 P8 all exercise BOTH synthesis with
   stub-prevention. If any produce confused output, the Priority 2
   stabilization fix didn't fully cover that pattern — note and
   continue.

4. **Multi-statement SQL errors** (Phase 6 Sim 5 finding). If any
   prompt produces "only one SQL statement can be executed",
   stabilization Priority 2 should have caught it. Same posture:
   note, continue, capture for follow-up patch.

---

## What this set proves about CASSIA, in pitch terms

If all four sims pass cleanly, the demo can claim each of these
truthfully:

- **CASSIA handles the full accountant workflow without leaving the
  chat** — uploads, queries, charts, regulations, synthesis, saves,
  organization, recall, drafted client communications. (Demonstrated
  in every sim.)
- **Work survives across time and is findable by meaning** (Sim 4 Phase A + P5-P7).
- **CASSIA combines uploaded client documents with internal accounting
  data fluidly** (Sims 1, 2, 3 all do this with PDF + CSV +
  internal DB).
- **CASSIA produces defensible recommendations grounded in both data
  and regulations** (BOTH-route synthesis in every sim).
- **CASSIA admits scope honestly** — graceful fall-through visible at
  least once per sim either through visible route badges (no mystery
  routing) or RAG not-found behavior when the corpus doesn't cover
  the question.
- **CASSIA organizes accounting work like an accountant already
  organizes their inbox** — every sim ends with a named topic that
  reads like a real client issue, not a generic folder.

That's the entire pitch demonstrated by evidence, not claim. Four
simulations. Roughly an hour of execution time. The four topics that
remain in Core afterward become the screenshots that anchor every
slide in the pitch deck.

---

## What I need from you to proceed

1. **Confirm the four-sim shape works** for you — scope, scenarios,
   timing
2. **Confirm the locator script + stabilization patches go first**
   (Sims should run on the patched system, not the current one)
3. **Approval to draft the 7 new uploads** in one batch after
   stabilization ships — I can do them all in one session

Once those are confirmed:
- Next turn: locator script
- Turn after: stabilization patch package (3 priorities + optional 4)
- Then: upload generation batch
- Then: you run Sims 1-4 with evidence capture
- Then: journal session
