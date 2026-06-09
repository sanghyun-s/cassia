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
    r"\bonly\s+([\w_]+(?:\s+and\s+[\w_]+)*)", re.I
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


def _select_chart_columns(columns, rows, question, chart_hint):
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
        tokens = [t.strip() for t in re.split(r"\s+and\s+|\s*,\s*",
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
    print(f"[P1 DEBUG] build_chart_spec IN cols: {columns}", flush=True)
    selected = _select_chart_columns(columns, rows, question, chart_hint)
    print(f"[P1 DEBUG] build_chart_spec OUT cols: {selected}", flush=True)
    filtered_rows = [
        {c: row.get(c) for c in selected if c in row}
        for row in rows
    ]
    return {
        "chart_type": chart_hint,
        "columns":    selected,
        "rows":       filtered_rows,
        "question":   question,
    }
