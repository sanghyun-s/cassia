"""
=============================================================
SQL PIPELINE — Text-to-SQL for structured accounting data
=============================================================

Phase 3 close-out polish:
  - Detect upload-related questions; short-circuit cleanly when no
    uploads exist (prevents LLM hallucinating user_data.revenue)
  - Append no_data nudge suggesting 📎 upload when zero rows returned
"""

import re
import sqlite3
import pandas as pd
from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate

from uploads.session_db import session_db_path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH      = PROJECT_ROOT / "outputs" / "accounting.db"

# ── Table-level descriptions ───────────────────────────────
TABLE_DESCRIPTIONS = {
    "profit_loss": (
        "Monthly P&L by account. "
        "Time columns are: january_2026, february_2026, march_2026, april_2026, ytd_total, prior_year_q1. "
        "There is NO date column. To query by time use the month columns directly. "
        "Key account_code values: 'net_income', 'gross_profit', 'gross_margin_pct', 'ebitda', 'total_revenue', 'total_cos', 'total_opex'. "
        "Revenue rows: category = 'Revenue' AND account_code NOT LIKE 'total%'. "
        "Expense rows: category = 'Operating Expense'. "
        "Cost of services: category = 'Cost of Services'."
    ),
    "balance_sheet": (
        "Monthly balance sheet snapshots. "
        "Balance columns: jan_31_2026, feb_28_2026, mar_31_2026, apr_30_2026, prior_year_dec_31_2025. "
        "There is NO date column. Use balance columns for time comparisons. "
        "account_subtype values: 'Current Asset', 'Fixed Asset', 'Other Asset', "
        "'Current Liability', 'Long-Term Liability', 'Equity'. "
        "Cash account: account_code = 1000. "
        "Current ratio: SUM current assets / SUM ABS(current liabilities)."
    ),
    "general_ledger": (
        "Double-entry transactions. Each transaction has a debit or credit entry. "
        "Date column is 'date' (TEXT, format YYYY-MM-DD). "
        "Period column is 'period' (TEXT, format YYYY-MM, e.g. '2026-03'). "
        "Revenue accounts: account_code BETWEEN 4000 AND 4999. "
        "Expense accounts: account_code BETWEEN 5000 AND 5999."
    ),
    "accounts_receivable": (
        "Outstanding client invoices. "
        "aging_bucket values: 'Current', '31-60 Days', '61-90 Days', '90+ Days'. "
        "balance_due = amount still owed after partial payments. "
        "billing_partner = staff member responsible."
    ),
    "accounts_payable": (
        "Vendor invoices. "
        "status values: 'Paid', 'Outstanding', 'Overdue'. "
        "days_outstanding = days since invoice date."
    ),
    "revenue": (
        "Client invoice detail. "
        "service_type values: 'Accounting Services', 'Audit Services', 'Tax Preparation', "
        "'Consulting', 'Bookkeeping', 'Payroll Services'. "
        "status values: 'Paid', 'Pending'."
    ),
    "chart_of_accounts": (
        "Account master list. "
        "account_type values: 'Asset', 'Liability', 'Equity', 'Revenue', 'Expense'. "
        "normal_balance values: 'Debit', 'Credit'."
    ),
    "journal_entries": (
        "Legacy journal entries table from earlier dataset version. "
        "Prefer general_ledger for transaction queries."
    ),
}

