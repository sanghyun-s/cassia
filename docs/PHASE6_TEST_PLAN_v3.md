# CASSIA — Phase 6 Business Case Simulation Test Plan (v3)

**Version 3** — supersedes v2. The v2 plan was designed without direct
inspection of the demo CSV files. v3 incorporates findings from the
full data review:

- **Sim 2 pivoted** from "find late payroll deposits" to "find the
  missing payroll deposits" — the GL shows accruals without any
  corresponding IRS deposit transactions, which is itself a real-looking
  compliance flag. Pivoted scenario is more honest and more interesting
  than the original.
- **Sim 4 anchored** to Oracle Corporation as the named vendor in the
  mock email PDF (matches existing overdue AP record INV-038, $15,000,
  57 days overdue).
- **Sim 3 flagged** for a possible Q1-vs-YTD discrepancy between the
  pre-existing Core save ($101,491) and a fresh query of true Q1
  (Jan+Feb+Mar = $75,556).
- **`journal_entries.csv` flagged as orphaned** — uses account codes
  inconsistent with `chart_of_accounts.csv` and the rest of the demo.
  Prompts now reference "general ledger" explicitly to avoid the LLM
  routing to the orphaned table.

Everything else from v2 carries forward.

---

## What we found inspecting the demo data

A short summary of what's actually in each CSV — kept here as a journal
reference (the journal can quote from this when describing how Phase 6
was scoped):

| File | Status | What it supports |
|---|---|---|
| `chart_of_accounts.csv` | ✅ Canonical | 59 accounts, full subtype/description coverage |
| `general_ledger.csv` | ✅ Strong | 139 entries Jan-Apr 2026, double-entry, named clients/vendors, references |
| `balance_sheet.csv` | ✅ Strong | 4 months + prior year comparison |
| `profit_loss.csv` | ✅ Strong | Monthly + YTD + prior-year-Q1, EBITDA, margins |
| `revenue.csv` | ✅ Strong | 53 transactions, payment method, status |
| `accounts_receivable.csv` | ✅ Strong | 14 open invoices, 4 aging buckets, billing partners, dispute notes |
| `accounts_payable.csv` | ✅ Strong | 45 invoices, 10 overdue with named vendors |
| `journal_entries.csv` | ⚠️ Orphaned | Account codes don't match chart_of_accounts; vendors don't match AP |

**Specific findings worth knowing before testing:**

1. **Payroll tax deposits don't exist in the books.** Only one
   withholding accrual recorded (Jan 15, $8,653). No subsequent
   accruals and no IRS deposit transactions. Balance sheet shows the
   liability constant at $-8,653 from Jan through April. This is the
   Sim 2 pivot foundation.

2. **AP has 10 named overdue vendors** totaling $44,780. Largest is
   Oracle Corporation at $15,000 / 57 days overdue (INV-038). This
   anchors the Sim 4 mock PDF and Sim 6 prioritization analysis.

3. **AR has rich dispute/collection notes** in the `notes` column —
   e.g., "Disputed invoice - services rendered", "Non-responsive -
   collections engaged", "bad debt likely". This gives Sim 1's client-
   facing summary substantive material to draw from.

4. **The pre-existing "Q1 2026 Net Income" save shows $101,491**, which
   is actually the YTD-through-April figure. True Q1-only is $75,556.
   Worth watching in Sim 3.

---

## Coverage matrix

How the six simulations together hit every capability:

| Capability | Sim 1 | Sim 2 | Sim 3 | Sim 4⭐ | Sim 5⭐ | Sim 6 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| Login / logout | | | | ✓ | ✓ | |
| Persistent sessions | | | | | ✓ | |
| Topic-grouped sidebar | ✓ | ✓ | | ✓ | ✓ | |
| SQL answers | ✓ | ✓ | ✓ | ✓ | | ✓ |
| RAG answers | ✓ | ✓ | | | | |
| BOTH / hybrid synthesis | ✓ | ✓ | | ✓ | ✓ | ✓ |
| Charts | ✓ | | ✓ | | | ✓ |
| Upload (CSV/Excel/PDF) | | | | ✓ | | |
| Save to Core | ✓ | ✓ | | ✓ | | ✓ |
| Topic organization | ✓ | ✓ | | ✓ | ✓ | |
| Core Recall (single save) | | | ✓ | | | ✓ |
| Core Recall (multi-save) | | | | | ✓ | |
| Graceful no-match behavior | ✓ | ✓ | | | | |
| Pass 5 "Also move source session" | | | | ✓ | | |

