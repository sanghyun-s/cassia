#!/usr/bin/env python3
"""
Stabilization v2 — Priority 1b: Frontend chart-column filter (companion to P1).

The backend P1 patch correctly filters chart_spec at build time, but only the
HISTORY-LOAD path in the frontend populates `_chart_spec` (from the saved
artifact at line 1133 of index.html). The NEW-MESSAGE path receives the API
response without _chart_spec and falls back to the unfiltered raw_data/
columns at line 2031, producing noisy multi-series charts.

This patch ports the backend's _select_chart_columns logic to the frontend,
so the new-message fallback path applies the same column filtering on the
client side. The history-load path (which already has _chart_spec from the
artifact) is unchanged.

Modifications to backend/static/index.html:
  + Adds _P1_PREFERRED_MEASURE_COLS constant (Set of preferred measure columns)
  + Adds _P1_AVOID_AS_MEASURE_COLS constant (Set of columns to never chart)
  + Adds _p1SelectChartColumns(columns, rows) helper function
  + Modifies the chart-spec fallback at the call site (line ~2031) to use the helper

Safety
------
- Backs up index.html with timestamped suffix
- Idempotent (looks for _P1_PREFERRED_MEASURE_COLS marker)
- Pattern uniqueness checks before applying
- No server restart needed — this is a static frontend file

Run from app2/ project root:
    python3 apply_p1b_frontend_chart_filter.py
"""

import shutil
import sys
from pathlib import Path
from datetime import datetime


PROJECT_ROOT = Path.cwd()
FILE_PATH    = PROJECT_ROOT / "backend" / "static" / "index.html"


# ── Block to insert BEFORE 'function renderChart(...)' ────────────────
HELPER_BLOCK = """// v2 stabilization P1b: mirror backend's _select_chart_columns for the
// new-message rendering path (where _chart_spec isn't yet populated).
// History-load path uses _chart_spec from the saved artifact and is unaffected.
const _P1_PREFERRED_MEASURE_COLS = new Set([
  'balance_due', 'amount', 'debit', 'credit', 'revenue', 'expense',
  'total', 'net_income', 'ytd_total', 'payment_amount',
  'invoice_amount', 'cash_balance', 'outstanding_balance',
  'january_2026', 'february_2026', 'march_2026', 'april_2026',
  'jan_31_2026', 'feb_28_2026', 'mar_31_2026', 'apr_30_2026',
]);

const _P1_AVOID_AS_MEASURE_COLS = new Set([
  'date', 'due_date', 'invoice_date', 'payment_date', 'period',
  'account_code', 'customer_id', 'vendor_id', 'client_id',
  'days_outstanding', 'aging_bucket', 'txn_id', 'id',
  'reference', 'category',
]);

function _p1SelectChartColumns(columns, rows) {
  // Defensive: return as-is if nothing to filter
  if (!columns || !columns.length || !rows || !rows.length) return columns;

  // Classify columns as numeric vs categorical (>70% values parse as number)
  const numericCols     = [];
  const categoricalCols = [];
  columns.forEach(col => {
    const vals = rows.map(r => r[col]).filter(v => v != null && v !== '');
    const numCount = vals.filter(v => !isNaN(parseFloat(v))).length;
    if (vals.length && numCount / vals.length > 0.7) {
      numericCols.push(col);
    } else {
      categoricalCols.push(col);
    }
  });

  // Filter numeric columns: prefer PREFERRED, avoid AVOID
  const preferredHits = numericCols.filter(c =>
    _P1_PREFERRED_MEASURE_COLS.has(c.toLowerCase())
  );
  const safeHits = numericCols.filter(c =>
    !_P1_AVOID_AS_MEASURE_COLS.has(c.toLowerCase())
    && !_P1_PREFERRED_MEASURE_COLS.has(c.toLowerCase())
  );

  const keep = categoricalCols.length ? [categoricalCols[0]] : [];
  if (preferredHits.length) {
    keep.push(...preferredHits);
  } else if (safeHits.length) {
    // No preferred match but some safe numeric — take just the first
    keep.push(safeHits[0]);
  } else {
    // No usable measure column — defensive fallback to all columns
    return columns;
  }
  return keep;
}

"""


