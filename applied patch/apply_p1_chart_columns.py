#!/usr/bin/env python3
"""
Stabilization v2 — Priority 1: chart-builder column selection.

Adds column filtering to build_chart_spec() so only accounting measure
columns + the label column appear in the chart_spec sent to the frontend.
Prevents over-inclusive multi-series charts where date/id/category
columns render as near-zero bars alongside the real accounting amount.

Modifications to backend/pipelines/chart_builder.py:
  + PREFERRED_MEASURE_COLUMNS, AVOID_AS_MEASURE_COLUMNS, and
    EXPLICIT_COLUMN_REQUEST_PATTERN constants (after _MONTH_COLUMN_KEYWORDS)
  + _select_chart_columns() helper — picks columns based on explicit user
    request, monthly-line-chart shape, or PREFERRED/AVOID heuristic
  + build_chart_spec() updated to subset both columns and rows via the
    helper before packaging

Safety:
  - Backs up chart_builder.py with timestamped suffix
  - Idempotent — re-running on patched file does nothing
  - Pattern uniqueness checks before applying
  - Defensive fallback: if no usable measure column is identified,
    returns all columns unchanged so the chart still renders

Run from app2/ project root:
    python3 apply_p1_chart_columns.py
"""

import shutil
import sys
from pathlib import Path
from datetime import datetime


PROJECT_ROOT = Path.cwd()
FILE_PATH    = PROJECT_ROOT / "backend" / "pipelines" / "chart_builder.py"


CONSTANTS_BLOCK = '''

# ── v2 stabilization: column selection for chart_spec ─────────
# Accounting measure columns we want to chart, lowercased.
PREFERRED_MEASURE_COLUMNS = (
    "balance_due", "amount", "debit", "credit", "revenue", "expense",
    "total", "net_income", "ytd_total", "payment_amount",
    "invoice_amount", "cash_balance", "outstanding_balance",
    "january_2026", "february_2026", "march_2026", "april_2026",
    "jan_31_2026", "feb_28_2026", "mar_31_2026", "apr_30_2026",
)

# Identifier / date / categorical columns we should never chart as a
# numeric measure, even when they happen to parse as numeric.
AVOID_AS_MEASURE_COLUMNS = (
    "date", "due_date", "invoice_date", "payment_date", "period",
    "account_code", "customer_id", "vendor_id", "client_id",
    "days_outstanding", "aging_bucket", "txn_id", "id",
    "reference", "category",
)

# Detects explicit user requests like "only balance_due" or
# "only debit and credit" — when matched, honor the request.
EXPLICIT_COLUMN_REQUEST_PATTERN = re.compile(
    r"\\bonly\\s+([\\w_]+(?:\\s+and\\s+[\\w_]+)*)", re.I
)
'''


OLD_BUILD = '''def build_chart_spec(columns, rows, question: str, chart_hint: str) -> dict:
    """
    Package the chart payload for the frontend's renderChart().

    Does NOT reorder rows — assumes upstream already called reorder_for_chart
    so that the data table and the chart show consistent ordering.
    """
    return {
        "chart_type": chart_hint,
        "columns":    columns,
        "rows":       rows,
        "question":   question,
    }'''


NEW_BUILD = '''def _select_chart_columns(columns, rows, question, chart_hint):
    """
    Pick which columns should appear in the chart_spec.

    Priority:
      1. Explicit user request — "only balance_due", "only debit and credit"
         → use those numeric columns + the first categorical column for label
      2. Monthly/trend line chart — pass through all columns unchanged
         (the month-name detection already produced the right wide shape)
      3. Heuristic — label column + PREFERRED_MEASURE_COLUMNS, falling back
         to safe numeric columns. AVOID_AS_MEASURE_COLUMNS are never
         charted as measures.

    Returns the list of column names to keep. The caller subsets rows.

    Defensive fallback: if no usable measure column is identified, returns
    all columns unchanged so the chart still renders (preserves prior
    behavior in edge cases).
    """
    if not columns or not rows:
        return columns

    # 1. Explicit user request
    explicit_match = EXPLICIT_COLUMN_REQUEST_PATTERN.search(question or "")
    if explicit_match:
        requested_text = explicit_match.group(1).lower()
        tokens = [t.strip() for t in re.split(r"\\s+and\\s+|\\s*,\\s*",
                                              requested_text) if t.strip()]
        col_lower_map = {c.lower(): c for c in columns}
        requested = [col_lower_map[t] for t in tokens if t in col_lower_map]
        if requested:
            _num, categorical_cols = _classify_columns(columns, rows)
            keep = list(categorical_cols[:1]) if categorical_cols else []
            for c in requested:
                if c not in keep:
                    keep.append(c)
            return keep

    # 2. Monthly/trend line chart — preserve the wide shape
    if chart_hint == "line":
        if any(any(kw in c.lower() for kw in _MONTH_COLUMN_KEYWORDS)
               for c in columns):
            return columns

    # 3. Heuristic filtering
    numeric_cols, categorical_cols = _classify_columns(columns, rows)
    keep = list(categorical_cols[:1]) if categorical_cols else []

    avoid_set     = set(AVOID_AS_MEASURE_COLUMNS)
    preferred_set = set(PREFERRED_MEASURE_COLUMNS)

    preferred_hits = [c for c in numeric_cols if c.lower() in preferred_set]
    safe_hits      = [c for c in numeric_cols
                      if c.lower() not in avoid_set
                      and c.lower() not in preferred_set]

    if preferred_hits:
        keep.extend(preferred_hits)
    elif safe_hits:
        # No preferred match but some safe numeric — take just the first
        # to avoid multi-series noise.
        keep.append(safe_hits[0])
    else:
        # No usable measure column. Defensive: return all columns so the
        # chart still renders with prior behavior in unexpected shapes.
        return columns

    return keep


def build_chart_spec(columns, rows, question: str, chart_hint: str) -> dict:
    """
    Package the chart payload for the frontend's renderChart().

    Does NOT reorder rows — assumes upstream already called reorder_for_chart
    so that the data table and the chart show consistent ordering.

    v2 stabilization: filters columns to just the accounting measure(s) +
    label, preventing multi-series noise from date/id/category columns
    that happen to parse as numeric.
    """
    selected = _select_chart_columns(columns, rows, question, chart_hint)
    filtered_rows = [
        {c: row.get(c) for c in selected if c in row}
        for row in rows
    ]
    return {
        "chart_type": chart_hint,
        "columns":    selected,
        "rows":       filtered_rows,
        "question":   question,
    }'''