⭐ = advanced showcase per spec.

---

## Pre-test data preparation

**Required:**

1. **Mock vendor email PDF for Sim 4.** Anchored to **Oracle
   Corporation, INV-038, $15,000, invoice date 2026-02-01, due
   2026-03-03, currently 57 days overdue (Software/Cloud)**. The PDF
   should look like a forwarded client email referencing this specific
   invoice and amount — see Sim 4 below for the content spec. I can
   draft the PDF content when you're ready to run Sim 4.

**Optional cleanup:**

2. **Decide what to do with `journal_entries.csv`.** It's inconsistent
   with the rest of the demo data and could confuse CASSIA on certain
   prompts. Three options:
   - **Leave it** (Phase 6 prompts explicitly reference "general ledger"
     to route around it). My recommendation for now.
   - **Drop it** from the `accounting.db` build (modify `sql/phase1_load.py`).
   - **Rebuild it** to be consistent with chart_of_accounts + GL.

   If you leave it, all Phase 6 prompts that reference transactions
   say "general ledger" or "GL" explicitly. Sim prompts below already
   do this.

**Pre-flight checks before starting:**

- [ ] Verify Pub 15 in ChromaDB returns content on a quick recon
      query ("What does the IRS say about payroll tax deposits?")
- [ ] Confirm the existing "Q1 2026 Net Income" save is in My Core
      (needed for Sim 3)
- [ ] Cookie state: log out and log back in once before starting

---

## Simulation 1 — AR Collection & Recordkeeping Risk

### Business situation
A client is preparing for month-end close and asks their accountant
which customer invoices are overdue, which balances need collection
follow-up, and what documentation they should keep to support their
receivables position. The accountant uses CASSIA to pull the AR data,
look up IRS recordkeeping guidance, and produce a client-facing summary.

### Sources / capabilities used
SQL pipeline over `accounting.db` (accounts_receivable); chart
auto-rendering; RAG pipeline over IRS Pub 15; possible BOTH-route
synthesis; Save to Core; topic organization.

### Data context
14 open invoices in AR data, spread across 4 aging buckets (Current /
31-60 / 61-90 / 90+). 5 invoices are at 75+ days overdue including 3
in the 90+ bucket. The `notes` column has rich situational text:
"Disputed invoice", "Partial collect - bad debt likely",
"Non-responsive - collections engaged". Use this richness in the
summary prompt.

### Prompt sequence (5 prompts + organize)

| # | Prompt | Expected capability |
|---|---|---|
| 1 | "Which customer invoices are currently past due? Show customer, amount, due date, days overdue, and any notes on each." | SQL |
| 2 | "Show overdue balances by customer as a bar chart, ranked from highest to lowest." | SQL + chart |
| 3 | "What does the IRS say about recordkeeping requirements for receivables and supporting documentation for collections?" | RAG (likely partial-match — see risk flag) |
| 4 | "Summarize the collection risk and recommend next steps the client should take. Frame this as a brief client communication. Include the most concerning specific accounts by name." | Synthesis (BOTH or conversational) |
| 5 | (💾) Save the answer as "AR collection risk" | save |
| 6 | In My Core, create topic "Client Advisory — Q1 2026" and move the save there | topic create + move |

### Expected output

- Prompt 1: Table of overdue invoices. Most concerning by data: KLM
  Restaurants (140 days, $4,800), Union Pacific Foods (116 days,
  $2,800 unpaid), Titan Wholesale (112 days, $9,400 disputed), Liberty
  Insurance (75 days, $14,000 partial), NorthStar Energy (75 days,
  $19,500).
- Prompt 2: Bar chart with customers ranked descending by overdue
  balance.
- Prompt 3: Pub 15 content about employment tax recordkeeping (4-year
  retention rule). The question is whether CASSIA acknowledges this is
  employment-tax-specific and not AR-specific, or extends the principle
  honestly.
- Prompt 4: Client-facing summary that names specific accounts and
  draws from the notes column. Should mention dispute resolution for
  Titan Wholesale, collections strategy for KLM Restaurants, partial-
  payment follow-up for Liberty Insurance / Union Pacific Foods.
- Save lands in Core under the new topic.

### Pass / partial / fail

