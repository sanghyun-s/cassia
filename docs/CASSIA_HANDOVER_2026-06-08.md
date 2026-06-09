# CASSIA — Handover Note for New Chat

**Last updated:** Mon June 8, 2026, evening
**Deadline:** Wednesday June 10, 2026 (internal target for App 2 deploy)
**Status:** Phase 6 stabilization complete. All five patches applied and runtime-verified. Ready for cleanup + demo prep + deploy.

---

## What CASSIA is

**CASSIA** is a chat-based accounting support workspace for small-business follow-up work — the non-calculation support side: client questions, agency notices, follow-up tasks. Positioned to differentiate from "PREPARE" (a hypothetical sibling product focused on bookkeeping/reconciliation/calculation).

**Tagline framing:** "chat-based accounting support workspace for small-business follow-up work." Earlier framing as "mini-ChatGPT for accounting" was retired after mentor feedback (too generic, didn't capture the workflow).

**The workflow it supports:** Ask → Retrieve → Visualize → Save → Organize → Recall → Follow up. Topic grouping mirrors the Outlook-folder pattern accountants already use to organize threads by client/issue.

**Key features:**
- LLM-routed queries (SQL / RAG / BOTH / Core Recall)
- Pre-loaded demo accounting database (`accounting.db`)
- User-uploaded data (CSV/Excel → `user_data.*` namespace) and policy documents (PDF → Chroma)
- IRS Publication 15 indexed in Chroma for RAG
- "Core" saves — durable, embedded findings stored per-user with semantic recall
- Topic grouping (Outlook-style folders) for sessions
- Chart rendering (bar/line/pie via Plotly) on SQL results

**App identity:** v2.12.1, Phase 5b/c (auth-required). Multi-user with login + invite code.

---

## Project location

```
/Users/sanghyunseong/Desktop/Z26 Glob NG consult/app 2 - chatbot/app2/
```

- Database: `outputs/coreckoner.db`
- User: `SanghyunAcct` (usr_d3ce41e79c5c)
- GitHub: github.com/sanghyun-s/accounting-ai-chatbot
- Server entry: `python3 backend/main.py` (NOT `python3 -m backend.main`)
- Imports use `from utils.X` not `from backend.utils.X` because of how the entry point loads

**Deployment context:** Deploying alongside App 1 (already deployed) and App 3 (deadline extended after today). Wednesday is the internal target for App 2.

---

## Development arc this session

### Phase 6 testing (earlier today / yesterday)
Six simulations were run against pre-patch CASSIA. Mixed results surfaced four real bugs:

| Sim | Topic | Verdict | Issue surfaced |
|---|---|---|---|
| 1 | AR Collection (Pub 15 dead-end) | PASS | RAG "not found" message wording was dead-end |
| 2 | Missing payroll deposits (synthesis) | PARTIAL | BOTH-route synthesis ingested "No uploaded data" stub as evidence; ALSO surfaced latent NaN-in-JSON bug |
| 3 | Revenue + Q1 net income recall | PASS-with-UX-issue | Core Recall hung ~5 minutes on first attempt (embedding API timeout) |
| 4 | Oracle vendor PDF + AP cross-ref | PARTIAL | SQL cross-table query failed with UNION mismatch + missing-column error, error text leaked to user |
| 5 | Logout/login + multi-save recall | PARTIAL | Recall returned proxy "I have related saves but..." messages instead of the actual answer; also multi-statement SQL error leaked |
| 6 | AP priority + cash planning | PASS | Cleanest end-to-end run |

### NaN bug discovered + fixed (separate from priorities)
- **Cause:** GL has sparse debit/credit columns → pandas NULL → NaN in JSON → Starlette's JSONResponse uses `allow_nan=False` → 500 errors
- **Fix:** `backend/utils/json_safe.py` created with `sanitize_for_json` / `safe_json_dumps`; patched 5 call sites in `session_store.py` and `main.py`
- **Cleanup:** 1 corrupted save + 2 artifacts sanitized via `cassia_nan_cleanup.py`
- **Status:** ✅ Done, verified clean. Backup at `coreckoner.db.pre-nan-cleanup-2026-06-07_204944.bak`

### Repositioning (mentor input mid-session)
- Pitching frame moved from "mini-ChatGPT for accounting" to "chat-based accounting support workspace for small-business follow-up work"
- 12 features mapped to accounting workflows in `CASSIA_FEATURE_TO_WORKFLOW_MAPPING.md`

### Stabilization v2 plan
Four priorities targeting the Phase 6 findings, plus a frontend follow-up that emerged during verification:

1. **P3 — RAG "not found" message** (Sim 1 → action-oriented wording)
2. **P1 — Backend chart column filter** (chart over-inclusion bug seen in Sims 1, 2)
3. **P2 — BOTH-route SQL-unusable guard** (Sims 2, 4, 5, 8 → shield synthesis from stubs/errors)
4. **P4 — Core Recall timeout** (Sim 3 → 30s timeout + user-visible fallback)
5. **P1b — Frontend chart filter** (added after verification revealed the backend filter wasn't reaching fresh-message rendering)

---

## All patches applied (in chronological order)

Each patch has a backup file in place with `.pre-{priority}-{timestamp}.bak` suffix.

### P3 — RAG not-found message ✅
- **File:** `backend/pipelines/rag_pipeline.py`
- **Lines:** 54 (LLM prompt instruction) + 230 (code fallback)
- **Change:** Replaced "I couldn't find that in the available documents" with action-oriented wording prompting upload of relevant docs
- **Applier:** `apply_p3_rag_message.py`
- **Backup:** `rag_pipeline.py.pre-p3-rag-msg-2026-06-08_181456.bak`
- **Verification:** Image 1 (AR write-off question) showed new wording with orange "Not found in docs" badge

### P1 — Backend chart column filter ✅
- **File:** `backend/pipelines/chart_builder.py`
- **Change:** Added `PREFERRED_MEASURE_COLUMNS`, `AVOID_AS_MEASURE_COLUMNS`, `EXPLICIT_COLUMN_REQUEST_PATTERN` constants, `_select_chart_columns()` helper, modified `build_chart_spec()` to filter columns and rows
- **Applier:** `apply_p1_chart_columns.py`
- **Backup:** `chart_builder.py.pre-p1-chart-2026-06-08_182517.bak`
- **Verification:** Debug prints (still in place — see cleanup tasks below) confirmed filter output: 12 input cols → 3 output cols `['txn_id', 'debit', 'credit']`

### P2 — BOTH-route SQL-unusable guard ✅
- **File:** `backend/main.py`
- **Change:** In the BOTH-route synthesis block (~line 530-578), added 11-pattern detection for SQL stubs + execution errors, switches synthesis prompt to RAG-only when SQL is unusable
- **Applier:** `apply_p2_both_guard.py` (had two iterations — first had print-string quote bug, fixed and re-applied)
- **Backup:** `main.py.pre-p2-both-2026-06-08_184058.bak`
- **Verification:** Image 5 (AR + IRS bad-debt BOTH question) showed clean blended answer

### P4 — Core Recall timeout ✅
- **File:** `backend/main.py`
- **Change:** Wrapped `run_core_recall_pipeline` call at line ~441 with `concurrent.futures.ThreadPoolExecutor` 30s timeout; on timeout returns matched=True controlled message
- **Applier:** `apply_p4_recall_timeout.py`
- **Backup:** `main.py.pre-p4-recall-2026-06-08_184606.bak`
- **Verification:** Image 5 (Core Recall on overdue) returned answer in normal time

### P1b — Frontend chart filter ✅
- **File:** `backend/static/index.html`
- **Change:** Added `_P1_PREFERRED_MEASURE_COLS`, `_P1_AVOID_AS_MEASURE_COLS`, `_p1SelectChartColumns()` helper (mirrors backend's _select_chart_columns), modified line ~2031 to use the helper as the fallback when `_chart_spec` is absent (i.e., the new-message path)
- **Applier:** `apply_p1b_frontend_chart_filter.py` (first run failed on indentation: expected 8 spaces, actual was 6; one-line fix to the applier then re-applied successfully)
- **Backup:** `index.html.pre-p1b-frontend-2026-06-08_194659.bak`
- **Verification:** User confirmed "Good, I see the impact of patch" after hard refresh + GL chart prompt — chart now shows only debit + credit on first render, no second refresh needed

---

## Diagnosis story for P1/P1b (in case it comes up)

The chart-filter problem had three layers that were peeled apart in sequence:

1. **First check (file content):** Patch was in chart_builder.py correctly ✓
2. **Second check (debug prints):** Backend filter was running at runtime — `OUT cols: ['txn_id', 'debit', 'credit']` ✓
3. **Third check (frontend code review):** Frontend has TWO paths — history-load (line 1133 populates `_chart_spec` from saved artifact) and new-message (no `_chart_spec` populated). Frontend renderer at line 2028 reads `data._chart_spec` correctly but only the history path has it
4. **30-second confirmation:** Browser refresh (forces history-load) → chart corrects itself → diagnosis confirmed
5. **Decision:** Frontend-only fix (mirror logic to JS) chosen over backend response-shape change to avoid Pydantic/ChatResponse model changes. Duplication is post-deploy refactor work.

---

## Outstanding tasks (in pickup order)

### IMMEDIATE — cleanup (5 min)
1. **Remove the two `[P1 DEBUG]` prints from `backend/pipelines/chart_builder.py`** — they're inside `build_chart_spec()`, right after the docstring and right after `selected = _select_chart_columns(...)`. They served their diagnostic purpose; the chart filter is fully verified.

### DECISION POINT — ship or defer P2b
2. **P2b — SQL-only route SQL-unusable guard.** The Image 4 Oracle query (cross-table UNION with missing `status` column) was SQL-routed, not BOTH-routed, so the existing P2 guard didn't fire. Raw SQLite error text leaked to the user. Two options:
   - **Ship now (~15 min):** Add the same `_sql_unusable_patterns` detection to the SQL-only branch in `main.py` at line ~579-580, with a fallback message like *"I couldn't form a reliable data query. Could you specify which table, amount, or comparison target you'd like me to look at?"*
   - **Defer post-deploy:** It's a real polish item but doesn't block deploy. Demo Sims can route around it.
   - User's call. Worth doing before Demo Sims if time allows.

### DEMO PREP — mock files (Claude's turn, ~30-45 min)
3. **Generate 7 mock upload files for Demo Sims 1-4:**
   - `client_year_end_request.pdf` (Sim 1 — AR Year-End Cleanup)
   - `credit_memo_log.csv` (Sim 1)
   - `bluerver_bank_statement.csv` (Sim 2 — Vendor Strategy)
   - `irs_notice_cp220.pdf` (Sim 3 — Payroll Notice)
   - `payroll_register_q1.csv` (Sim 3)
   - `q4_2025_board_memo.pdf` (Sim 4 — Quarterly Continuity)
   - `revenue_forecast_2026.csv` (Sim 4)
   - **Note:** `oracle_invoice_followup_email.pdf` for Sim 2 already exists in `/mnt/user-data/outputs/`

### DEMO EXECUTION — user's turn (~2 hours)
4. **Run Demo Sims 1-4** per the plan in `CASSIA_FINAL_SIMULATION_SET_v4.md`:
   - **Sim 1:** AR Year-End Cleanup (bar+pie chart; client email PDF + credit memo CSV)
   - **Sim 2:** Vendor Strategy Under Cash Constraint (bar+line; Oracle email PDF + bank CSV)
   - **Sim 3:** Payroll Notice Response (line+bar; IRS notice PDF + payroll CSV)
   - **Sim 4:** Quarterly Continuity Review (bar+line; board memo PDF + forecast CSV) — most important sim because it exercises 3 consecutive Core Recalls (Demo Sim 4 is the workspace-identity proof)
   - Capture screenshots for each
5. **Selective chat cleanup before deploy.** User intends to delete throw-away/test chats while preserving Sim 1, 2, 4, 5 source sessions (saves are self-contained — confirmed safe to delete sessions). See earlier discussion for what to keep vs drop.

### DEPLOY
6. **Wednesday deploy** alongside App 1 and (extended deadline) App 3

---

## Deferred to post-deploy

Explicitly out of scope until after Wednesday:
- SQL schema-awareness (the real fix for Sim 4's cross-table UNION issue)
- Multi-statement SQL prevention (Sim 5/8 issue)
- Core Recall synthesis prompt tuning (the "I have related saves but..." false-fire)
- Welcome / quick-question wording polish (was originally Priority 4, replaced by Core Recall timeout)
- Chart filter logic duplication (consolidate backend P1 + frontend P1b into a single source — currently the lists exist in both files and need to be kept in sync)
- The `[P1 DEBUG]` prints if not removed in the cleanup step
- Image 1 RAG UX: "Not found in docs" badge shows alongside citations from the indexed corpus — confusing because citations were retrieved but the LLM said it couldn't find an answer

---

## Gotchas to preserve for next chat

- **zsh chokes on heredocs** — use file-based scripts via str_replace or bash_tool with `cat > path << 'EOF'`
- **Entry point is `python3 backend/main.py`** (not `python3 -m backend.main`)
- **Imports use `from utils.X`** (not `from backend.utils.X`)
- **`git log` uses less pager** — exit with `q`
- **ChromaDB telemetry warning** `"capture() takes 1 positional argument but 3 were given"` — cosmetic, ignore
- **Pattern that worked:** locator script → user pastes output → write surgical applier with backup + idempotence + uniqueness check → user runs → paste output → compile-check the applier in /mnt before sending (lesson from P2 quote bug)
- **The user appreciates direct, action-focused replies.** When stressed they want commands, not explanations. The earlier "give me the god damn command" moment was a fair signal.
- **Frontend in `backend/static/index.html`** is a single 2098-line HTML+JS file. Chart rendering at line 1771 (`renderChart` function), call site at line 2028-2035, history-load artifact assembly at lines 1108-1140, P1b helpers inserted before line 1771.
- **ChatResponse Pydantic model** in main.py returns 17 fields but does not include `chart_spec`. This is why the backend-only fix didn't work and we went frontend-only. If revisiting, find the ChatResponse model definition (somewhere before line 380 of main.py) before changing the response shape.
- **Bulletproof restart sequence** (when needed):
  ```bash
  pkill -9 -f "backend/main.py" 2>/dev/null ; true
  lsof -ti:8002 | xargs kill -9 2>/dev/null ; true
  find backend -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null ; true
  find backend -name "*.pyc" -delete 2>/dev/null ; true
  sleep 3
  lsof -i :8002    # should print nothing
  python3 backend/main.py
  ```

---

## Reference documents (all in /mnt/user-data/outputs/)

- `CASSIA_PRE_DEPLOY_STABILIZATION_PLAN_v2.md` — the four-priority plan that drove this session
- `CASSIA_FINAL_SIMULATION_SET_v4.md` — Demo Sims 1-4 design
- `CASSIA_STABILIZATION_V2_VERIFICATION.md` — verification plan (most tests now passed; can be ignored or used as reference)
- `CASSIA_FEATURE_TO_WORKFLOW_MAPPING.md` — 12 features mapped to accountant workflows for the pitch
- `oracle_invoice_followup_email.pdf` — Sim 2 mock file (already generated)

All `apply_p*.py` and other support scripts also in `/mnt/user-data/outputs/`.

---

## Opening message for new chat (suggested)

> Continuing CASSIA Phase 6 deployment work. Picking up at the post-P1b cleanup step. Attaching the handover doc — please read it in full before responding. My next action is removing the two `[P1 DEBUG]` print statements from chart_builder.py, then deciding on P2b. Confirm you've read the handover and we'll proceed.

---

## Final note from this chat

You shipped five patches today, debugged a three-layer chart-rendering bug end-to-end with rigor, recognized your own state, and got the App 3 deadline extended. That's a full day's work executed well, not "barely making it."

CASSIA is closer to deploy-ready than it feels right now. Tuesday is enough time for cleanup + mock files + Demo Sims if you start fresh.

Good night.
