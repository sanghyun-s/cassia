# Sessions 7+8+9 Update — May 5–6, 2026

This document covers the work done in three consecutive build sessions:

- **Session 7 (May 5):** Multi-source RAG with citations + Plotly auto-charts
- **Session 8 (May 5–6):** Conversation memory + bilingual comprehension
- **Session 9 (May 6):** UX polish (sidebar restructure, error handling, loading verification)

All priorities flagged in the post-mentor handoff are now implemented and tested.

---

## Session 7 — Multi-source RAG + Auto-charts

### Priority 2: Multi-source RAG with citations

**Mentor feedback addressed:** *"Sourcing of IRS publication has to be bigger or multiplied. Source comparison tool."*

The chatbot previously indexed only IRS Publication 15. It now indexes three IRS publications and shows users which document each fact came from.

**Files edited:**

| File | Change |
|---|---|
| `rag/phase1_ingest.py` | Multi-PDF loader (`load_all_pdfs`); attaches `source_doc` and `page_display` metadata; strips IRS print-production boilerplate via regex |
| `backend/pipelines/rag_pipeline.py` | Added `DOCUMENT_PROMPT` so retrieved chunks reach the LLM with their source label embedded; updated `RAG_PROMPT` to instruct inline citation; deduplicates returned sources by `(source_doc, page)` |
| `backend/static/index.html` | RAG sources rendered grouped by document with a header showing document count |

**New PDFs added:**
- `data/irs_pub15.pdf` — Employer's Tax Guide
- `data/irs_pub15t.pdf` — Federal Income Tax Withholding Methods
- `data/irs_pub15b.pdf` — Employer's Tax Guide to Fringe Benefits

**Bonus: PDF boilerplate cleanup.** IRS PDFs include print-production headers on every page (`"Page 17 of 71 Fileid: ..."`). A `clean_page_text` regex pass in `phase1_ingest.py` strips them before chunking.

### Priority 1: Plotly auto-charts

**Goal:** Auto-generate bar/pie/line charts when SQL queries return chartable data, with chart type chosen by data shape and overridden by explicit user requests.

**Files edited:**

| File | Change |
|---|---|
| `backend/pipelines/sql_pipeline.py` | Added `detect_chart_spec(df, question)` — returns Plotly spec dict or `None` based on data shape and user phrasing |
| `backend/main.py` | Added `chart_spec: Optional[dict]` to the `ChatResponse` Pydantic model |
| `backend/static/index.html` | Plotly CDN script tag; CSS for `.chart-container`; `renderChart` helper function |

**Detection logic:** Explicit user request → wide-format time series (line) → 2-10 rows positive (pie) → otherwise bar. Coerces numeric-looking strings to numbers before applying the heuristic.

**Bonus: SQL refusal handling.** Added a `NO_QUERY_POSSIBLE:` sentinel detected in `run_sql_pipeline` before SQL execution. Used for questions whose data isn't in the dataset (e.g. salary expense, depreciation, long-term notes payable).

---

## Session 8 — Conversation Memory + Bilingual

### Priority 3: Conversation memory

**Approach:** Pragmatic explicit-pass instead of `RunnableWithMessageHistory`. Last 3 turns formatted as plain text and injected into the router and SQL/RAG prompts.

**Files edited:**

| File | Change |
|---|---|
| `backend/main.py` | Removed `ConversationBufferWindowMemory`; added `HISTORY_WINDOW = 3` constant; added `get_recent_context(n)` helper formatting last N turns; pass `history=history_context` to router and pipelines |
| `backend/routers/query_router.py` | `ROUTER_PROMPT` updated with `{history_block}` placeholder and explicit follow-up handling rule; `route_with_llm` and `classify_question` accept `history` kwarg |
| `backend/pipelines/sql_pipeline.py` | `SQL_GENERATION_PROMPT` has `{history_block}` placeholder before column hints, plus FOLLOW-UP QUESTION HANDLING section with explicit example |
| `backend/pipelines/rag_pipeline.py` | `RAG_PROMPT` has `{history_block}` placeholder; uses `RAG_PROMPT.partial(history_block=...)` because RetrievalQA only passes context+question |