CONSTANTS_ANCHOR = '    "jan_", "feb_", "mar_", "apr_", "2026", "2025",\n)'


def backup(path: Path) -> Path:
    ts  = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    bak = path.with_suffix(path.suffix + f".pre-p1-chart-{ts}.bak")
    shutil.copy2(str(path), str(bak))
    return bak


def main():
    print("=" * 72)
    print("  Stabilization v2 — Priority 1: chart column selection")
    print("=" * 72)
    print()
    print(f"File: {FILE_PATH}")
    print()

    if not FILE_PATH.exists():
        print(f"✗ File not found at {FILE_PATH}")
        print("  Run this from the app2/ project root.")
        return 1

    text = FILE_PATH.read_text()

    # Idempotence
    if "PREFERRED_MEASURE_COLUMNS" in text and "_select_chart_columns" in text:
        print("  ✓ Already patched (PREFERRED_MEASURE_COLUMNS + "
              "_select_chart_columns both present).")
        return 0

    # Pre-flight pattern checks
    if CONSTANTS_ANCHOR not in text:
        print("  ⚠ Constants insertion anchor not found.")
        print("    Expected to find the closing of _MONTH_COLUMN_KEYWORDS.")
        print("    chart_builder.py may have been edited.")
        return 1

    if OLD_BUILD not in text:
        print("  ⚠ build_chart_spec function body not found as expected.")
        print("    chart_builder.py may have been edited.")
        return 1

    if text.count(OLD_BUILD) > 1:
        print("  ⚠ build_chart_spec body found multiple times (ambiguous).")
        return 1

    # Back up
    bak = backup(FILE_PATH)
    print(f"Backed up to: {bak.name}")
    print()

    # Apply
    new_text = text

    # 1. Insert constants after _MONTH_COLUMN_KEYWORDS
    new_text = new_text.replace(
        CONSTANTS_ANCHOR,
        CONSTANTS_ANCHOR + CONSTANTS_BLOCK,
        1,
    )
    print("  ✓ Added PREFERRED_MEASURE_COLUMNS, AVOID_AS_MEASURE_COLUMNS,")
    print("    and EXPLICIT_COLUMN_REQUEST_PATTERN")

    # 2. Replace build_chart_spec with helper + new function
    new_text = new_text.replace(OLD_BUILD, NEW_BUILD, 1)
    print("  ✓ Added _select_chart_columns() helper")
    print("  ✓ Updated build_chart_spec() to filter columns and rows")

    FILE_PATH.write_text(new_text)
    print()
    print("Applied successfully.")
    print()
    print("Verification — run these in order:")
    print()
    print("  1. Syntax check (catches any indentation/syntax problem):")
    print("       python3 -m py_compile backend/pipelines/chart_builder.py")
    print()
    print("  2. Restart server:")
    print("       lsof -ti:8002 | xargs kill -9 2>/dev/null ; true")
    print("       python3 backend/main.py")
    print()
    print("  3. In the UI, test these four chart cases:")
    print()
    print('     a) "Show me the first 10 rows of the general ledger"')
    print("        → expect: chart shows ONLY debit + credit (no date,")
    print("          account_code, or period as bars)")
    print()
    print('     b) "Show overdue balances by customer as a bar chart"')
    print("        → expect: chart shows ONLY balance_due (no due_date,")
    print("          days_outstanding, or aging_bucket)")
    print()
    print('     c) "Show revenue by service line as a bar chart"')
    print("        → expect: existing good behavior preserved (single")
    print("          revenue/ytd_total series). Sim 3 confirmed clean.")
    print()
    print('     d) "Show only balance_due by customer as a bar chart"')
    print("        → expect: same as (b) via explicit request path")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