| Outcome | Criteria |
|---|---|
| ✅ Pass | SQL queries return correct overdue invoices; chart renders descending; prompt 3 returns Pub 15 content **with honest framing** about scope; prompt 4 references specific accounts by name and pulls from the notes column; save persists |
| 🟡 Partial | SQL/chart work but prompt 3 hallucinates AR-specific IRS guidance not in Pub 15, OR prompt 4 is too generic to be useful (no specific account names) |
| ❌ Fail | SQL pipeline fails; OR save doesn't persist; OR prompt 3 returns confidently fabricated content attributed to Pub 15 |

### What this scenario tests about CASSIA
The everyday client-advisory workflow: data lookup, documentation
guidance, synthesized recommendation, persisted finding. *Can an
accountant use CASSIA for routine client work and end up with a
defensible, organized client deliverable that names specific accounts?*

### Risk flag
Prompt 3 is intentionally on the edge of Pub 15's scope. Pub 15 has a
recordkeeping section but it's about employment tax records, not AR
records. The graceful-behavior question is whether CASSIA
acknowledges this scope boundary. This is the most important
reliability observation Phase 6 can produce.

---

## Simulation 2 — Missing Payroll Tax Deposits (pivoted)

### Business situation
A client is worried about their payroll tax compliance — they're not
sure their books are properly tracking IRS deposit obligations. The
accountant uses CASSIA to inspect the payroll-related activity in the
general ledger, look up the IRS rules for what should be there, and
identify gaps.

### Why this scenario was pivoted from v2
v2's Sim 2 was designed to find "deposits that look late." In the
actual data, **there are no payroll tax deposits at all** — only one
withholding accrual (Jan 15, $8,653) and zero subsequent activity on
the Accrued Payroll Taxes account. So Sim 2 pivots to a stronger
scenario: find what's missing, not what's late. CASSIA is being used
as a review tool, not a search tool.

### Sources / capabilities used
SQL over `accounting.db` (general_ledger specifically); RAG over IRS
Pub 15; conversational synthesis combining the two; Save to Core;
topic organization.

### Data context
GL has 4 months of semi-monthly payroll runs (Jan 15, Feb 15, Mar 15,
Apr 15) showing salary expense and net pay disbursement. Only Jan 15
includes a $8,653 credit to Account 2020 (Accrued Payroll Taxes) for
withholding. There is no debit to 2020 anywhere — meaning no deposit
to IRS is recorded. Balance sheet confirms: the liability stays at
$-8,653 constant from Jan through April.

### Prompt sequence (4 prompts + organize)

| # | Prompt | Expected capability |
|---|---|---|
| 1 | "Show me the payroll-related activity in our general ledger for Q1 2026 — payroll runs, salary expenses, accrued payroll tax withholdings, and any IRS deposit transactions." | SQL |
| 2 | "What does the IRS require for payroll tax deposit schedules and deposit deadlines per Pub 15?" | RAG |
| 3 | "Based on what's actually in our books and what the IRS requires, what looks wrong or missing in how we're tracking payroll taxes?" | Synthesis (BOTH or conversational) |
| 4 | "Draft a short note to the client explaining what we found and what they need to verify or correct." | Conversational |
| 5 | (💾) Save as "Payroll tax exposure" | save |
| 6 | Create topic "Payroll Compliance" and move the save there | topic create + move |

### Expected output

