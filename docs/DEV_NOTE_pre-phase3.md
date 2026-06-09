# App 2 — CoReckoner
## Hybrid RAG + Text-to-SQL Pipeline

> An AI-powered accounting assistant that answers plain-English questions about both unstructured documents (IRS publications) and structured financial data (QuickBooks-style exports), served through a FastAPI backend and dark-themed chat UI with conversation memory and bilingual support.

---

## What This Project Does

A unified chatbot that combines two AI pipelines under one interface:

- **RAG pipeline** — answers policy and regulation questions grounded in three IRS publications (Pub 15, Pub 15-T, Pub 15-B), with inline source citations
- **Text-to-SQL pipeline** — converts plain-English questions into SQL, runs them on a 7-table accounting database, returns exact numbers with auto-generated Plotly charts when appropriate
- **Hybrid router** — classifies each question and routes to the right pipeline, or combines both for hybrid questions
- **Conversation memory** — handles follow-up questions ("show me top 3 of those") by passing recent turns into the router and pipelines
- **Bilingual comprehension** — accepts Korean and English questions, generates correct SQL and pulls correct citations regardless of input language

---

## Demo Capabilities

The system handles five distinct response patterns, each with appropriate UI treatment:

1. **Successful SQL answer** — table of numbers + auto-chart (bar / pie / line)
2. **Successful RAG answer** — text answer with inline `[Pub 15-B, p.4]` citations + grouped sources panel
3. **Hybrid (BOTH) answer** — merges SQL data with policy context in one unified response
4. **Graceful refusal** — when data isn't tracked (e.g. salary expense), returns a redirect message instead of broken SQL
5. **Categorized error** — friendly messages distinguishing connection issues, API key problems, database access, etc.

---

## Project Structure

```
app2/
│
├── data/                          ← All source files
│   ├── irs_pub15.pdf              ← Employer's Tax Guide
│   ├── irs_pub15t.pdf             ← Federal Income Tax Withholding Methods
│   ├── irs_pub15b.pdf             ← Employer's Tax Guide to Fringe Benefits
│   ├── chart_of_accounts.csv      ← 52 accounts (full COA)
│   ├── general_ledger.csv         ← 139 transactions Jan–Apr 2026
│   ├── balance_sheet.csv          ← 27 monthly snapshots
│   ├── profit_loss.csv            ← 28 P&L rows by service line
│   ├── accounts_receivable.csv    ← 14 invoices with aging buckets
│   ├── accounts_payable.csv       ← 45 vendor invoices
│   └── revenue.csv                ← 53 client invoices
│
├── outputs/                       ← Generated indexes (do not commit)
│   ├── chroma_db/                 ← Multi-source vector store
│   └── accounting.db              ← SQLite, 7 tables
│
├── rag/                           ← RAG pipeline scripts
│   ├── phase1_ingest.py           ← Multi-PDF → chunks → ChromaDB
│   ├── phase2_query.py            ← Standalone RAG Q&A
│   └── phase3_inspect.py          ← Inspect vectors, scores, filters
│
├── sql/                           ← Text-to-SQL pipeline scripts
│   ├── phase1_load.py             ← CSVs → SQLite
│   └── phase2_query.py            ← Standalone SQL Q&A
│
├── backend/                       ← FastAPI server
│   ├── main.py                    ← /chat endpoint, runs on port 8002
│   ├── routers/
│   │   └── query_router.py        ← LLM-based question classifier with history awareness
│   ├── pipelines/
│   │   ├── sql_pipeline.py        ← Text-to-SQL + chart detection + memory
│   │   └── rag_pipeline.py        ← Multi-source RAG with citations + memory
│   └── static/
│       └── index.html             ← Dark-themed chat UI + Plotly + sidebar history
│
├── docs/
│   ├── SESSION_7_UPDATE.md        ← Sessions 7+8+9 work log
│   └── architecture.png           ← (optional) System diagram
│
├── venv/                          ← Single consolidated environment
├── .env                           ← OPENAI_API_KEY (do not commit)
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER QUESTION                                │
│   "What's our AP overdue and what does the IRS say about that?"     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              QUERY ROUTER (history-aware)                           │
│         Is this NUMBERS, DOCUMENT, or BOTH?                         │
│         Resolves follow-ups using recent conversation context       │
└────────────────┬─────────────────────┬──────────────────────────────┘
                 │                     │
        ┌────────┘                     └────────┐
        ▼                                       ▼
┌────────────────────────┐      ┌─────────────────────────────────────┐
│   TEXT-TO-SQL PIPELINE │      │           RAG PIPELINE              │
│                        │      │                                     │
│  Question + history    │      │  Question + history                 │
│     ↓                  │      │     ↓                               │
│  LLM writes SQL        │      │  Embed via text-embedding-3-small   │
│  (or NO_QUERY refusal) │      │     ↓                               │
│     ↓                  │      │  ChromaDB top-5 across 3 IRS pubs   │
│  sqlite3 execution     │      │     ↓                               │
│     ↓                  │      │  LLM grounded answer                │
│  Auto chart spec       │      │  Inline [Pub name, p.X] citations   │
│     ↓                  │      │     ↓                               │
│  Plain-English summary │      │  Grouped sources panel              │
└──────────┬─────────────┘      └──────────────┬──────────────────────┘
           │                                   │
           └──────────────┬────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        UNIFIED ANSWER                               │
│   Text + Plotly chart (if applicable) + Sources (if RAG was used)   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────┐
│   FastAPI → HTML/JS UI               │  localhost:8002
│   Sidebar: history + jump-to-message │
└──────────────────────────────────────┘
```

