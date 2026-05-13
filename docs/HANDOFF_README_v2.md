# CoReckoner — Accounting AI Chatbot
## Session Handoff Document v2 — May 11, 2026

---

## What CoReckoner Is

An accounting AI chatbot combining RAG (IRS document search) and
Text-to-SQL (structured QuickBooks data) into one hybrid system.
FastAPI backend, persistent SQLite sessions, Plotly charts, dark UI.

**Port: 8002** — never reuse 3000 (prototype), 3001 (App 1), 3002 (future Next.js)

---

## How to Start Every Session

```bash
cd "/Users/sanghyunseong/Desktop/Z26 Glob NG consult/app 2 - chatbot/app2"
source venv/bin/activate
lsof -ti:8002 | xargs kill -9
python3 backend/main.py
```

Open: http://localhost:8002

**When to restart vs refresh:**
- Changed .py file → server restart required
- Changed index.html only → browser Cmd+R is enough
- Changed CSV data → run sql/phase1_load.py then restart
- Changed IRS PDF → run rag/phase1_ingest.py then restart

---

## Folder Structure

```
app2/
├── venv/                        single venv, Python 3.13 ARM
├── .env                         OPENAI_API_KEY
├── requirements.txt
├── data/                        9 source files
│   ├── irs_pub15.pdf
│   ├── accounts_payable.csv
│   ├── accounts_receivable.csv
│   ├── balance_sheet.csv
│   ├── chart_of_accounts.csv
│   ├── general_ledger.csv
│   ├── journal_entries.csv
│   ├── profit_loss.csv
│   └── revenue.csv
├── outputs/
│   ├── chroma_db/               414 vectors (IRS Pub 15)
│   ├── accounting.db            7 SQL tables
│   └── coreckoner.db            sessions + messages + artifacts
├── rag/
│   ├── phase1_ingest.py
│   ├── phase2_query.py
│   └── phase3_inspect.py
├── sql/
│   ├── phase1_load.py
│   └── phase2_query.py
└── backend/
    ├── main.py
    ├── db/
    │   ├── __init__.py
    │   └── session_store.py
    ├── pipelines/
    │   ├── __init__.py
    │   ├── sql_pipeline.py
    │   └── rag_pipeline.py
    ├── routers/
    │   ├── __init__.py
    │   └── query_router.py
    └── static/
        └── index.html
```

---

## Databases

### accounting.db — demo dataset (7 tables)

| Table | Rows | Key columns |
|-------|------|-------------|
| chart_of_accounts | 52 | account_code, account_type, account_subtype |
| general_ledger | 139 | date, debit, credit, period, client_vendor |
| balance_sheet | 27 | jan_31_2026 → apr_30_2026, account_subtype |
| profit_loss | 28 | january_2026 → april_2026, ytd_total, category |
| accounts_receivable | 14 | balance_due, days_outstanding, aging_bucket, billing_partner |
| accounts_payable | 45 | amount, status, days_outstanding, vendor_name |
| revenue | 53 | amount, invoice_date, service_type, client_name |

**Critical SQL rules (enforced via _override_sql + prompt rules):**
- profit_loss has NO date column — use january_2026/february_2026/march_2026/april_2026
- balance_sheet has NO date column — use jan_31_2026/feb_28_2026/mar_31_2026/apr_30_2026
- general_ledger uses 'date' (TEXT YYYY-MM-DD) and 'period' (TEXT YYYY-MM)

### coreckoner.db — session persistence (3 tables)

```
sessions   — session_id, title, created_at, updated_at
messages   — message_id, session_id, role, content, pipeline_used, timestamp
artifacts  — artifact_id, message_id, artifact_type, content_json, created_at
```

Artifact types saved per assistant message:
- route_explanation
- response_type
- sql_query
- sql_result  {columns, rows}
- citations   [{page, preview}]
- chart_spec  {chart_type, columns, rows, question}

---

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | /chat | Main chat — session_id optional in body |
| GET | /sessions | List all sessions |
| POST | /sessions | Create new session |
| GET | /sessions/{id} | Full restore with messages + artifacts |
| PATCH | /sessions/{id} | Rename session |
| DELETE | /sessions/{id} | Delete session + cascade |
| GET | /health | Server + persistence status |
| GET | /stats | Row counts + session count |
| GET | /schema | accounting.db schema |

---

## What Is Completed ✅

### Phase 1 — Persistent Multi-Session Chat
- session_id created automatically on first question
- All messages saved to coreckoner.db
- SQL results, citations, response_type, chart_spec saved as artifacts
- Sidebar lists sessions ordered by recent activity
- Clicking session restores full thread including SQL tables and charts
- Browser refresh does not erase history
- New Chat button creates separate session
- Delete session with ✕ button (cascades to messages + artifacts)

### Group A — Session UX
- A1 ✅ Session rename — pencil icon in sidebar, inline edit, PATCH /sessions/{id}

### Group B — Visualization
- B1 ✅ Plotly charts — auto-generated from SQL numeric results
- B2 ✅ User chart type requests — "bar chart", "pie chart", "line chart" honored
- B3 ✅ Chart artifacts saved — charts restore when session reopened

### Group D — Response Quality
- D1 ✅ Response type badges — answer/no_data/sql_error/rag_not_found with color coding
- D1 ✅ Response type saved as artifact — badge restores correctly on session restore

### SQL Pipeline Improvements
- Dynamic schema enrichment — TABLE_DESCRIPTIONS injected at query time
- _override_sql() — intercepts trend/chart questions and returns correct SQL directly
  bypassing LLM for known problem patterns (profit_loss date hallucination)
- chart_hint inference — bar/line/pie detected from data shape + question keywords

---

## What Remains ❌