- Prompt 1: Table of GL entries tagged as payroll activity. Should
  surface: 4 semi-monthly salary expense pairs (Jan 15, Feb 15, Mar
  15, Apr 15), the one withholding accrual on Jan 15 ($8,653 credit to
  Account 2020), and the payroll cash disbursements. Should NOT
  surface any debits to Account 2020 (because there aren't any).
- Prompt 2: Pub 15 content on deposit schedules — monthly schedule
  depositors must deposit by the 15th of the following month;
  semi-weekly depositors have varying deadlines based on payday day-of-
  week. Penalty tiers for late deposits.
- Prompt 3: **The critical synthesis test.** CASSIA should ideally
  notice:
  - The Jan 15 accrual of $8,653 was never deposited — under monthly
    schedule that should have been deposited by Feb 17 (15th was a
    Sunday)
  - No subsequent semi-monthly accruals are recorded (Feb 15, Mar 15,
    Apr 15 entries are missing the 2020 credit)
  - The liability on the balance sheet has stayed constant, confirming
    no deposit activity
  - Whether or not CASSIA catches all three is fine; even catching one
    correctly is a meaningful finding.
- Prompt 4: Client-facing note describing what was found, what should
  be verified (whether the deposits actually happened but weren't
  recorded vs. whether deposits really were skipped), and the IRS
  penalty exposure if deposits are genuinely missing.

### Pass / partial / fail

| Outcome | Criteria |
|---|---|
| ✅ Pass | SQL surfaces the actual payroll GL entries (including the lonely Jan 15 accrual); RAG returns correct Pub 15 deposit rules with citations; **prompt 3 correctly notices the missing deposit activity** (at least the absence of any debit to Accrued Payroll Taxes); prompt 4 produces a defensible client note |
| 🟡 Partial | SQL and RAG both work but prompt 3 doesn't catch the missing deposit pattern — just summarizes what's there without flagging what's missing |
| ❌ Fail | RAG hallucinates penalty rules; OR SQL returns wrong figures; OR prompt 3 invents deposit transactions that don't exist; OR save doesn't persist |

### What this scenario tests about CASSIA
Whether CASSIA can be used as a review tool — finding what's NOT in
the books when checked against what SHOULD be there per regulations.
This is a stronger advisory capability than "summarize what's there."
*Can CASSIA catch a real compliance issue by combining what the books
show with what regulations require?*

### Risk flag
This is the most cognitively demanding scenario for CASSIA's LLM.
Listing what's present is easy; noticing what's absent requires the
model to compare two retrieved contexts and identify a gap. If
prompt 3 fails (lists what's there without flagging what's missing),
that's an honest journal finding about CASSIA's analytical ceiling
— and it would be worth noting that the workflow could be saved by
asking "what's missing from this list given the IRS rules?" as a
follow-up.

---

## Simulation 3 — Revenue by Service Line + Management Summary

### Business situation
A client wants to understand which service lines are driving revenue
and whether their Q1 performance aligns with the net income story
already captured in CASSIA from prior work. The accountant pulls the
current service-line breakdown, recalls the prior Q1 net income save,
and writes a short management summary.

### Sources / capabilities used
SQL + chart auto-rendering; **Core Recall (single save, retrieves
existing data — not new test data created in this Phase 6 run)**;
conversational synthesis.

### Data context
Revenue table has 53 transactions spanning Oct 2025 - Apr 2026.
P&L has service-line breakdowns. The pre-existing "Q1 2026 Net Income"
save shows $101,491 — which, looking at the P&L data, is actually the
**YTD-through-April** total ($18,981 + $21,983 + $34,592 + $25,935 =
$101,491). True Q1-only (Jan+Feb+Mar) is $75,556.

### Prompt sequence (5 prompts, save optional)

| # | Prompt | Expected capability |
|---|---|---|
| 1 | "Show revenue by service line as a bar chart, ranked from highest to lowest." | SQL + chart |
| 2 | "Which service lines are strongest and weakest? What's the gap?" | Conversational + SQL context |
| 3 | "Recall what I saved about Q1 net income." | **Core Recall** |
| 4 | "Compare the saved net income note with current service-line performance — what's the story for management?" | Synthesis |
| 5 | "Write a short management summary I can send to the controller." | Conversational synthesis |

### Expected output
- Prompt 1: Bar chart with Consulting Revenue highest ($345,500),
  Audit ($171,000), Accounting ($68,200), Tax Prep ($16,400),
  Bookkeeping ($9,400), Payroll and CFO Advisory at $0.
- Prompt 2: Plain-English ranking noting Payroll Services and CFO
  Advisory both at zero in Q1 (worth investigating).
- Prompt 3: **Core Recall fires** — should retrieve the prior "Q1
  2026 Net Income" save showing $101,491 with title, date, similarity
  score, and clickable source-session link.
- Prompt 4: Multi-source synthesis. **Watch for the $101,491 vs
  $75,556 discrepancy:** if a fresh SQL query in prompt 4 produces
  $75,556 while the recalled save says $101,491, CASSIA should either
  notice the discrepancy or pick one. Either behavior is informative.
- Prompt 5: A 2-4 paragraph management summary suitable for the
  controller.

### Pass / partial / fail

| Outcome | Criteria |
|---|---|
| ✅ Pass | Chart renders; prompt 3 routes to Core Recall (not SQL or RAG) and returns the existing Q1 net income save; prompt 4 references both the saved content and current data meaningfully; prompt 5 is coherent and management-appropriate |
| 🟡 Partial | Core Recall fires but doesn't surface the most relevant save (similarity threshold too tight); OR synthesis is shallow; OR the $101,491 vs $75,556 discrepancy goes unnoticed but the summary is still coherent |
| ❌ Fail | Prompt 3 doesn't route to Core Recall at all; OR Recall returns hallucinated content not in any save |

### What this scenario tests about CASSIA
The architecturally distinctive claim — *current data + prior saved
knowledge fused into one workflow*. This scenario uses the user's
**actual existing saves** as part of the test, not new test data. If
this works, it proves the memory-database identity claim with real
artifacts.

### Risk flag — Q1 vs YTD discrepancy
The pre-existing save's $101,491 figure is YTD-through-April, not
Q1-only. If a fresh query in this session produces $75,556 for Q1, the
two figures will conflict. This is a real-world ambiguity test — does
CASSIA reconcile, defer to recall, or surface the conflict?

### Design principle established
This scenario establishes a Phase 6 design principle: **verify the
workspace claim using the actual workspace.** Don't always create new
test data — sometimes the test IS that prior work survives and is
findable.

---

## Simulation 4 ⭐ — Uploaded Client Email/PDF + Vendor Follow-up

This is the first advanced showcase: external business document
connecting to internal accounting data with full save/organize follow-up.

### Business situation
A client forwards their accountant a PDF copy of an email exchange
with Oracle Corporation. Oracle is claiming an invoice is unpaid; the
client wants their accountant to verify against the books and prepare
a response.

### Sources / capabilities used
PDF upload; uploaded PDF RAG (session-scoped, user-isolated); SQL on
`accounting.db` (accounts_payable); Save to Core; topic creation; the
**Pass 5 "Also move source session" checkbox**.

### Data context — anchor for the mock PDF
**AP record INV-038:** Oracle Corporation, invoice date 2026-02-01,
due 2026-03-03, amount $15,000, currently 57 days overdue, category
Software/Cloud. Status: Overdue, unpaid.

### Mock PDF content spec
The mock email PDF should reference:
- Vendor: **Oracle Corporation**
- Invoice number: any plausible (e.g., "ORCL-2026-1247")
- Amount: **$15,000**
- Invoice date: roughly **February 1, 2026**
- A tone of concern from Oracle ("We haven't received payment for the
  attached invoice... please advise")
- A line suggesting the client passed it to their accountant for review

I can draft the full PDF text content when you're ready to run Sim 4 —
just say the word and I'll produce a paste-into-PDF-converter ready
text block.

### Prompt sequence (5 prompts + organize)

Set up:
- Log in as SanghyunAcct (or confirm logged in)
- Create a new session titled "Vendor follow-up — Oracle email"
- Upload the prepared mock Oracle email PDF

| # | Prompt | Expected capability |
|---|---|---|
| 1 | "Read this uploaded email and summarize what Oracle is asking about." | Uploaded PDF RAG |
| 2 | "Find any Oracle Corporation invoices or payments in our accounting data — when were they invoiced, when were they due, and what's the current status?" | SQL on AP |
| 3 | "Based on what we found, does Oracle's claim look correct? What should we tell the client?" | Conversational synthesis using PDF + SQL context |
| 4 | "Draft a short response the client could send back to Oracle, with internal next steps for the accountant." | Conversational |
| 5 | (💾) Save the conclusion | save |
| 6 | Move the save to a new topic "Vendor Follow-up", **with the "Also move source session" checkbox CHECKED** | topic + Pass 5 polish |

### Expected output
- Upload: file ingests cleanly (chunks created, "Files in this
  session" indicator visible)
- Prompt 1: Summary of Oracle's email — they're claiming non-payment
  of a $15,000 invoice from early February.
- Prompt 2: SQL result showing INV-038, Oracle Corporation, invoice
  date 2026-02-01, due 2026-03-03, $15,000, status Overdue, 57 days
  overdue, payment_date NULL. Confirms Oracle's claim is correct.
- Prompt 3: Synthesis confirming Oracle's claim is accurate — the
  invoice is genuinely overdue 57 days. Recommendation should be to
  pay it (or dispute formally if there's a reason).
- Prompt 4: Client-ready draft acknowledging the invoice and
  committing to payment or a specific follow-up timeline.
- Save: lands in Core; topic "Vendor Follow-up" created; **the source
  session also moves into the same topic group in the sidebar** (Pass
  5 checkbox ripple visible).

### Pass / partial / fail

| Outcome | Criteria |
|---|---|
| ✅ Pass | PDF ingests; uploaded RAG retrieves Oracle-relevant content; SQL finds INV-038 with correct details; prompt 3 correctly confirms the claim against the AP record; prompt 4 produces a usable client draft; save persists; **Pass 5 checkbox successfully ripples the source session into the new topic with sidebar refresh** |
| 🟡 Partial | Document ingests and summarizes correctly but SQL misses the AP record (vendor name match issue); OR Pass 5 checkbox works but sidebar doesn't refresh; OR save works but topic creation fails |
| ❌ Fail | Upload doesn't ingest; OR uploaded RAG retrieves unrelated content; OR the source session ripple breaks |

### What this scenario tests about CASSIA
The full external-document → internal-data → save workflow that
distinguishes CASSIA from generic chat tools or standalone Q&A bots.
*Can an accountant take a client-forwarded document, connect it to the
books inside CASSIA, and end up with an organized follow-up plan
without ever leaving the chat?*

---

## Simulation 5 ⭐ — Logout/Login + Core Memory Continuity

The second advanced showcase: persistence and recall across an
explicit auth boundary, using saves created earlier in Phase 6.

### Business situation
A few days after the prior work, the user returns to CASSIA. They
expect all prior sessions, topics, and saved findings to still be
there. They log back in, ask CASSIA to recall multiple prior findings
across different topics, and have CASSIA synthesize them into a brief
client update — proving that Core works as cross-session memory, not
just session history.

### Sources / capabilities used
Authentication (logout + login); cookie persistence; full session
restoration; topic-grouped sidebar; **multi-save Core Recall across
different topics**; conversational synthesis.

### Prerequisites
Sims 1, 2, 3 must have run first so the following saves exist:
- "AR collection risk" (Sim 1, in topic "Client Advisory — Q1 2026")
- "Payroll tax exposure" (Sim 2, in topic "Payroll Compliance")
- The existing "Q1 2026 Net Income" save (pre-existing, retrieved in
  Sim 3)

### Prompt sequence — Phase A (current session, simulated end-of-day)

| # | Action | Expected behavior |
|---|---|---|
| A1 | Log out via the header user dropdown | redirects to login screen; cookie cleared |
| A2 | (Optional) wait ~30 seconds — represents "a few days later" | n/a |
| A3 | Log back in with same credentials | session restores; sidebar repopulates |
| A4 | Verify in sidebar: prior sessions present, topic groups intact | topic-grouped sidebar working |
| A5 | Verify in My Core: prior topics present ("Client Advisory — Q1 2026", "Payroll Compliance", "Vendor Follow-up" from Sim 4) | Core persistence |

### Prompt sequence — Phase B (new session after re-login)

Create a new session: "Client update from saved findings"

| # | Prompt | Expected capability |
|---|---|---|
| B1 | "Recall the summarized collection risk and recommended next steps from AR collection risk." | **Core Recall** → AR save |
| B2 | "Recall the saved short note to the client about payroll tax exposure." | **Core Recall** → Payroll save |
| B3 | "Recall the saved the brought-up net income note with current service-line performances." | **Core Recall** → Q1 net income save (closest match) |
| B4 | "Combine these into a short client update covering the three areas." | Multi-source synthesis |
| B5 | "What should I follow up on first, and why?" | Reasoning/recommendation |

### Expected output
- A1-A5: Clean logout/login cycle; all prior state intact; sidebar
  and My Core both reflect the work done in Sims 1-4.
- B1-B3: Each prompt routes to Core Recall (not SQL/RAG); each
  returns the most-relevant save with title, date, similarity score,
  and clickable source-session link.
- B4: Coherent 3-4 paragraph synthesis weaving together the three
  saved findings without inventing new content.
- B5: Specific priority recommendation grounded in the recalled
  findings. Note: this is where CASSIA could reasonably flag the
  payroll tax exposure as highest-priority since unrecorded IRS
  deposits accumulate penalties.

### Pass / partial / fail

| Outcome | Criteria |
|---|---|
| ✅ Pass | Logout/login cycle clean; all sessions and topics persist; all three Core Recall prompts route correctly and return the right saves; multi-save synthesis is coherent and grounded |
| 🟡 Partial | Auth and persistence work but one of the three Core Recall prompts returns a less-relevant save (similarity threshold or recall ranking issue); OR synthesis is shallow but accurate |
| ❌ Fail | Logout/login breaks persistence; OR Core Recall fails on any prompt; OR synthesis hallucinates content not in the recalled saves |

### What this scenario tests about CASSIA
The deepest identity claim — **CASSIA is a memory database for
accounting work, not a chat history.** If a user can log out, come
back, and use natural language to find prior work across multiple
topics with synthesis on top — that's the workspace claim proven. If
any part of this breaks, the workspace identity needs honest
reframing in the journal.

### Risk flag
The most important multi-step test in Phase 6. Failures here would
materially change what the journal can say about CASSIA's identity.

---

## Simulation 6 — AP Payment Priority + Cash Planning

### Business situation
A client has cash flow constraints this month and asks their accountant
which vendor payments should be prioritized. The accountant pulls the
overdue AP, ranks vendor exposure, **recalls prior context about cash
position or net income** to set the constraint, and produces a
prioritization recommendation.

### Sources / capabilities used
SQL + chart auto-rendering; **Core Recall (single save — fused with new
SQL for planning synthesis)**; Save to Core.

### Data context
AP has 10 vendors currently marked Overdue: Microsoft Azure ($6,200,
75 days), Cisco Systems ($9,800, 70 days), **Oracle Corporation
($15,000, 57 days)** — note: same vendor used in Sim 4, perfect cross-
reference, HP Inc ($4,300, 48 days), Pitney Bowes ($1,200, 43 days),
Iron Mountain ($880, 38 days), Comcast Business ($1,450, 29 days),
Xerox Corporation ($3,200, 25 days), Ricoh USA ($2,100, 20 days),
Shred-It ($650, 15 days). Total overdue: $44,780.

### Distinct from Sim 1
Sim 1 was AR + recordkeeping (collection + documentation). Sim 6 is AP
+ prior-context recall (priority + cash planning). The distinct
capability hit here is **Core Recall fused with a new SQL query to
produce a planning synthesis** — using yesterday's analysis to
constrain today's decision.

### Prompt sequence (5 prompts + save)

| # | Prompt | Expected capability |
|---|---|---|
| 1 | "Which vendor invoices are currently overdue? Show vendor, amount, days overdue, and category." | SQL |
| 2 | "Rank overdue vendor exposure by amount as a chart." | SQL + chart |
| 3 | "Recall what I saved about net income or our current cash position." | **Core Recall** (hits Q1 net income save or similar) |
| 4 | "Given our recent net income context, which vendor payments should we prioritize and which can wait? Consider both amount and days overdue." | Synthesis (Core Recall context + new SQL) |
| 5 | (💾) Save as "AP payment priority" | save |

### Expected output
- Prompt 1: AP table with 10 overdue vendors, amounts, days overdue.
  Should highlight Oracle ($15,000) as the biggest exposure by amount
  and Microsoft Azure (75 days) as oldest.
- Prompt 2: Bar chart ranking vendor exposure descending. Oracle on
  far left.
- Prompt 3: Core Recall fires; returns the Q1 net income save (or the
  closest cash-position-relevant save). Should show ~$101,491 figure.
- Prompt 4: Synthesis that uses both the new AP data and the recalled
  context. Strong synthesis would: prioritize Oracle (largest amount),
  Cisco (large + old), Microsoft Azure (oldest); deprioritize Shred-It,
  Iron Mountain, Pitney Bowes (small amounts) for next month.
- Save persists.

### Pass / partial / fail

| Outcome | Criteria |
|---|---|
| ✅ Pass | SQL/chart work; Core Recall surfaces a relevant prior save; prompt 4 synthesizes meaningfully — uses the recalled context AND ranks by combined criteria (amount + age), not just one; save persists |
| 🟡 Partial | SQL/chart work but Core Recall returns no good match (acceptable if no relevant save exists), OR synthesis ignores the recalled context entirely |
| ❌ Fail | SQL fails; OR Core Recall hallucinates a save that doesn't exist; OR save doesn't persist |

### What this scenario tests about CASSIA
Decision-support, not just reporting. *Can CASSIA combine fresh data
with prior context to produce a recommendation that takes constraints
into account?* This is the difference between a chatbot that answers
questions and a workspace that supports decisions.

---

## Demo video recommendations

**Top three for the demo video** (≈5-7 minutes filmed back-to-back):

1. **Sim 1 — AR Collection & Recordkeeping Risk.** Best opening because
   it's the most universally relatable advisory workflow. Numbers,
   chart, regulation, summary, save. Tight 90-second story.

2. **Sim 4 — Uploaded Oracle Email + Vendor Follow-up.** The
   distinctive demo — external document arriving, getting connected to
   internal books, ending with an organized follow-up plan. This is the
   moment that differentiates CASSIA from generic chat tools.

3. **Sim 5 — Logout/Login + Core Memory Continuity.** Proves the
   workspace claim. Most powerful if filmed with a visible time cut
   ("end of work session" → "after re-login") to dramatize persistence.

**Cutting room floor (README/devlog evidence, not video):**

- **Sim 2** — important compliance-review evidence (especially if
  CASSIA catches the missing deposits), but visually less compelling
  than Sim 1's full workflow. **However:** if Sim 2 produces a
  particularly striking "we found a real compliance issue" moment, it
  could replace Sim 1 in the demo lineup.
- **Sim 3** — important Core Recall evidence using existing saves, but
  the visual story is just text-and-chart. Stronger as a journal
  paragraph than a video segment.
- **Sim 6** — important decision-support evidence, but conceptually
  similar enough to Sim 1 that it would feel redundant in a video.

---

## Risk and scope notes

**Most important things to observe (not features to add, just journal
material):**

1. **Sim 1 prompt 3 — RAG fall-through honesty.** Does CASSIA admit
   when Pub 15 doesn't fully cover the AR-specific angle?
2. **Sim 2 prompt 3 — gap detection.** Does CASSIA notice the absence
   of deposit transactions, or just summarize what's there?
3. **Sim 3 — Q1 vs YTD discrepancy.** Does the $101,491 (recalled) vs
   $75,556 (fresh Q1 query) conflict surface, and how?
4. **Sim 4 — Pass 5 polish in real use.** Does the "Also move source
   session" checkbox actually refresh the sidebar correctly?
5. **Sim 5 prompts B1-B3 — multi-topic Core Recall.** Does Recall
   reach across different topic-organized saves consistently?
6. **Sim 5 prompts B4-B5 — synthesis quality.** Is CASSIA reasoning
   across recalls, or just listing them?
7. **Any scenario — BOTH route classification.** When questions blend
   data and rules, does the router actually classify as BOTH?

---

## Evidence capture checklist (during testing)

For each simulation, capture:

- [ ] Screenshot of each major answer (chat view)
- [ ] Screenshot of My Core after save/organize steps
- [ ] Screenshot of sidebar showing topic grouping (Sim 1, 2, 4, 5)
- [ ] Screenshot of route badge (SQL / RAG / BOTH / CORE_RECALL) per
      prompt
- [ ] Note on any surprises, hesitations, workarounds, or unexpected
      routes
- [ ] Final pass / partial / fail verdict per simulation
- [ ] One-paragraph "what I learned" / "what worked" / "what
      surprised" note per simulation — these go directly into the
      journal

---

## Decisions still open

1. **`journal_entries.csv` — leave / drop / rebuild.** My
   recommendation: leave, route around with explicit "general ledger"
   phrasing in prompts.
2. **Mock PDF for Sim 4 — ready when you are.** Anchored to Oracle
   Corporation, INV-038, $15,000, 57 days overdue. I'll draft full
   text content for the PDF conversion just before Sim 4 runs.
3. **Korean prompt inclusion.** Still optional. Recommend baking one
   into Sim 1 (e.g., "이 분석을 한국어로 한 문장 요약해주세요" after
   the synthesis) if you want bilingual coverage without adding a
   scenario.
4. **Execution order.** Still 1 → 6. Sim 5 requires saves from 1, 2,
   and (recall against pre-existing) 3.

---

## What success looks like

If Sims 1, 3, 6 pass cleanly and the two showcases (4, 5) pass with at
most one partial flag, Phase 6 is a success. **Sim 2 is the wildcard
this version** — if it passes (CASSIA catches the missing deposits),
that's a strong claim for the journal. If it partials (CASSIA
summarizes what's there but doesn't flag what's missing), that's still
honest and informative — CASSIA's analytical ceiling is "describe
what's present" rather than "identify what's absent."

The journal will be written from whatever Phase 6 produces, not from
the test plan's expected outputs. Honest framing is already the
project's posture.