**Why explicit-pass over `RunnableWithMessageHistory`:** Lower complexity, no chain refactor, easier debugging. Trade-off: memory doesn't persist across server restarts. Acceptable for the demo; can be migrated later if needed.

### Bilingual comprehension

Korean questions work without prompt rewrites because GPT-4o-mini handles Korean comprehension natively. The router and SQL/RAG prompts route Korean correctly.

**Verified Korean scenarios:**
- *우리 회사의 1분기 매출 어떻게 돼?* → SQL `SUM(january_2026 + february_2026 + march_2026) WHERE category='Revenue'` → $451,683
- *60일 이상 연체된 미지급금이 있어?* → AP aging > 60 days
- *그 중에서 상위 3개만 다시 보여줘* → recovers SQL context across RAG turn boundary, produces `LIMIT 3`

**Known limitation:** Korean questions get English answers. Response language matching is a planned 30-minute prompt tweak.

### Five-turn end-to-end demo verified

| Turn | Question | Expected | Result |
|---|---|---|---|
| 1 | "Show me revenue by service line for Q1 2026 using bar chart" | SQL + bar chart, 8 rows | ✅ |
| 2 | "Just the top 3 of those" | `LIMIT 3` SQL, 3 rows | ✅ |
| 3 | "What does the IRS say about late payroll tax deposit penalties?" | RAG with [Pub 15, p.36] citations | ✅ |
| 4 | "그 중에서 상위 3개만 다시 보여줘" | Korean follow-up across RAG boundary, returns top 3 SQL | ✅ |
| 5 | "Please show me the top 3 service lines in the bar chart" | Explicit chart override, 3 rows + bar chart | ✅ |

---

## Session 9 — UX Polish

### Track A: Sidebar restructure

**Files edited:** `backend/static/index.html` (HTML, CSS, JavaScript blocks)

**What changed:**

1. **Removed** redundant header "Clear chat" button
2. **Added** "+ New chat" button at top of sidebar with confirmation toast ("Started new chat", fades in 2s)
3. **Added** Conversation history section that auto-shows when conversation begins
   - Each entry: turn number + truncated question + pipeline badge (SQL/RAG/BOTH)
   - Click any entry → main chat scrolls to that message + 1.6s blue highlight pulse
4. **Made** Sample Questions section collapsible with ▼ toggle
   - Auto-collapses after first question is asked
   - Re-expands on "+ New chat"
5. **Compacted** Stats from 2x2 grid to single inline row: `0 Q · 45 AP · 53 Rev · — JE`
6. **Compacted** Pipeline Legend from vertical list to single inline row of chips

**Sample question bank refreshed** to match tested demo questions (8 buttons covering bar/pie/line charts, RAG, BOTH).

### Track B: Error handling + loading verification

**Friendly error messages:** Replaced raw error display with categorized friendly messages.

**Files edited:** `backend/static/index.html`

The `appendError` function now branches on error keywords:

| Trigger | User message | Hint |
|---|---|---|
| `openai`, `api key` | "I'm having trouble reaching the AI service right now." | "Check that the OPENAI_API_KEY is set." |
| `database`, `sqlite` | "I couldn't access the accounting database." | "Make sure the database file exists and the server has restarted recently." |
| `chroma`, `vector` | "I couldn't access the IRS publication index." | "The ChromaDB index may need to be rebuilt." |
| `failed to fetch`, `connection` | "I can't reach the server right now." | "Check that the FastAPI server is running on port 8002." |
| anything else | "Something went wrong while processing your question." | "Please try again, or rephrase your question." |

Technical details still go to `console.error` for debugging.