### Group C — Multi-Datasource Upload (Phase 3) — NEXT PRIORITY
- C1 File upload engine — CSV, Excel, PDF, text, image per session
- C2 CSV/Excel ingestion — column mapping preview, ingest to SQLite, session-scoped
- C3 PDF ingestion into RAG — chunk + embed + add to ChromaDB session-scoped
- C4 Text/image upload — embed description into ChromaDB
- C5 Missing data guidance — when query needs data not uploaded, suggest what to upload

### Group D — Remaining
- D2 Conversation memory — follow-up questions referencing prior answer
  ("show me the top 3 from those" needs context from previous turn)
  LangChain ConversationBufferWindowMemory deprecated — needs new implementation

### Group E — Client/Dataset Scope (Phase 4)
- E1 Client profiles — client_id, name, fiscal_year_end, accounting_standard
- E2 Dataset scoping — session-only vs client-wide datasets

### Group F — Infrastructure
- F1 LangChain Chroma deprecation — migrate from langchain_community.vectorstores
  to langchain_chroma package

### Phase 5 — Cross-Dataset Synthesis — DEFERRED
- Compare data across sessions and datasets
- Multi-table JOIN generation
- Deferred until Phase 4 stable

---

## Known Issues

| Issue | Status |
|-------|--------|
| LLM hallucinates date column on profit_loss | Fixed via _override_sql() |
| No data badge disappears on session switch | Fixed — response_type saved as artifact |
| Duplicate response_type key in openSession JS | Fixed — removed redundant line |
| FROM missing in structural SQL example | Fixed in RULES section |

---

## 60 Demo Questions

### SQL — P&L
1. What is our net income for Q1 2026?
2. Show our net income trend as a line chart
3. What is our gross margin by month?
4. Show gross margin trend as a line chart
5. Which month had the highest net income?
6. What is our total revenue by service line?
7. Show revenue by service line as a bar chart
8. What is our EBITDA for Q1 2026?
9. Which expense category cost the most in Q1?
10. How does our Q1 2026 revenue compare to prior year?

### SQL — Balance Sheet
11. How has our cash balance changed since January?
12. What is our current ratio as of April 30?
13. What are our total current assets as of April 30?
14. What is our total liability as of April 30?
15. How much did accounts receivable grow from January to April?
16. What is our total equity as of April 30?
17. How much prepaid insurance do we have remaining?
18. What is our net fixed asset value after depreciation?
19. How much do we owe on long term notes payable?
20. What is our working capital as of April 30?

### SQL — AR/AP/GL
21. Show me all AR over 60 days with the billing partner
22. Which client has the highest outstanding balance?
23. How much total AR is in the 90+ days bucket?
24. Which invoices are at risk of becoming bad debt?
25. What is our total AR balance right now?
26. Which vendor do we owe the most money to right now?
27. What invoices are overdue by more than 60 days?
28. What is our total outstanding AP balance?
29. Which GL entries hit consulting revenue in March?
30. What is the total amount of depreciation recorded YTD?

### RAG — IRS Publication 15
31. What are the FICA tax rates for Social Security and Medicare?
32. How should employers handle W-4 exempt claims?
33. What is the penalty for late payroll tax deposits?
34. What counts as a supplemental wage payment?
35. When must an employer use the semiweekly deposit schedule?
36. What is the Social Security wage base limit for 2026?
37. How are employee bonuses and commissions taxed?
38. What are employer responsibilities for new hires?
39. What is backup withholding and when does it apply?
40. How does the trust fund recovery penalty work?

### BOTH — Showstopper demo questions
41. What is our overdue AP balance and what is the IRS penalty for late deposits?
42. How much did we pay in payroll and what are the FICA withholding requirements?
43. Show me our Q1 revenue and explain how consulting income is taxed
44. What is our total salary expense and what payroll forms must we file?
45. Which invoices are past due and what does IRS say about recordkeeping?

### Response type / edge cases
46. Show me all invoices from 2019           — No data badge
47. What is our Q5 revenue?                  — No data badge
48. Tell me about company strategy           — RAG not found badge
49. Show our net income trend as a line chart — line chart with transpose
50. Show expense breakdown as a pie chart     — pie chart

---

## 5-Question Mentor Demo Sequence

| # | Question | Shows |
|---|----------|-------|
| 1 | What is our net income for Q1 2026? | P&L, monthly breakdown |
| 2 | Show our net income trend as a line chart | Plotly line chart |
| 3 | Show me all AR over 60 days with billing partner | AR aging, collections |
| 4 | What is the penalty for late payroll tax deposits? | RAG, IRS citations |
| 5 | What is our overdue AP balance and what is the IRS penalty? | BOTH pipeline |

---

## Sessions 7–10 Roadmap

| Session | Focus |
|---------|-------|
| 7 | Multi-datasource upload — CSV/Excel/PDF upload per session (Phase 3) |
| 8 | Conversation memory — follow-up question context (D2) |
| 9 | Client profiles + dataset scoping (Phase 4) |
| 10 | UX polish + Loom video + GitHub repo + LinkedIn post |

---

## Job Positioning

LinkedIn headline:
"Applied Gen AI Developer — RAG + Text-to-SQL for Accounting & Finance"

Positioning statement:
"I build practical AI tools for accounting, finance, tax, and
document-heavy business workflows using RAG + Text-to-SQL architecture."

2-minute demo script:
  0:00–0:30  Problem — why accountants need AI for data queries
  0:30–1:30  Live demo — BOTH pipeline question with chart
  1:30–2:00  Tech stack — RAG + Text-to-SQL + FastAPI + persistent sessions

---

*Last updated: May 11, 2026*
*Next task: Phase 3 — Multi-datasource upload (Session 7)*