STRUCTURAL_EXAMPLES = """
STRUCTURAL PATTERNS (use these shapes, substitute real column names from schema above):

Pattern: Trend over months from profit_loss
Q: Show net income trend / Show X as a line chart (when X is in profit_loss)
A: SELECT account_name, january_2026, february_2026, march_2026, april_2026
   FROM profit_loss WHERE account_code = 'net_income';

Pattern: Revenue breakdown
Q: Revenue by service line / What services generate the most revenue?
A: SELECT account_name, ytd_total FROM profit_loss
   WHERE category = 'Revenue' AND account_code NOT LIKE 'total%'
   ORDER BY ytd_total DESC;

Pattern: Balance sheet comparison across months
Q: How has X changed since January? / X balance over time
A: SELECT account_name, jan_31_2026, feb_28_2026, mar_31_2026, apr_30_2026
   FROM balance_sheet WHERE account_code = [relevant code];

Pattern: Current ratio
Q: What is our current ratio?
A: SELECT ROUND(
     SUM(CASE WHEN account_subtype='Current Asset' THEN ABS(apr_30_2026) ELSE 0 END) /
     SUM(CASE WHEN account_subtype='Current Liability' THEN ABS(apr_30_2026) ELSE 0 END)
   ,2) AS current_ratio FROM balance_sheet;

Pattern: AR aging
Q: AR over X days / overdue receivables
A: SELECT client_name, balance_due, days_outstanding, aging_bucket, billing_partner
   FROM accounts_receivable WHERE days_outstanding > [X] ORDER BY days_outstanding DESC;
"""

USER_DATA_EXAMPLES_HEADER = """
USER UPLOAD QUERY PATTERNS (only valid when USER UPLOADED TABLES section is non-empty):

Pattern: How many rows in my uploaded data
A: SELECT COUNT(*) FROM user_data.revenue_2;
   -- 'revenue_2' is just an example. Replace with an actual table name from USER UPLOADED TABLES.

Pattern: Total amount in my uploaded data
A: SELECT SUM(amount) FROM user_data.revenue_2;
   -- Replace 'amount' with a real numeric column listed in USER UPLOADED TABLES.

Pattern: Show contents of my uploaded data
A: SELECT * FROM user_data.revenue_2 LIMIT 20;
"""

SQL_GENERATION_PROMPT = PromptTemplate(
    template="""You are an expert SQL developer for a QuickBooks-style accounting database.

DATABASE SCHEMA WITH DESCRIPTIONS:
{schema}

{user_schema_block}

{structural_examples}

{user_data_examples}

RULES:
- Return ONLY the SQL query — no explanation, no markdown, no backticks
- Use SQLite syntax
- Use ONLY column names that appear in the schema above
- profit_loss has NO date column — NEVER use WHERE date or ORDER BY date on profit_loss
- For profit_loss trends: SELECT account_name, january_2026, february_2026, march_2026, april_2026 FROM profit_loss WHERE account_code = 'net_income'
- For balance_sheet time queries: use jan_31_2026/feb_28_2026/mar_31_2026/apr_30_2026 — never 'date'
- For general_ledger time queries: use the 'date' or 'period' column
- Today's date is date('now')
- For tables under USER UPLOADED TABLES, prefix with user_data. and use the EXACT table and column names listed there
- NEVER invent a table or column name. If the user asks about uploaded data but USER UPLOADED TABLES is empty or absent, return exactly: SELECT 'No uploaded data in this session.' AS message;

Question: {question}

SQL Query:""",
    input_variables=["schema", "user_schema_block", "structural_examples",
                     "user_data_examples", "question"],
)

EXPLANATION_PROMPT = PromptTemplate(
    template="""You are a helpful accounting assistant.
A user asked: "{question}"

The SQL query returned:
{result}

Write a clear, concise plain-English answer (2-4 sentences).
Focus on the business insight. Format dollar amounts with $ and commas.
If the result is empty, say no matching records were found.""",
    input_variables=["question", "result"],
)

# Phrases that signal the user is asking about THEIR uploaded data.
# When matched AND no uploads exist, we short-circuit before the LLM
# can hallucinate a user_data.* table name.
UPLOAD_KEYWORDS = [
    "uploaded", "upload", "my csv", "my excel", "my file",
    "my data", "the data i uploaded", "the file i uploaded",
    "user data", "user_data",
]

NO_UPLOAD_NUDGE = (
    " This data isn't in the demo tables — to query data of your own, click 📎 "
    "in the chat composer to upload a CSV or Excel file."
)


def get_db_connection(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found at {db_path}. "
            "Run sql/phase1_load.py first."
        )
    return sqlite3.connect(str(db_path))


