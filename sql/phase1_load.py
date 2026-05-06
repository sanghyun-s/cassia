"""
=============================================================
TEXT-TO-SQL PHASE 1 — Load All Accounting Tables → SQLite
=============================================================

Loads 7 QuickBooks-style tables into accounting.db:
  1. chart_of_accounts    — full COA with account types
  2. general_ledger       — every transaction double-entry
  3. balance_sheet        — monthly snapshots Jan–Apr 2026
  4. profit_loss          — monthly P&L by service line
  5. accounts_receivable  — AR aging with buckets
  6. accounts_payable     — AP with overdue tracking
  7. revenue              — client invoice detail
"""

import os
import sqlite3
import pandas as pd
from pathlib import Path
from rich.console import Console
from rich.table import Table

console = Console()

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR     = PROJECT_ROOT / "data"
DB_PATH      = PROJECT_ROOT / "outputs" / "accounting.db"

# All tables to load — order matters for foreign key logic
TABLES = [
    ("chart_of_accounts.csv",   "chart_of_accounts"),
    ("general_ledger.csv",      "general_ledger"),
    ("balance_sheet.csv",       "balance_sheet"),
    ("profit_loss.csv",         "profit_loss"),
    ("accounts_receivable.csv", "accounts_receivable"),
    ("accounts_payable.csv",    "accounts_payable"),
    ("revenue.csv",             "revenue"),
]


def load_csv_to_table(conn, csv_path, table_name):
    console.print(f"\n[bold cyan]📂 Loading:[/bold cyan] {csv_path.name} → '{table_name}'")
    df = pd.read_csv(csv_path)
    df.to_sql(table_name, conn, if_exists="replace", index=False)
    console.print(f"   ✓ {len(df)} rows, {len(df.columns)} columns")
    console.print(f"   ✓ Columns: {', '.join(df.columns.tolist()[:6])}{'...' if len(df.columns) > 6 else ''}")
    return df


def show_schema(conn):
    console.print("\n[bold cyan]📋 Database schema summary:[/bold cyan]\n")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()

    summary = Table(title="All Tables", show_lines=True)
    summary.add_column("Table",   style="cyan",  width=25)
    summary.add_column("Rows",    style="green", width=8)
    summary.add_column("Key columns", width=55)

    for (tname,) in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {tname}")
        row_count = cursor.fetchone()[0]
        cursor.execute(f"PRAGMA table_info({tname})")
        cols = [c[1] for c in cursor.fetchall()]
        summary.add_row(tname, str(row_count), ", ".join(cols[:5]) + ("..." if len(cols) > 5 else ""))

    console.print(summary)


def run_verification_queries(conn):
    console.print("\n[bold cyan]🔍 Verification queries:[/bold cyan]\n")

    queries = [
        (
            "Total revenue by service line (P&L)",
            """SELECT account_name,
                      printf('$%,.0f', january_2026) as Jan,
                      printf('$%,.0f', february_2026) as Feb,
                      printf('$%,.0f', march_2026) as Mar,
                      printf('$%,.0f', april_2026) as Apr,
                      printf('$%,.0f', ytd_total) as YTD
               FROM profit_loss
               WHERE category = 'Revenue'
               AND account_code NOT LIKE 'total%'"""
        ),
        (
            "AR aging summary by bucket",
            """SELECT aging_bucket,
                      COUNT(*) as invoices,
                      printf('$%,.0f', SUM(balance_due)) as total_balance
               FROM accounts_receivable
               GROUP BY aging_bucket
               ORDER BY CASE aging_bucket
                 WHEN 'Current' THEN 1
                 WHEN '31-60 Days' THEN 2
                 WHEN '61-90 Days' THEN 3
                 WHEN '90+ Days' THEN 4 END"""
        ),
        (
            "Balance sheet - total assets vs liabilities Apr 30",
            """SELECT account_type,
                      printf('$%,.0f', SUM(apr_30_2026)) as apr_30_balance
               FROM balance_sheet
               GROUP BY account_type"""
        ),
        (
            "General ledger - top 5 revenue transactions",
            """SELECT date, account_name, credit as amount, description, client_vendor
               FROM general_ledger
               WHERE account_code BETWEEN 4000 AND 4900
               AND credit > 0
               ORDER BY credit DESC
               LIMIT 5"""
        ),
        (
            "Net income by month",
            """SELECT 'Net Income' as metric,
                      printf('$%,.0f', january_2026) as January,
                      printf('$%,.0f', february_2026) as February,
                      printf('$%,.0f', march_2026) as March,
                      printf('$%,.0f', april_2026) as April,
                      printf('$%,.0f', ytd_total) as YTD
               FROM profit_loss WHERE account_code = 'net_income'"""
        ),
    ]

    for label, sql in queries:
        console.print(f"[bold yellow]→ {label}[/bold yellow]")
        df = pd.read_sql_query(sql, conn)
        console.print(df.to_string(index=False))
        console.print()


def main():
    console.print("[bold white]═══════════════════════════════════════════════════[/bold white]")
    console.print("[bold white]  TEXT-TO-SQL PHASE 1 — Full Accounting Dataset    [/bold white]")
    console.print("[bold white]  7 Tables: COA, GL, BS, P&L, AR, AP, Revenue     [/bold white]")
    console.print("[bold white]═══════════════════════════════════════════════════[/bold white]")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    if DB_PATH.exists():
        DB_PATH.unlink()
        console.print(f"\n[yellow]⚠ Removed existing database, rebuilding...[/yellow]")

    conn = sqlite3.connect(str(DB_PATH))

    missing = []
    for csv_file, table_name in TABLES:
        csv_path = DATA_DIR / csv_file
        if not csv_path.exists():
            missing.append(csv_file)
        else:
            load_csv_to_table(conn, csv_path, table_name)

    if missing:
        console.print(f"\n[bold red]❌ Missing CSV files:[/bold red]")
        for f in missing:
            console.print(f"   {DATA_DIR / f}")
        console.print("\n[yellow]Copy all CSV files to the data/ folder and retry.[/yellow]")
        conn.close()
        return

    conn.commit()
    show_schema(conn)
    run_verification_queries(conn)
    conn.close()

    console.print("[bold green]✅ Phase 1 complete — 7 tables loaded![/bold green]")
    console.print("[green]   Run [bold]python phase2_query.py[/bold] to ask questions.[/green]\n")


if __name__ == "__main__":
    main()
