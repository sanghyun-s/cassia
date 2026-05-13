"""
=============================================================
SCHEMA UTILS — name sanitization + type inference
=============================================================

Helpers shared by tabular ingest (CSV/Excel).

Two responsibilities:
  1. sanitize_identifier() — turn arbitrary user input into a
     safe SQLite identifier (table or column name).
  2. infer_column_type()   — map a pandas dtype to a SQLite type
     string the user sees in the preview.
"""

import re
import pandas as pd


# SQLite reserved words we should never emit as identifiers.
# Not exhaustive — just the ones likely to collide with user files.
_RESERVED = {
    "select", "from", "where", "table", "index", "join",
    "order", "group", "by", "having", "limit", "offset",
    "insert", "update", "delete", "create", "drop", "alter",
    "and", "or", "not", "null", "true", "false",
    "primary", "foreign", "key", "references", "default",
}


def sanitize_identifier(name: str, fallback: str = "col") -> str:
    """
    Convert an arbitrary string into a safe SQLite identifier.

    Rules:
      - lowercase
      - replace non-alphanumeric with underscores
      - collapse repeated underscores
      - strip leading/trailing underscores
      - prepend fallback if result starts with a digit or is empty
      - suffix '_col' if result collides with a reserved word

    Examples:
      "Net Income ($)"   -> "net_income"
      "2026 Revenue"     -> "col_2026_revenue"
      "Account #"        -> "account"
      "from"             -> "from_col"
      ""                 -> "col"
    """
    if name is None:
        return fallback

    s = str(name).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")

    if not s:
        return fallback
    if s[0].isdigit():
        s = f"{fallback}_{s}"
    if s in _RESERVED:
        s = f"{s}_col"
    return s


def sanitize_table_name(filename_stem: str, sheet_name: str | None = None) -> str:
    """
    Build a table name from a filename stem and optional sheet name.

    "sales_2026.csv" with stem "sales_2026"
       -> "sales_2026"

    "Q1 Report.xlsx" sheet "Revenue Detail"
       -> "q1_report__revenue_detail"
    """
    base = sanitize_identifier(filename_stem, fallback="upload")
    if sheet_name is None:
        return base
    sheet = sanitize_identifier(sheet_name, fallback="sheet")
    return f"{base}__{sheet}"


def infer_column_type(series: pd.Series) -> str:
    """
    Map a pandas Series dtype to a display string.
    Used in the preview UI so the user knows what types were detected.

    Returns one of: INTEGER, REAL, TEXT, DATE
    """
    dtype = series.dtype

    # Datetime check first (datetime64[ns], etc.)
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "DATE"
    if pd.api.types.is_integer_dtype(dtype):
        return "INTEGER"
    if pd.api.types.is_float_dtype(dtype):
        return "REAL"
    if pd.api.types.is_bool_dtype(dtype):
        return "INTEGER"
    return "TEXT"


def sample_value(series: pd.Series) -> str:
    """
    Pick a non-null sample value for preview display.
    Returns empty string if the column is entirely null.
    """
    non_null = series.dropna()
    if non_null.empty:
        return ""
    val = non_null.iloc[0]
    s = str(val)
    return s if len(s) <= 40 else s[:37] + "..."