def get_enriched_schema(conn: sqlite3.Connection) -> str:
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()

    schema_parts = []
    for (table_name,) in tables:
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        col_defs = [f"  {col[1]} ({col[2] or 'TEXT'})" for col in columns]

        col_names = [col[1] for col in columns]
        value_hints = []
        for col_name in col_names:
            if any(kw in col_name.lower() for kw in
                   ["status", "type", "category", "subtype", "bucket",
                    "method", "standard", "bucket", "by", "partner"]):
                try:
                    cursor.execute(
                        f"SELECT DISTINCT {col_name} FROM {table_name} "
                        f"WHERE {col_name} IS NOT NULL LIMIT 8"
                    )
                    vals = [str(r[0]) for r in cursor.fetchall() if r[0]]
                    if vals:
                        value_hints.append(f"  {col_name} sample values: {', '.join(vals)}")
                except Exception:
                    pass

        description = TABLE_DESCRIPTIONS.get(table_name, "")
        part = f"Table: {table_name}"
        if description:
            part += f"\nDescription: {description}"
        part += "\nColumns:\n" + "\n".join(col_defs)
        if value_hints:
            part += "\nSample values:\n" + "\n".join(value_hints)

        schema_parts.append(part)

    return "\n\n".join(schema_parts)


def get_schema(conn: sqlite3.Connection) -> str:
    return get_enriched_schema(conn)


# ── User-uploaded table support ────────────────────────────

def _attach_user_db(conn: sqlite3.Connection, session_id: str | None) -> bool:
    """ATTACH the session DB as 'user_data' if it exists."""
    if not session_id:
        return False
    user_db = session_db_path(session_id)
    if not user_db.exists():
        return False
    try:
        conn.execute(f"ATTACH DATABASE '{user_db}' AS user_data")
        return True
    except sqlite3.Error as e:
        print(f"[sql_pipeline] ATTACH user_data failed: {e}")
        return False


def _infer_user_col_type(conn: sqlite3.Connection, table: str, col: str) -> str:
    """Sniff first non-null value to label as INTEGER/REAL/TEXT for the prompt."""
    try:
        row = conn.execute(
            f'SELECT "{col}" FROM user_data."{table}" '
            f'WHERE "{col}" IS NOT NULL LIMIT 1'
        ).fetchone()
    except sqlite3.Error:
        return "TEXT"
    if not row or row[0] is None:
        return "TEXT"
    val = row[0]
    if isinstance(val, bool):     return "INTEGER"
    if isinstance(val, int):      return "INTEGER"
    if isinstance(val, float):    return "REAL"
    return "TEXT"