---

## Pipeline 1 — RAG (Unstructured Data)

**What it does:** Answers questions grounded in IRS publications, citing the specific document and page each fact came from.

**How to run standalone:**
```bash
source venv/bin/activate

# Step 1 — Build the index (run once, ~$0.005 for 3 PDFs)
python rag/phase1_ingest.py

# Step 2 — Ask questions
python rag/phase2_query.py
```

**Source attribution:** Each chunk carries a human-readable label (`Pub 15 (Employer's Tax Guide)`, `Pub 15-T (Withholding Methods)`, `Pub 15-B (Fringe Benefits)`). The answer text contains inline citations like `[Pub 15-B, p.4]`, and the UI renders a sources panel grouped by document.

**Multi-source example:** When a question pulls from multiple publications (e.g. *"Are employer-provided meals taxable, and how do I withhold tax on them?"*), the answer cites both Pub 15-B (the meal rule) and Pub 15-T (the withholding method), and the UI shows both source groups distinctly.

---

## Pipeline 2 — Text-to-SQL (Structured Data)

**What it does:** Converts plain-English questions into SQL, runs them against the accounting database, explains the result, and auto-generates a Plotly chart when the data is chartable.

**How to run standalone:**
```bash
source venv/bin/activate

# Step 1 — Load CSVs into SQLite (run once)
python sql/phase1_load.py

# Step 2 — Ask natural language questions
python sql/phase2_query.py
```

**Database schema:**

| Table | Rows | Purpose |
|-------|------|---------|
| chart_of_accounts | 52 | Full COA backbone with account types |
| general_ledger | 139 | All double-entry transactions Jan–Apr 2026 |
| balance_sheet | 27 | Monthly snapshots (jan_31_2026 → apr_30_2026) |
| profit_loss | 28 | Monthly P&L by service line + ytd_total |
| accounts_receivable | 14 | AR aging with buckets (Current / 31-60 / 61-90 / 90+) |
| accounts_payable | 45 | Vendor invoices with status (Paid / Outstanding / Overdue) |
| revenue | 53 | Client invoice detail Oct 2025 – Apr 2026 |

**Auto-chart detection:** Numeric SQL results trigger automatic Plotly visualization. Bar charts for categorical breakdowns, pie charts for small (≤10) positive-value distributions, line charts for wide-format time series across month columns. Users can override the heuristic by including `"using bar chart"`, `"as pie chart"`, etc. in their question.

**Schema-grounded refusals:** Questions whose data isn't tracked (e.g. salary expense, depreciation, long-term notes payable) return a graceful redirect via a `NO_QUERY_POSSIBLE:` sentinel, instead of generating broken SQL.

---

## Conversation Memory

Every user question receives the last 3 turns of conversation as plain-text context, formatted via a `get_recent_context()` helper in `main.py`. This context flows into:

- **Router prompt** — resolves ambiguous follow-ups like "those" or "그 중에서"
- **SQL prompt** — modifies prior SQL with new constraints (e.g. adding `LIMIT 3`)
- **RAG prompt** — connects topical follow-ups across turns

Implemented as an explicit-pass approach rather than `RunnableWithMessageHistory` for pragmatism — the chains stay simple while gaining context awareness.

**Verified scenarios:**
- Turn 1: SQL question → bar chart with 8 service lines
- Turn 2: "Just the top 3" → produces `LIMIT 3` SQL automatically
- Turn 3: RAG question → IRS citations
- Turn 4 (Korean): "그 중에서 상위 3개만 다시 보여줘" → recovers SQL context across the RAG turn boundary, produces correct `LIMIT 3` SQL

---

## Bilingual Comprehension

Korean questions are routed and answered correctly without prompt rewrites:

- *우리 회사의 1분기 매출 어떻게 돼?* → Generates correct Q1 revenue SQL
- *60일 이상 연체된 미지급금* → Returns AP aging > 60 days
- *급여세 납부가 늦으면 IRS 벌금* → Pulls Pub 15 late deposit penalty citations

The router and SQL/RAG prompts handle Korean comprehension natively. Response language polish (Korean answers for Korean questions) is a planned follow-up.

---

## UX Polish

**Sidebar:**
- "+ New chat" button at top with confirmation toast
- Conversation history section with click-to-jump and highlight pulse
- Collapsible Sample Questions section (auto-collapses after first turn)
- Compact stats and pipeline legend (single inline rows)

**Error handling:**
- Categorized friendly error messages (connection / API key / database / vector store / unknown)
- Technical details still logged to browser console
- Refusals (system can run, can't answer) styled distinctly from errors (system can't run)

**Loading state:**
- Verified persistent during slow hybrid (BOTH) calls (5–8 seconds)
- Clean removal on response arrival

---

## RAG vs Text-to-SQL — When to Use Which

| Dimension | RAG | Text-to-SQL |
|-----------|-----|-------------|
| Data type | Unstructured (PDF, email, notes) | Structured (CSV, Excel, database) |
| Storage | ChromaDB (vector embeddings) | SQLite (relational tables) |
| Retrieval method | Cosine similarity search | SQL query execution |
| Result type | Cited text passages | Exact numbers + auto chart |
| Hallucination risk | Low — grounded in retrieved chunks | Near zero — math is deterministic |
| Best for | "What does the IRS say about...?" | "How much do we owe to...?" |

The router classifies each question and dispatches to one or both pipelines automatically.

---

## Key Concepts Learned

**Embeddings** — Text converted to 1536 floats representing semantic meaning. Similar meanings → vectors close together in space. Used in RAG to find relevant chunks without keyword matching.

**ChromaDB** — Local vector database. Stores text + embedding + metadata (source_doc, page_display). Persists to disk so you never re-embed the same document twice.

**Cosine similarity** — The score ChromaDB uses to rank chunks. Score near 1.0 = very relevant. Score near 0 or negative = unrelated.

**RetrievalQA chain with document_prompt** — LangChain pattern that orchestrates: embed question → retrieve top-k chunks → format each chunk with metadata → assemble prompt → call LLM → return answer with source documents. The `document_prompt` parameter is what enables inline citations.

**Text-to-SQL** — LLM reads the database schema and writes SQL to answer the question. SQL runs on real data returning exact numbers — no hallucination on the arithmetic. Few-shot Q&A pairs in the prompt teach the LLM project-specific column conventions.

**Plotly chart detection** — Inspecting a pandas DataFrame's shape and column types to decide whether and how to visualize it. Different chart types match different data shapes.

**Explicit-pass conversation memory** — Rather than refactoring chains to be `RunnableWithMessageHistory`, format the last N turns as plain text and inject into the prompt. Pragmatic when chain complexity is low.

---

## How to Run the Full App

```bash
cd "/path/to/app2"
source venv/bin/activate

# First time only: build indexes
python3 rag/phase1_ingest.py    # builds outputs/chroma_db/
python3 sql/phase1_load.py      # builds outputs/accounting.db

# Every session
lsof -ti:8002 | xargs kill -9   # kill any stale server
python3 backend/main.py         # start FastAPI

# Open http://localhost:8002 in Chrome
```