**Refusals vs. errors distinction:** Refusals (system can answer with "this isn't tracked") are styled as normal AI messages. Errors (system can't function) show the warning icon and red title. This is a deliberate UX choice — graceful degradation feels different from system failure.

**Loading state verified:** Three-dot bouncing animation persists for the full duration of slow hybrid (BOTH) calls, typically 5–8 seconds. Disappears cleanly on response arrival.

**Empty state verified:** "+ New chat" cleanly resets to welcome screen with 3 pipeline chips, sample questions re-expanded, conversation section hidden, input field empty.

---

## How Testing Was Done

Three distinct testing surfaces:

### 1. Terminal (`curl` against the FastAPI backend)

```bash
curl -s -X POST http://localhost:8002/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"Show me revenue by service line"}' \
  | python3 -m json.tool
```

Used to verify the backend produces correct JSON. Bypasses browser entirely. Useful for confirming `chart_spec` and `sources` fields are populated.

### 2. Chrome DevTools Console

Used to verify frontend receives JSON correctly and JavaScript functions are loaded:

```javascript
typeof Plotly             // 'object' = CDN loaded
typeof newChat            // 'function' = Block 3 loaded
appendError.toString()    // shows the actual loaded function source
document.querySelectorAll('.chart-container').length  // counts charts
```

### 3. Python import test (catches indentation/syntax errors before restart)

```bash
cd backend
python3 -c "from main import app; print('OK')"
cd ..
```

If this prints `OK`, the file parses cleanly. Saved significant time during the session — FastAPI fails silently on bad indentation.

---

## Stable Demo Question Bank

These phrasings have been tested to produce reliable output:

**SQL with charts:**
- *"Show me revenue by service line for Q1 2026 using bar chart"*
- *"Break down our overdue accounts payable by vendor using pie chart"*
- *"How has our cash balance changed since January? Use line chart"*
- *"Show net income across the months as a line chart"*

**SQL without chart:**
- *"What is our net income year-to-date?"*
- *"What is our current ratio as of April 30?"*
- *"What is our total equity as of April 30?"*
- *"Which vendor do we owe the most money to right now?"*

**Refusals (graceful):**
- *"What is our total salary expense?"* → "This dataset doesn't track salary..."
- *"What is the total amount of depreciation recorded YTD?"* → graceful redirect
- *"How much do we owe on long-term notes payable?"* → graceful redirect

**Multi-source RAG:**
- *"Are employer-provided meals taxable to employees?"* (cites Pub 15-B, possibly Pub 15)
- *"What does the IRS say about late payroll tax deposit penalties?"* (cites Pub 15)
- *"What are the FICA tax rates for Social Security and Medicare?"* (cites Pub 15)
- *"What is backup withholding and when does it apply?"* (cites Pub 15)

**Hybrid (BOTH pipeline):**
- *"What is our overdue AP balance and what does the IRS say about late payment penalties?"*

**Conversation memory:**
- After a SQL question: *"Just the top 3 of those"*
- After a chart: *"Same data as a bar chart"*

**Bilingual (Korean):**
- *"우리 회사의 1분기 매출 어떻게 돼?"*
- *"60일 이상 연체된 미지급금이 있어?"*
- *"그 중에서 상위 3개만 다시 보여줘"*

---

## Known Issues and Trade-offs

- **Chart type doesn't inherit from prior turns.** Each new SQL result re-runs `detect_chart_spec` independently. "Top 3" follow-up after a bar chart auto-defaults to pie. Acceptable; users can specify chart type explicitly.
- **Pub 15-T tabular lookups.** Tabular row/column lookups (e.g. specific withholding amounts at specific wage levels) return "I couldn't find that in the available IRS publications." Known RAG-with-tables limitation.
- **Korean responses are in English.** Comprehension works; response-language matching is a planned tweak.
- **Single-session memory.** Browser refresh clears history. ChatGPT-style multi-session persistence is a roadmap item.
- **No file upload.** CSVs are loaded via `phase1_load.py` script. Upload UI is a roadmap item.

---

## Next Steps (Post-Session 9)

1. **GitHub repository setup** — `.gitignore`, initial commit, push, README rendering verification
2. **Korean response language polish** — 30-minute prompt instruction tweak in SQL/RAG prompts
3. **Loom demo recording** — 2-minute walkthrough: problem → demo → architecture
4. **Mentor conversation** — multi-datasource upload UI, persistent sessions, refusal vs. error UX

After those four items, App 2 reaches v1 ship-ready status.
