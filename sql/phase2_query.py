"""
=============================================================
TEXT-TO-SQL PHASE 2 — Natural Language → SQL → Answer
=============================================================

Mirrors RAG Phase 2, but for structured data.

Instead of:
  question → embed → ChromaDB similarity search → LLM → answer

We do:
  question → LLM generates SQL → run SQL on SQLite → LLM explains result → answer

The key difference: no embeddings needed. The LLM reads the
database schema and writes SQL directly. The SQL runs against
real data and returns exact numbers — no hallucination possible
on the numerical results.
"""

import os
import sqlite3
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table

from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate

load_dotenv()
console = Console()

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH      = PROJECT_ROOT / "outputs" / "accounting.db"


# ── Prompt: Schema + question → SQL ───────────────────────
# This is the core of Text-to-SQL.
# We give the LLM: (1) the schema, (2) the question.
# It returns: a valid SQL query.
SQL_GENERATION_PROMPT = PromptTemplate(
    template="""You are an expert SQL developer working with a QuickBooks-style accounting database.

DATABASE SCHEMA:
{schema}

IMPORTANT RULES:
- Return ONLY the SQL query, no explanation, no markdown, no backticks
- Use standard SQLite syntax
- For date comparisons use: date('now') or string comparison like >= '2026-01-01'
- Column names are exactly as shown in the schema
- Today's date is 2026-04-30

Question: {question}

SQL Query:""",
    input_variables=["schema", "question"],
)

# ── Prompt: SQL result → plain English explanation ─────────
EXPLANATION_PROMPT = PromptTemplate(
    template="""You are a helpful accounting assistant. 
A user asked this question about their QuickBooks data:
"{question}"

The SQL query ran and returned this result:
{result}

Write a clear, concise plain-English answer (2-4 sentences).
Focus on the business insight, not the technical details.
If the result has dollar amounts, format them with $ and commas.""",
    input_variables=["question", "result"],
)


