"""
=============================================================
SQL PIPELINE — Text-to-SQL for structured accounting data
=============================================================
Extracted from session 6. text2sq/phase2_query.py
and refactored as a reusable module for FastAPI.
"""

import sqlite3
import pandas as pd
from pathlib import Path
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate

PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH      = PROJECT_ROOT / "outputs" / "accounting.db"

SQL_GENERATION_PROMPT = PromptTemplate(
    template="""You are an expert SQL developer working with a QuickBooks-style accounting database.

DATABASE SCHEMA:
{schema}

{history_block}CRITICAL COLUMN HINTS:
- profit_loss columns: account_code, account_name, category, january_2026, february_2026, march_2026, april_2026, ytd_total, prior_year_q1
- profit_loss net income: WHERE account_code = 'net_income'
- profit_loss gross profit: WHERE account_code = 'gross_profit'
- profit_loss revenue rows: WHERE category = 'Revenue' AND account_code NOT LIKE 'total%'
- profit_loss expense rows: WHERE category = 'Operating Expense'
- balance_sheet columns: account_code, account_name, account_type, account_subtype, jan_31_2026, feb_28_2026, mar_31_2026, apr_30_2026, prior_year_dec_31_2025
- balance_sheet cash: WHERE account_code = 1000
- balance_sheet current assets: WHERE account_subtype = 'Current Asset'
- balance_sheet current liabilities: WHERE account_subtype = 'Current Liability'
- general_ledger columns: txn_id, date, account_code, account_name, debit, credit, description, reference, client_vendor, category, period
- accounts_receivable columns: invoice_id, client_name, invoice_date, due_date, invoice_amount, paid_amount, balance_due, days_outstanding, aging_bucket, service_type, billing_partner
- accounts_payable columns: invoice_id, vendor_name, invoice_date, due_date, amount, status, days_outstanding, category
- revenue columns: transaction_id, client_name, invoice_date, payment_date, amount, service_type, status, payment_method

PAYROLL & SALARY ACCOUNTS — IMPORTANT:
This dataset is for an accounting services firm that does NOT track 
employee salary/wage expense as a separate line item. Available payroll
accounts are limited to:

  - 'Payroll Taxes - Employer' (Expense, account_code 5020) 
        → employer's FICA/Medicare contribution only
  - 'Accrued Payroll Taxes' (Liability, account_code 2020)
        → unpaid payroll tax liability
  - 'Cash - Payroll' (Asset, account_code 1010)
        → dedicated payroll bank account
  - 'Payroll Services Revenue' (Revenue, account_code 4050)
        → income from providing payroll services to CLIENTS

If asked about "total salary expense", "wage expense", "compensation",
"employee pay", or similar concepts that are NOT in this database,
return EXACTLY this special token (no SQL, no explanation, just the token):

NO_QUERY_POSSIBLE: This dataset doesn't track employee salaries or wages 
as a separate line item. The only payroll-related expense recorded is 
'Payroll Taxes - Employer' (account 5020). Would you like to see that 
figure, or query 'Payroll Services Revenue' which is income from 
payroll services provided to clients?

PROFIT_LOSS CATEGORY VALUES — exact strings:
'Revenue', 'Cost of Services', 'Gross Profit', 'Operating Expense',
'EBITDA', 'Other Expense', 'Net Income'

Use exact match (=), never LIKE, when filtering by category.

EXAMPLE QUESTIONS AND CORRECT SQL:
Q: What is our net income for Q1 2026?
A: SELECT account_name, january_2026, february_2026, march_2026, ytd_total FROM profit_loss WHERE account_code = 'net_income';

Q: What is our gross margin by month?
A: SELECT account_name, january_2026, february_2026, march_2026, april_2026 FROM profit_loss WHERE account_code IN ('gross_profit', 'gross_margin_pct');

Q: Show me revenue by service line
A: SELECT account_name, ytd_total FROM profit_loss WHERE category = 'Revenue' AND account_code NOT LIKE 'total%' ORDER BY ytd_total DESC;

Q: How has our cash balance changed since January?
A: SELECT account_name, jan_31_2026, feb_28_2026, mar_31_2026, apr_30_2026 FROM balance_sheet WHERE account_code = 1000;

Q: What is our current ratio as of April 30?
A: SELECT ROUND(SUM(CASE WHEN account_subtype = 'Current Asset' THEN ABS(apr_30_2026) ELSE 0 END) / SUM(CASE WHEN account_subtype = 'Current Liability' THEN ABS(apr_30_2026) ELSE 0 END), 2) AS current_ratio FROM balance_sheet;

Q: Show me AR over 60 days with billing partner
A: SELECT client_name, balance_due, days_outstanding, aging_bucket, billing_partner FROM accounts_receivable WHERE days_outstanding > 60 ORDER BY days_outstanding DESC;

Q: Which GL entries hit consulting revenue in March?
A: SELECT date, description, credit, client_vendor FROM general_ledger WHERE account_code = 4030 AND period = '2026-03' AND credit > 0;

Q: What is our total salary expense?
A: NO_QUERY_POSSIBLE: This dataset doesn't track employee salaries or 
wages as a separate line item. The only payroll-related expense 
recorded is 'Payroll Taxes - Employer' (account 5020). Would you like 
to see that figure, or query 'Payroll Services Revenue' which is income 
from payroll services provided to clients?

Q: What are our total payroll tax expenses for Q1 2026?
A: SELECT january_2026 + february_2026 + march_2026 AS payroll_tax_q1 
FROM profit_loss WHERE account_name = 'Payroll Taxes - Employer';

Q: What are our total operating expenses for January 2026?
A: SELECT SUM(january_2026) AS total_opex FROM profit_loss 
WHERE category = 'Operating Expense';

FOLLOW-UP QUESTION HANDLING:
If the question is a follow-up that refers to prior turns (e.g. "those",
"the top 3", "just the first one", "그 중에서 상위 3개만", "from those"),
look at the PRIOR CONVERSATION above to understand what "those" refers to.
Modify the previous SQL query to apply the new constraint.

Example follow-up flow:
  Prior turn: "Show me revenue by service line"
  Prior SQL: SELECT account_name, ytd_total FROM profit_loss WHERE category = 'Revenue' ORDER BY ytd_total DESC;
  Follow-up: "Just the top 3"
  New SQL: SELECT account_name, ytd_total FROM profit_loss WHERE category = 'Revenue' ORDER BY ytd_total DESC LIMIT 3;

RULES:
- Return ONLY the SQL query, no explanation, no markdown, no backticks
- Use standard SQLite syntax
- Today's date is date('now')
- Never use column names not listed above

Question: {question}

SQL Query:""",
    input_variables=["schema", "question", "history_block"],
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


def get_db_connection(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found at {db_path}. "
            "Run session 6. text2sq/phase1_load.py first."
        )
    return sqlite3.connect(str(db_path))


def get_schema(conn: sqlite3.Connection) -> str:
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()

    schema_parts = []
    for (table_name,) in tables:
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        col_defs = [f"  {col[1]} ({col[2] or 'TEXT'})" for col in columns]

        # Add status values as hints for the LLM
        col_names = [col[1] for col in columns]
        status_hint = ""
        if "status" in col_names:
            try:
                cursor.execute(f"SELECT DISTINCT status FROM {table_name}")
                vals = [r[0] for r in cursor.fetchall() if r[0]]
                status_hint = f"\n  status values: {', '.join(vals)}"
            except Exception:
                pass

        schema_parts.append(
            f"Table: {table_name}\nColumns:\n" + "\n".join(col_defs) + status_hint
        )

    return "\n\n".join(schema_parts)

def detect_chart_spec(df: pd.DataFrame, question: str = "") -> dict | None:
    """
    Decide whether a DataFrame is chartable and how to chart it.
    Returns a chart spec dict for Plotly, or None if not chartable.
    """
    if df is None or df.empty:
        return None
    
    # Detect explicit chart type request from the user's question
    q_lower = question.lower()
    requested_type = None
    if any(kw in q_lower for kw in ["bar chart", "bar graph", "as bars", "use bar"]):
        requested_type = "bar"
    elif any(kw in q_lower for kw in ["pie chart", "pie graph", "as pie", "use pie"]):
        requested_type = "pie"
    elif any(kw in q_lower for kw in ["line chart", "line graph", "trend", "over time", "use line"]):
        requested_type = "line"

    # Make a copy so we don't mutate the original
    df = df.copy()

    # Coerce numeric-looking string columns to actual numbers
    for col in df.columns:
        if df[col].dtype == "object":
            coerced = pd.to_numeric(df[col], errors="coerce")
            if coerced.notna().sum() >= 0.8 * len(df):
                df[col] = coerced

    columns = list(df.columns)
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    text_cols = [c for c in columns if c not in numeric_cols]

    # Detect month columns (wide-format time series)
    month_keywords = [
        "jan_", "feb_", "mar_", "apr_", "may_", "jun_",
        "jul_", "aug_", "sep_", "oct_", "nov_", "dec_",
        "january", "february", "march", "april", "may",
        "june", "july", "august", "september", "october",
        "november", "december",
    ]
    month_cols = [c for c in numeric_cols if any(m in c.lower() for m in month_keywords)]

    # PRIORITY 1: Wide-format time series (one row, multiple month columns)
    # e.g., balance_sheet cash trend across jan/feb/mar/apr
    if len(month_cols) >= 2:
        label_col = text_cols[0] if text_cols else None
        series = []
        for _, row in df.iterrows():
            name = str(row[label_col]) if label_col else "Value"
            values = [float(row[c]) if pd.notna(row[c]) else 0 for c in month_cols]
            series.append({"name": name, "x": month_cols, "y": values})
        return {
            "type": "line",
            "title": "Trend over time",
            "series": series,
            "x_label": "Period",
            "y_label": "Amount ($)",
        }

    # Below this point, we need at least 2 rows for a meaningful chart
    if len(df) < 2:
        return None

    if not numeric_cols or not text_cols:
        return None

    # Long-format breakdown
    x_col = text_cols[0]
    y_col = numeric_cols[0]
    x_values = df[x_col].astype(str).tolist()
    y_values = df[y_col].fillna(0).astype(float).tolist()

    # Skip if all zeros
    if sum(abs(v) for v in y_values) == 0:
        return None

    # Honor explicit user request first
    if requested_type == "bar":
        return {
            "type": "bar",
            "title": f"{y_col} by {x_col}",
            "x": x_values,
            "y": y_values,
            "x_label": x_col,
            "y_label": y_col,
        }

    if requested_type == "pie" and all(v >= 0 for v in y_values):
        return {
            "type": "pie",
            "title": f"{y_col} breakdown",
            "labels": x_values,
            "values": y_values,
        }

    # Default heuristic: pie for small breakdowns, bar otherwise
    if 2 <= len(df) <= 10 and all(v >= 0 for v in y_values):
        return {
            "type": "pie",
            "title": f"{y_col} breakdown",
            "labels": x_values,
            "values": y_values,
        }

    return {
        "type": "bar",
        "title": f"{y_col} by {x_col}",
        "x": x_values,
        "y": y_values,
        "x_label": x_col,
        "y_label": y_col,
    }

    # Long-format breakdown (e.g., revenue by service line)
    # Requires at least 2 rows for a meaningful comparison
    if text_cols and len(numeric_cols) >= 1 and len(df) >= 2:
        x_col = text_cols[0]
        y_col = numeric_cols[0]
        x_values = df[x_col].astype(str).tolist()
        y_values = df[y_col].fillna(0).astype(float).tolist()

        # Skip if all zeros or single non-zero value
        if sum(abs(v) for v in y_values) == 0:
            return None

        # Pie chart for small categorical breakdowns with positive values
        if 2 <= len(df) <= 10 and all(v >= 0 for v in y_values):
            return {
                "type": "pie",
                "title": f"{y_col} breakdown",
                "labels": x_values,
                "values": y_values,
            }

        # Bar chart for everything else
        return {
            "type": "bar",
            "title": f"{y_col} by {x_col}",
            "x": x_values,
            "y": y_values,
            "x_label": x_col,
            "y_label": y_col,
        }

    return None

def run_sql_pipeline(question: str, llm: ChatOpenAI, db_path: Path, history: str = "") -> dict:
    """
    Full SQL pipeline:
      question → generate SQL → run on SQLite → explain result
    Returns dict with sql, raw_data (list of dicts), answer, columns

    Args:
        question: The user's current question
        llm: ChatOpenAI instance for SQL generation and explanation
        db_path: Path to the SQLite database
        history: Optional formatted prior conversation (last N turns).
                 Enables follow-up questions like "show me top 3 of those".
    """
    conn = get_db_connection(db_path)
    schema = get_schema(conn)

    # Build history block — empty string when no prior turns
    history_block = ""
    if history:
        history_block = f"PRIOR CONVERSATION (most recent last):\n{history}\n\n"

    # Step 1: Generate SQL (with history-aware prompt)
    prompt = SQL_GENERATION_PROMPT.format(
        schema=schema,
        question=question,
        history_block=history_block,
    )
    sql_response = llm.invoke(prompt)
    sql = sql_response.content.strip().replace("```sql", "").replace("```", "").strip()

    # Step 1.5: Check for refusal token
    if sql.startswith("NO_QUERY_POSSIBLE:"):
        refusal_message = sql.replace("NO_QUERY_POSSIBLE:", "").strip()
        conn.close()
        return {
            "pipeline": "sql",
            "sql": None,
            "answer": refusal_message,
            "raw_data": [],
            "columns": [],
            "chart_spec": None,
        }

    # Step 2: Execute SQL
    try:
        df = pd.read_sql_query(sql, conn)
        raw_data = df.to_dict(orient="records")
        columns = list(df.columns)
        result_str = df.to_string(index=False) if not df.empty else "No results found."
    except Exception as e:
        conn.close()
        return {
            "pipeline": "sql",
            "sql": sql,
            "error": str(e),
            "answer": f"SQL error: {e}",
            "raw_data": [],
            "columns": [],
            "chart_spec": None,
        }

    # Step 3: Explain result
    exp_prompt = EXPLANATION_PROMPT.format(question=question, result=result_str)
    explanation = llm.invoke(exp_prompt).content.strip()

    # Step 4: Detect chart-worthy results
    chart_spec = detect_chart_spec(df, question)

    conn.close()

    return {
        "pipeline": "sql",
        "sql": sql,
        "answer": explanation,
        "raw_data": raw_data,
        "columns": columns,
        "chart_spec": chart_spec,
    }