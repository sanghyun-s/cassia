# CoReckoner

> **Accounting AI chatbot** that combines **Retrieval-Augmented Generation** (IRS regulations) with **Text-to-SQL** (structured QuickBooks data) into one hybrid query system. Built to answer questions like *"What is our overdue AP balance, and what is the IRS penalty for late deposits?"* — a single question that needs both numbers and policy context.

---

## What it does

CoReckoner is a chat interface for accountants and finance teams that answers questions across two very different knowledge sources:

- **Structured accounting data** (P&L, balance sheet, AR, AP, GL, revenue) via a Text-to-SQL pipeline against SQLite.
- **Tax regulations** (IRS Publication 15 — Employer's Tax Guide) via a RAG pipeline backed by ChromaDB vector search.
- **Hybrid questions** that need both — the router classifies, runs both pipelines, and merges the answer.

Users can also **upload their own CSV or Excel files** through the UI; the data is ingested into a per-session SQLite database and becomes immediately queryable in chat alongside the demo data.

---

## Demo questions

A representative slice of the 60-question benchmark suite this app is tested against:

### Structured data (Text-to-SQL)
- *What is our net income for Q1 2026?*
- *Show our net income trend as a line chart*
- *Show me all AR over 60 days with the billing partner*
- *Which vendor do we owe the most money to right now?*
- *What is our current ratio as of April 30?*

### Tax regulations (RAG)
- *What is the penalty for late payroll tax deposits?*
- *What are the FICA tax rates for Social Security and Medicare?*
- *When must an employer use the semiweekly deposit schedule?*

### Hybrid (router runs both pipelines)
- *What is our overdue AP balance and what is the IRS penalty for late deposits?*
- *How much did we pay in payroll and what are the FICA withholding requirements?*

### User uploads (upload `revenue.csv` first via 📎)
- *How many rows are in my uploaded data?*
- *What is the total amount in my uploaded revenue table?*

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Browser  (vanilla HTML/CSS/JS · Plotly · dark UI)         │
│  ▸ 📎 upload · session sidebar · chat · charts             │
└────────────────────────┬────────────────────────────────────┘
                         │ /chat · /sessions · /uploads
┌────────────────────────▼────────────────────────────────────┐
│  FastAPI backend (port 8002)                                │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Query router  (LLM classifier → sql | rag | both)   │    │
│  └─────────────────────────────────────────────────────┘    │
│        │                                  │                 │
│  ┌─────▼────────┐                  ┌──────▼──────┐          │
│  │ SQL pipeline │                  │ RAG pipeline│          │
│  │ • Text-to-SQL│                  │ • ChromaDB  │          │
│  │ • accounting │                  │ • IRS Pub 15│          │
│  │ • + user_data│                  │   (414 vecs)│          │
│  │   (attached) │                  │             │          │
│  └─────┬────────┘                  └──────┬──────┘          │
│        │                                  │                 │
│        └──────────────┬───────────────────┘                 │
│                       ▼                                     │
│                Merge & answer                               │
└─────────────────────────────────────────────────────────────┘

Persistence (all SQLite):
  outputs/accounting.db          — demo data (7 tables)
  outputs/coreckoner.db          — sessions, messages, artifacts, uploads
  outputs/sessions/{id}.db       — per-session user uploads
  outputs/chroma_db/             — IRS vector store
```

### Key design choices

- **Two-database architecture for SQL.** The demo data lives in `accounting.db`; each user session has its own private DB at `outputs/sessions/{session_id}.db`. The SQL pipeline `ATTACH`-es the session DB at query time as the schema `user_data`, so a single query can read both demo and user data without polluting either.
- **Hybrid retrieval.** The router is a one-shot LLM call returning `sql | rag | both`. For `both` queries, the two pipelines run in parallel and a third LLM call merges their answers into one coherent response.
- **Persistent sessions with full artifact restore.** Every assistant message saves not just the text but the SQL query, the result rows/columns, the citations, the chart spec, and the response-type badge. Clicking a session in the sidebar restores everything pixel-for-pixel.
- **Schema-grounded prompts.** Instead of giving the LLM hand-written few-shot examples, the SQL pipeline introspects the live database, builds an enriched schema (column names, types, sample distinct values), and injects table-level descriptions. New columns appear in the prompt automatically.

---

## Tech stack

| Layer | Tools |
|-------|-------|
| Backend | Python 3.13, FastAPI, Uvicorn |
| LLM | OpenAI GPT-4o-mini via `langchain-openai` |
| RAG | LangChain, ChromaDB, OpenAI embeddings |
| Data | pandas, SQLite (built-in), openpyxl |
| Frontend | Vanilla HTML/CSS/JS, Plotly.js |
| Persistence | SQLite with WAL mode |

---

## Quick start

```bash
# 1. Clone and enter
git clone <your-repo-url> coreckoner
cd coreckoner/app2

# 2. Create venv + install
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY

# 4. Build the data stores (one-time)
python3 sql/phase1_load.py     # → outputs/accounting.db
python3 rag/phase1_ingest.py   # → outputs/chroma_db/

# 5. Run
python3 backend/main.py
```

Open http://localhost:8002.

API docs at http://localhost:8002/docs (FastAPI auto-generated).

---

## Project structure

```
app2/
├── backend/
│   ├── main.py                 FastAPI app entry + /chat + /sessions
│   ├── db/session_store.py     coreckoner.db CRUD
│   ├── pipelines/
│   │   ├── sql_pipeline.py     Text-to-SQL + user-data attach
│   │   └── rag_pipeline.py     RAG retrieval + synthesis
│   ├── routers/
│   │   ├── query_router.py     LLM classifier (sql | rag | both)
│   │   └── upload_router.py    /uploads/{preview,ingest,list,delete}
│   ├── uploads/
│   │   ├── schema_utils.py     Identifier sanitization, type inference
│   │   ├── tabular.py          CSV/Excel preview + ingest
│   │   └── session_db.py       Per-session SQLite manager
│   └── static/index.html       Single-page frontend
├── data/                       Source CSVs + IRS PDFs
├── sql/                        One-time scripts to build accounting.db
├── rag/                        One-time scripts to build ChromaDB
├── outputs/                    Generated at runtime (gitignored)
└── requirements.txt
```

---

## Features

### Implemented
- ✅ Hybrid SQL + RAG routing with merged answers
- ✅ Persistent multi-session chat with full artifact restore
- ✅ Auto-generated Plotly charts (bar / line / pie) from SQL results
- ✅ Session rename + delete with cascade cleanup
- ✅ CSV / Excel upload per session, queryable as `user_data.<table>`
- ✅ Upload sidebar with row counts and one-click delete
- ✅ Friendly nudges when a query returns no data
- ✅ Response-type badges (answer / no_data / sql_error / rag_not_found)

### In progress
- ⏳ PDF upload into ChromaDB with session-scoped retrieval

### Planned
- 📋 User accounts with a permanent core database (cross-session save & recall)
- 📋 Per-message "save to my data" gesture
- 📋 Topic-based session organization (P&L / payroll / bookkeeping)

---

## License

Private / internal. No license granted for external use.

---

*Built as an applied generative-AI project demonstrating production-style RAG + Text-to-SQL architecture for finance and accounting workflows.*
