"""
=============================================================
CHART BUILDER — chart-type inference and data prep for the UI
=============================================================

Single source of truth for everything chart-related on the backend:

  infer_chart_hint(columns, rows, question)
      → returns "bar" | "line" | "pie" | "none"

  reorder_for_chart(columns, rows, chart_hint)
      → returns rows, optionally reordered. For bar charts on
        (categorical, numeric) data, sorts DESC by the numeric column
        so the chart shows the meaningful order (largest first).
        Other chart types pass through unchanged.

  build_chart_spec(columns, rows, question, chart_hint)
      → returns the dict shape the frontend's renderChart() expects.
        Does NOT reorder — assumes upstream already called reorder_for_chart.

Why this lives outside sql_pipeline.py:
  The chart logic has nothing to do with SQL execution. It happened to
  sit in sql_pipeline.py because that's where rows became available.
  Pulling it out keeps sql_pipeline.py focused on SQL and gives chart
  decisions one obvious home — important when new heuristics get added.

Bug context (the move-out commit also fixes two issues):
  1. The previous _infer_chart_hint matched substring "line" against the
     question, so "Show revenue by service line as a bar chart" routed
     to a line chart because "service LINE" was caught before the
     explicit "bar chart" phrase. Now we phrase-match explicit chart
     requests first ("bar chart", "line chart", "pie chart") and only
     fall through to substring heuristics for ambiguous questions.

  2. The data table sometimes showed rows in un-meaningful order even
     when the chart was a bar chart (the SQL's ORDER BY didn't always
     survive end-to-end, or the LLM omitted it). reorder_for_chart
     defensively sorts bar-chart data DESC by the numeric column so
     the table and chart always show the same, meaningful order.
"""

import re


# ── Explicit chart-type phrase patterns ────────────────────
# These take priority over substring heuristics. Order matters —
# checked top to bottom, first match wins.
EXPLICIT_CHART_REQUEST_PATTERNS = [
    (re.compile(r"\bas a pie\b|\bpie chart\b",   re.I), "pie"),
    (re.compile(r"\bas a bar\b|\bbar chart\b",   re.I), "bar"),
    (re.compile(r"\bas a line\b|\bline chart\b", re.I), "line"),
]

# Trend-style questions that imply a line chart but don't say "line chart"
TREND_KEYWORDS = ("trend", "over time", "monthly", "by month")

# Month/year tokens used to detect monthly-pivoted columns → line chart
_MONTH_COLUMN_KEYWORDS = (
    "january", "february", "march",  "april", "may", "june",
    "july",    "august",   "september", "october", "november", "december",
    "jan_", "feb_", "mar_", "apr_", "2026", "2025",
)


def _classify_columns(columns, rows):
    """
    Split columns into (numeric, categorical) based on whether >70% of
    a column's non-null values parse as float.
    """
    numeric_cols     = []
    categorical_cols = []
    for col in columns:
        try:
            vals       = [row.get(col) for row in rows if row.get(col) is not None]
            float_vals = [float(v) for v in vals if str(v) != ""]
            if vals and len(float_vals) / len(vals) > 0.7:
                numeric_cols.append(col)
            else:
                categorical_cols.append(col)
        except (ValueError, TypeError):
            categorical_cols.append(col)
    return numeric_cols, categorical_cols


def _detect_label_and_value_columns(columns, rows):
    """
    For a 2D (categorical, numeric) shape, return (label_col, value_col)
    or (None, None) if not a clear match. Used by reorder_for_chart.
    """
    if not rows or not columns:
        return None, None
    numeric_cols, categorical_cols = _classify_columns(columns, rows)
    if categorical_cols and numeric_cols:
        return categorical_cols[0], numeric_cols[0]
    return None, None


def infer_chart_hint(columns, rows, question: str) -> str:
    """
    Return a string indicating chart type: "bar" | "line" | "pie" | "none".

    Priority:
      1. Explicit phrase request — "bar chart", "as a line chart", etc.
      2. Trend keywords — "trend", "over time", "monthly", "by month"
      3. Monthly column names in the result → line chart
      4. Data shape — small (cat, num) result → bar chart
      5. Fallback → "none" (no chart rendered)

    The phrase-first priority fixes the previous false-positive where
    "service line" in a question routed to a line chart even when the
    user explicitly asked for a bar chart.
    """
    q = (question or "").lower()

    # 1. Explicit chart-type phrase requests
    for pattern, chart_type in EXPLICIT_CHART_REQUEST_PATTERNS:
        if pattern.search(q):
            return chart_type

    # 2. Trend-style implicit line chart
    if any(kw in q for kw in TREND_KEYWORDS):
        return "line"

    # No rows or no columns → nothing to chart
    if not rows or not columns:
        return "none"
    # Single scalar result (one row, one column) → not chartable
    if len(rows) == 1 and len(columns) == 1:
        return "none"

    # 3. Monthly column names imply a time-series line chart
    if any(any(kw in c.lower() for kw in _MONTH_COLUMN_KEYWORDS) for c in columns):
        return "line"

    # 4. Data-shape heuristics
    numeric_cols, categorical_cols = _classify_columns(columns, rows)
    if len(columns) == 2 and categorical_cols and numeric_cols and len(rows) <= 15:
        return "bar"
    if len(rows) > 1 and numeric_cols and len(rows) <= 20:
        return "bar"

    return "none"


def reorder_for_chart(columns, rows, chart_hint: str):
    """
    For bar charts on (categorical, numeric) data, sort rows DESC by the
    numeric column so the chart and the data table both show the
    meaningful order. Returns a new list (does not mutate the input).

    Other chart types pass through unchanged:
      - line charts may carry intentional time order
      - pie charts don't need ordering
      - "none" doesn't need ordering

    Idempotent: re-running on already-sorted data yields the same order.
    """
    if chart_hint != "bar" or not rows or not columns:
        return rows

    _label_col, value_col = _detect_label_and_value_columns(columns, rows)
    if not value_col:
        return rows

    def _sort_key(row):
        v = row.get(value_col)
        if v is None or str(v) == "":
            return float("-inf")
        try:
            return float(v)
        except (ValueError, TypeError):
            return float("-inf")

    return sorted(rows, key=_sort_key, reverse=True)


def build_chart_spec(columns, rows, question: str, chart_hint: str) -> dict:
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
    }