---

## Status

| Component | Status |
|---|---|
| RAG pipeline (3 IRS publications) | ✅ Done |
| Text-to-SQL pipeline (7 tables) | ✅ Done |
| Query router (SQL / RAG / BOTH) | ✅ Done |
| FastAPI backend on port 8002 | ✅ Done |
| Dark-themed chat UI with sidebar | ✅ Done |
| Multi-source citations grouped by document | ✅ Done |
| Plotly auto-charts (bar / pie / line) | ✅ Done |
| Schema-grounded SQL refusals | ✅ Done |
| Conversation memory (SQL + RAG, history-aware) | ✅ Done |
| Bilingual comprehension (Korean) | ✅ Done |
| New-chat / history sidebar / collapsible UX | ✅ Done |
| Friendly categorized error messages | ✅ Done |
| Korean response language polish | ⏳ Planned |
| Multi-datasource upload UI | 🔮 Roadmap |
| Persistent multi-session chat (ChatGPT-style) | 🔮 Roadmap |
| Loom demo + GitHub cleanup | ⏳ In progress |

## Development Log

This project was built across multiple sessions, with each session documented as a build journal. See [`docs/INDEX.md`](docs/INDEX.md) for the full development log including:

- Architectural decisions (e.g. why explicit-pass memory over `RunnableWithMessageHistory`)
- Debugging journeys (e.g. how cache issues were diagnosed, how schema-grounded refusals were added)
- Verified test scenarios
- Known limitations and trade-offs

A chronological record of build sessions for CoReckoner.
This is the development journal for the project — design decisions, debugging journeys, and lessons learned. Each entry covers one or more build sessions.

---

## Sessions

### [Major Build Sprint (May 5–6, 2026)](SESSION_7_UPDATE.md)

**Topics:** Multi-source RAG with citations, Plotly auto-charts, conversation memory, bilingual comprehension, sidebar restructure, friendly error handling

**Key milestones:**
- Indexed 3 IRS publications with grouped source citations
- Implemented bar/pie/line auto-chart detection
- Added pragmatic conversation memory via explicit-pass approach
- Verified Korean question handling end-to-end
- Restructured sidebar with new chat button and conversation history
- Categorized error messages (connection / API key / database / vector store)

---

## How to Read These Logs

Each session log follows a consistent format:

- **Goal** — what was being attempted
- **Files edited** — which parts of the codebase changed
- **Verified scenarios** — what was tested
- **Known issues** — limitations and trade-offs
- **Next steps** — what comes after

The logs are written for two audiences:
1. **My future self** — to remember why decisions were made
2. **Portfolio reviewers** — to see how the project was actually built

---

## Topics Index (Coming Soon)

As more sessions are added, this section will let you find specific topics:

- **RAG implementation** — Sessions 7
- **Conversation memory** — Sessions 7, 8
- **Bilingual support** — Session 8
- **UX polish** — Session 9
- **Deployment & demo** — TBD


---

## Roadmap

Future enhancements considered but not yet implemented:

- **Multi-datasource upload UI** — Drop-zone for uploading user CSVs (P&L, Balance Sheet, Transactions) with schema-flexible ingestion
- **Persistent multi-session chat** — Save and restore prior conversations like ChatGPT, requires SQLite session table and full DOM rebuild
- **LLM-as-judge evaluation suite** — Automated scoring of routing accuracy, citation correctness, refusal quality
- **Streaming responses** — Server-sent events for token-by-token streaming of long answers
- **Korean response generation** — Bilingual comprehension is done; matching response language is a 30-min prompt instruction tweak

---

## Environment Setup

```bash
# Python version
python --version   # 3.13.x (Mac ARM)

# Key packages — single consolidated venv
langchain==0.3.14
langchain-community==0.3.14
langchain-openai==0.2.14
chromadb==0.5.5
pandas==2.2.2
fastapi==0.115.4
uvicorn==0.32.0
rich==13.7.1
python-dotenv==1.0.1

# .env file at project root
OPENAI_API_KEY=sk-...
```