def get_schema(conn: sqlite3.Connection) -> str:
    """
    Build a schema string to give the LLM context.
    This is the TEXT-TO-SQL equivalent of the RAG chunks —
    it's the context the LLM needs to write accurate SQL.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()

    schema_parts = []
    for (table_name,) in tables:
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()

        col_defs = [f"  {col[1]} ({col[2] or 'TEXT'})" for col in columns]
        schema_parts.append(f"Table: {table_name}\nColumns:\n" + "\n".join(col_defs))

        # Add sample values so LLM knows what's in the data
        cursor.execute(f"SELECT DISTINCT status FROM {table_name} LIMIT 10") \
            if "status" in [col[1] for col in columns] else None
        try:
            sample = cursor.fetchall()
            if sample:
                vals = [str(r[0]) for r in sample if r[0]]
                schema_parts[-1] += f"\n  (status values: {', '.join(vals)})"
        except Exception:
            pass

    return "\n\n".join(schema_parts)


def generate_sql(llm: ChatOpenAI, schema: str, question: str) -> str:
    """Step 1: LLM reads schema + question → writes SQL."""
    prompt = SQL_GENERATION_PROMPT.format(schema=schema, question=question)
    response = llm.invoke(prompt)
    sql = response.content.strip()

    # Clean up any accidental markdown the LLM might add
    sql = sql.replace("```sql", "").replace("```", "").strip()
    return sql


def run_sql(conn: sqlite3.Connection, sql: str) -> pd.DataFrame:
    """Step 2: Run the generated SQL against the real database."""
    return pd.read_sql_query(sql, conn)


def explain_result(llm: ChatOpenAI, question: str, result_df: pd.DataFrame) -> str:
    """Step 3: LLM reads the SQL result → writes plain English explanation."""
    result_str = result_df.to_string(index=False) if not result_df.empty else "No results found."
    prompt = EXPLANATION_PROMPT.format(question=question, result=result_str)
    response = llm.invoke(prompt)
    return response.content.strip()


def ask(conn: sqlite3.Connection, llm: ChatOpenAI, schema: str, question: str, q_num: int):
    """Full pipeline: question → SQL → run → explain → display."""
    console.print(f"\n[bold white]── Question {q_num} ──────────────────────────────────────────[/bold white]")
    console.print(f"[bold yellow]❓ {question}[/bold yellow]\n")

    # Step 1: Generate SQL
    sql = generate_sql(llm, schema, question)
    console.print(f"[dim]🔧 Generated SQL:[/dim]")
    console.print(f"[dim cyan]   {sql}[/dim cyan]\n")

    # Step 2: Run SQL
    try:
        result_df = run_sql(conn, sql)
    except Exception as e:
        console.print(f"[bold red]❌ SQL Error: {e}[/bold red]")
        return

    # Step 3: Show raw data table
    if not result_df.empty:
        table = Table(show_lines=True, style="dim")
        for col in result_df.columns:
            table.add_column(col, style="cyan")
        for _, row in result_df.iterrows():
            table.add_row(*[str(v) if pd.notna(v) else "" for v in row])
        console.print("[dim]📊 Raw query result:[/dim]")
        console.print(table)

    # Step 4: Plain English explanation
    explanation = explain_result(llm, question, result_df)
    console.print(Panel(
        Text(explanation, style="white"),
        title="[bold green]💡 Answer[/bold green]",
        border_style="green",
        padding=(1, 2),
    ))


def run_demo_questions(conn, llm, schema):
    """
    5 demo questions covering real accounting use cases for App 2.
    These mirror what a user would actually ask in the chatbot.
    """
    questions = [
        # Q1: Classic AP aging question — the headline feature of App 2
        "What invoices are in our accounts payable that are overdue by more than 60 days?",

        # Q2: Revenue summary — period-based aggregation
        "What is our total revenue from January to March 2026?",

        # Q3: Vendor analysis — grouping and ranking
        "Which vendor do we owe the most money to right now?",

        # Q4: Cash flow — category breakdown
        "Break down our expenses by category for all outstanding and overdue invoices.",

        # Q5: Revenue by service type — business intelligence
        "Which service type generates the most revenue for us?",
    ]

    for i, question in enumerate(questions, 1):
        ask(conn, llm, schema, question, i)

    console.print("\n[bold green]✅ All 5 demo questions answered![/bold green]")


def interactive_mode(conn, llm, schema):
    """Ask your own questions in plain English."""
    console.print("\n[bold cyan]═══════════════════════════════════════════════════[/bold cyan]")
    console.print("[bold cyan]  Interactive Mode — ask your own questions         [/bold cyan]")
    console.print("[bold cyan]  Type 'quit' to exit                               [/bold cyan]")
    console.print("[bold cyan]═══════════════════════════════════════════════════[/bold cyan]\n")

    q_num = 6
    while True:
        try:
            question = console.input("[bold yellow]You: [/bold yellow]").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not question or question.lower() in ("quit", "exit", "q"):
            console.print("\n[dim]Goodbye![/dim]")
            break

        ask(conn, llm, schema, question, q_num)
        q_num += 1


def main():
    console.print("[bold white]═══════════════════════════════════════════════════[/bold white]")
    console.print("[bold white]  TEXT-TO-SQL PHASE 2 — Natural Language Q&A      [/bold white]")
    console.print("[bold white]  QuickBooks Data → Plain English Answers          [/bold white]")
    console.print("[bold white]═══════════════════════════════════════════════════[/bold white]")

    if not os.getenv("OPENAI_API_KEY"):
        console.print("\n[bold red]❌ OPENAI_API_KEY not found in .env[/bold red]")
        return

    if not DB_PATH.exists():
        console.print(f"\n[bold red]❌ Database not found. Run phase1_load.py first.[/bold red]")
        return

    console.print("\n[bold cyan]🗄  Connecting to database...[/bold cyan]")
    conn = sqlite3.connect(str(DB_PATH))
    schema = get_schema(conn)
    console.print("   ✓ Connected to accounting.db")
    console.print(f"   ✓ Schema loaded: {len(schema)} chars")

    console.print("\n[bold cyan]🔗 Initializing LLM...[/bold cyan]")
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
    )
    console.print("   ✓ GPT-4o-mini ready")

    run_demo_questions(conn, llm, schema)
    interactive_mode(conn, llm, schema)

    conn.close()


if __name__ == "__main__":
    main()