def _get_user_tables_schema(conn: sqlite3.Connection) -> str:
    """Describe attached user_data tables for the prompt. Empty string if none."""
    try:
        rows = conn.execute(
            "SELECT name FROM user_data.sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
    except sqlite3.Error:
        return ""

    if not rows:
        return ""

    parts = ["USER UPLOADED TABLES (query as user_data.<table_name>):"]
    for (table_name,) in rows:
        try:
            cursor = conn.execute(f'SELECT * FROM user_data."{table_name}" LIMIT 0')
            col_names = [d[0] for d in (cursor.description or [])]
        except sqlite3.Error as e:
            parts.append(f"Table: user_data.{table_name}  (could not inspect: {e})")
            continue

        col_lines = []
        for c in col_names:
            t = _infer_user_col_type(conn, table_name, c)
            col_lines.append(f"  {c} ({t})")

        try:
            (row_count,) = conn.execute(
                f'SELECT COUNT(*) FROM user_data."{table_name}"'
            ).fetchone()
        except sqlite3.Error:
            row_count = "unknown"

        parts.append(
            f"Table: user_data.{table_name}  ({row_count} rows)\n"
            + "Columns:\n" + "\n".join(col_lines)
        )

    return "\n\n".join(parts)


def _question_targets_uploads(question: str) -> bool:
    """Heuristic: did the user ask about THEIR uploaded data specifically?"""
    q = question.lower()
    q_clean = re.sub(r"[^\w\s]", " ", q)
    return any(kw in q_clean for kw in UPLOAD_KEYWORDS)


def _infer_chart_hint(columns: list, raw_data: list, question: str) -> str:
    q = question.lower()
    if "pie" in q:    return "pie"
    if "line" in q or "trend" in q or "over time" in q: return "line"
    if "bar" in q:    return "bar"

    if not raw_data or not columns:
        return "none"
    if len(raw_data) == 1 and len(columns) == 1:
        return "none"

    numeric_cols     = []
    categorical_cols = []
    for col in columns:
        try:
            vals       = [row[col] for row in raw_data if row.get(col) is not None]
            float_vals = [float(v) for v in vals if str(v) != ""]
            if len(float_vals) / max(len(vals), 1) > 0.7:
                numeric_cols.append(col)
            else:
                categorical_cols.append(col)
        except (ValueError, TypeError):
            categorical_cols.append(col)

    month_keywords = ["january","february","march","april","may","june",
                      "july","august","september","october","november","december",
                      "jan_","feb_","mar_","apr_","2026","2025"]
    if any(any(kw in c.lower() for kw in month_keywords) for c in columns):
        return "line"
    if len(columns) == 2 and categorical_cols and numeric_cols and len(raw_data) <= 15:
        return "bar"
    if len(raw_data) > 1 and numeric_cols and len(raw_data) <= 20:
        return "bar"

    return "none"


def run_sql_pipeline(
    question:   str,
    llm:        ChatOpenAI,
    db_path:    Path,
    session_id: str | None = None,
) -> dict:
    """
    Full SQL pipeline. If session_id is provided AND that session has user
    uploads, the user DB is ATTACH-ed as 'user_data' and its tables are
    queryable as user_data.<table>.
    """
    conn = get_db_connection(db_path)

    attached           = _attach_user_db(conn, session_id)
    schema             = get_enriched_schema(conn)
    user_schema_block  = _get_user_tables_schema(conn) if attached else ""
    user_data_examples = USER_DATA_EXAMPLES_HEADER if user_schema_block else ""

    # ── Short-circuit: question about uploads, but no uploads attached ──
    # Done in code (not via prompt) because LLMs sometimes ignore the rule
    # and hallucinate user_data.revenue from prior conversation context.
    if _question_targets_uploads(question) and not user_schema_block:
        conn.close()
        return {
            "pipeline":      "sql",
            "response_type": "no_data",
            "chart_hint":    "none",
            "sql":           "-- no uploads in this session",
            "answer": (
                "There's no uploaded data in this session yet."
                + NO_UPLOAD_NUDGE
            ),
            "raw_data":      [],
            "columns":       [],
        }

    prompt = SQL_GENERATION_PROMPT.format(
        schema              = schema,
        user_schema_block   = user_schema_block,
        structural_examples = STRUCTURAL_EXAMPLES,
        user_data_examples  = user_data_examples,
        question            = question,
    )
    sql_response = llm.invoke(prompt)
    sql          = sql_response.content.strip().replace("```sql","").replace("```","").strip()

    try:
        df         = pd.read_sql_query(sql, conn)
        raw_data   = df.to_dict(orient="records")
        columns    = list(df.columns)
        result_str = df.to_string(index=False) if not df.empty else "No results found."
    except Exception as e:
        conn.close()
        return {
            "pipeline":      "sql",
            "response_type": "sql_error",
            "chart_hint":    "none",
            "sql":           sql,
            "error":         str(e),
            "answer":        f"The query could not be executed: {e}",
            "raw_data":      [],
            "columns":       [],
        }

    conn.close()

    response_type = "no_data" if df.empty else "answer"
    chart_hint    = _infer_chart_hint(columns, raw_data, question)

    exp_prompt  = EXPLANATION_PROMPT.format(question=question, result=result_str)
    explanation = llm.invoke(exp_prompt).content.strip()

    # ── C5 nudge: append a soft hint when no rows were returned ──
    # Only nudge if the user is NOT asking about uploads (already handled above).
    if response_type == "no_data" and not _question_targets_uploads(question):
        explanation = explanation.rstrip(".") + "." + NO_UPLOAD_NUDGE

    return {
        "pipeline":      "sql",
        "response_type": response_type,
        "chart_hint":    chart_hint,
        "sql":           sql,
        "answer":        explanation,
        "raw_data":      raw_data,
        "columns":       columns,
    }