INSERTION_ANCHOR = "function renderChart(chartType, columns, rows, question) {"

OLD_LINE = "      const chartCols = spec ? spec.columns : cols;"
NEW_LINE = "      const chartCols = spec ? spec.columns : _p1SelectChartColumns(cols, rows);"


def backup(path: Path) -> Path:
    ts  = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    bak = path.with_suffix(path.suffix + f".pre-p1b-frontend-{ts}.bak")
    shutil.copy2(str(path), str(bak))
    return bak


def main():
    print("=" * 72)
    print("  Stabilization v2 — Priority 1b: Frontend chart-column filter")
    print("=" * 72)
    print()
    print(f"File: {FILE_PATH}")
    print()

    if not FILE_PATH.exists():
        print(f"  File not found at {FILE_PATH}")
        return 1

    text = FILE_PATH.read_text()

    # Idempotence check
    if "_P1_PREFERRED_MEASURE_COLS" in text and "_p1SelectChartColumns" in text:
        print("  Already patched (P1b markers present).")
        return 0

    # Pre-flight pattern checks
    if INSERTION_ANCHOR not in text:
        print(f"  Insertion anchor not found:")
        print(f"    '{INSERTION_ANCHOR}'")
        print("  index.html may have been edited since the locator ran.")
        return 1

    if text.count(INSERTION_ANCHOR) > 1:
        print("  Insertion anchor appears multiple times (ambiguous).")
        return 1

    if OLD_LINE not in text:
        print(f"  Call-site line not found:")
        print(f"    '{OLD_LINE.strip()}'")
        print("  Indentation may differ — check around line 2031 of index.html.")
        return 1

    if text.count(OLD_LINE) > 1:
        print("  Call-site line appears multiple times (ambiguous).")
        return 1

    # Back up before any write
    bak = backup(FILE_PATH)
    print(f"Backed up to: {bak.name}")
    print()

    # Apply
    new_text = text

    # 1. Insert helper block right before 'function renderChart'
    new_text = new_text.replace(
        INSERTION_ANCHOR,
        HELPER_BLOCK + INSERTION_ANCHOR,
        1,
    )
    print("  Added _P1_PREFERRED_MEASURE_COLS, _P1_AVOID_AS_MEASURE_COLS,")
    print("  and _p1SelectChartColumns() helper")

    # 2. Modify the call site to use the helper for the fallback case
    new_text = new_text.replace(OLD_LINE, NEW_LINE, 1)
    print("  Updated chart-spec fallback at the call site to use the helper")

    FILE_PATH.write_text(new_text)
    print()
    print("Applied successfully.")
    print()
    print("Verification:")
    print()
    print("  IMPORTANT: NO server restart needed — this is a static frontend file.")
    print("             The browser fetches index.html fresh on each page load.")
    print()
    print("  1. In your browser, do a HARD refresh to bypass any cached")
    print("     version of index.html:")
    print("       Mac:     Cmd + Shift + R")
    print("       Windows: Ctrl + Shift + R")
    print()
    print("  2. Test a fresh chart prompt (without refreshing afterward):")
    print('       "Show me the first 10 rows of the general ledger as a bar chart"')
    print("     Expected: chart shows ONLY debit and credit immediately,")
    print("     without needing a second refresh.")
    print()
    print("  3. Also test on AR aging:")
    print('       "Show overdue balances by customer as a bar chart"')
    print("     Expected: chart shows ONLY balance_due (no days_outstanding,")
    print("     no aging_bucket).")
    print()
    print("  4. Once confirmed, you can remove the two [P1 DEBUG] print lines")
    print("     from backend/pipelines/chart_builder.py (they're no longer")
    print("     needed — backend filter is fully verified).")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
