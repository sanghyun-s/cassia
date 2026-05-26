"""
=============================================================
TABULAR — CSV / Excel preview + ingest
=============================================================

Preview reads a file and describes its schema without persisting.
Ingest writes the file into the session's SQLite DB as tables.

Public API:
  preview_csv(file_bytes, filename)  -> dict
  preview_xlsx(file_bytes, filename) -> dict
  ingest_csv(session_id, file_bytes, filename, override_table_name=None) -> dict
  ingest_xlsx(session_id, file_bytes, filename, table_name_overrides=None) -> dict

Phase 4b-1:
  - ingest_csv / ingest_xlsx now also return a "summary" key: a compact
    {kind:"tabular", tables:[{table_name, columns, row_count, sample_rows}]}
    captured from the dataframe in hand. The upload router stores it as
    summary_json so core-saves can be rich without re-reading the file.
"""

import io
from pathlib import Path

import pandas as pd

from uploads.schema_utils import (
    sanitize_table_name,
    sanitize_identifier,
    infer_column_type,
    sample_value,
)
from uploads.session_db import write_dataframe

PREVIEW_MAX_COLUMNS = 50

# How many sample rows to capture in the ingest summary (for core-saves recall).
SUMMARY_SAMPLE_ROWS = 5
SUMMARY_MAX_COLUMNS = 30


# ── PREVIEW ────────────────────────────────────────────────

def _describe_dataframe(df: pd.DataFrame, suggested_table: str, sheet_name: str | None) -> dict:
    """Build the preview dict for one DataFrame (one sheet or the whole CSV)."""
    columns = []
    for col in df.columns[:PREVIEW_MAX_COLUMNS]:
        columns.append({
            "name":          sanitize_identifier(col, fallback="col"),
            "original_name": str(col),
            "type":          infer_column_type(df[col]),
            "sample":        sample_value(df[col]),
        })

    return {
        "sheet_name":        sheet_name,
        "suggested_table":   suggested_table,
        "row_count":         int(len(df)),
        "columns":           columns,
        "truncated_columns": len(df.columns) > PREVIEW_MAX_COLUMNS,
    }


def _table_summary(df: pd.DataFrame, table_name: str) -> dict:
    """
    Build a compact, JSON-safe summary of one table for core-saves.
    Columns (capped) + first N rows as plain dicts + row count.
    """
    cols = [str(c) for c in df.columns[:SUMMARY_MAX_COLUMNS]]

    head = df.head(SUMMARY_SAMPLE_ROWS)
    sample_rows = []
    for _, row in head.iterrows():
        r = {}
        for c in cols:
            val = row[c]
            # Coerce to JSON-safe primitives; NaN/NaT → None
            if pd.isna(val):
                r[c] = None
            elif isinstance(val, (int, float, bool, str)):
                r[c] = val
            else:
                r[c] = str(val)
        sample_rows.append(r)

    return {
        "table_name":  table_name,
        "columns":     cols,
        "row_count":   int(len(df)),
        "sample_rows": sample_rows,
        "truncated_columns": len(df.columns) > SUMMARY_MAX_COLUMNS,
    }


def _read_csv_bytes(file_bytes: bytes) -> pd.DataFrame:
    """Read CSV bytes with sensible fallbacks. Raises ValueError on failure."""
    try:
        return pd.read_csv(io.BytesIO(file_bytes), low_memory=False)
    except pd.errors.EmptyDataError:
        raise ValueError("The CSV file is empty.")
    except pd.errors.ParserError as e:
        raise ValueError(f"Could not parse CSV: {e}")
    except UnicodeDecodeError:
        try:
            return pd.read_csv(io.BytesIO(file_bytes), low_memory=False, encoding="latin-1")
        except Exception as e:
            raise ValueError(f"CSV encoding not recognised: {e}")


def preview_csv(file_bytes: bytes, filename: str) -> dict:
    """Read CSV bytes and return preview metadata."""
    df = _read_csv_bytes(file_bytes)

    if df.empty and len(df.columns) == 0:
        raise ValueError("The CSV file has no data and no headers.")

    stem = Path(filename).stem
    suggested = sanitize_table_name(stem)

    return {
        "file_type": "csv",
        "sheets":    [_describe_dataframe(df, suggested, sheet_name=None)],
    }


def preview_xlsx(file_bytes: bytes, filename: str) -> dict:
    """Read Excel bytes and return preview metadata for every sheet."""
    try:
        xl = pd.ExcelFile(io.BytesIO(file_bytes), engine="openpyxl")
    except Exception as e:
        raise ValueError(f"Could not read Excel file: {e}")

    if not xl.sheet_names:
        raise ValueError("The Excel file contains no sheets.")

    stem = Path(filename).stem
    sheets = []
    for sheet_name in xl.sheet_names:
        try:
            df = xl.parse(sheet_name)
        except Exception as e:
            sheets.append({
                "sheet_name":        sheet_name,
                "suggested_table":   sanitize_table_name(stem, sheet_name),
                "row_count":         0,
                "columns":           [],
                "error":             f"Could not read sheet: {e}",
                "truncated_columns": False,
            })
            continue

        if df.empty and len(df.columns) == 0:
            sheets.append({
                "sheet_name":        sheet_name,
                "suggested_table":   sanitize_table_name(stem, sheet_name),
                "row_count":         0,
                "columns":           [],
                "error":             "Sheet is empty.",
                "truncated_columns": False,
            })
            continue

        sheets.append(_describe_dataframe(df, sanitize_table_name(stem, sheet_name), sheet_name))

    return {
        "file_type": "xlsx",
        "sheets":    sheets,
    }


# ── INGEST ─────────────────────────────────────────────────

def ingest_csv(
    session_id:          str,
    file_bytes:          bytes,
    filename:            str,
    override_table_name: str | None = None,
) -> dict:
    """
    Write the CSV into this session's SQLite DB as one table.
    Returns a per-sheet summary (single sheet for CSV) plus a compact
    'summary' for core-saves.
    """
    df = _read_csv_bytes(file_bytes)
    if df.empty and len(df.columns) == 0:
        raise ValueError("The CSV file has no data and no headers.")

    stem      = Path(filename).stem
    suggested = sanitize_table_name(stem)

    target_table = (
        sanitize_table_name(override_table_name) if override_table_name else suggested
    )

    final_table = write_dataframe(session_id, df, target_table)

    return {
        "file_type":      "csv",
        "tables_created": [final_table],
        "sheets": [{
            "sheet_name":  None,
            "table_name":  final_table,
            "row_count":   int(len(df)),
            "status":      "ok",
        }],
        "total_rows":     int(len(df)),
        "summary": {
            "kind":   "tabular",
            "tables": [_table_summary(df, final_table)],
        },
    }


def ingest_xlsx(
    session_id:           str,
    file_bytes:           bytes,
    filename:             str,
    table_name_overrides: dict[str, str] | None = None,
) -> dict:
    """
    Write every readable sheet of the Excel file into the session's SQLite DB.
    Per-sheet ingestion — one bad sheet does not block the others.

    table_name_overrides: {sheet_name: desired_table_name}. Missing keys
      fall back to the suggested name.
    """
    try:
        xl = pd.ExcelFile(io.BytesIO(file_bytes), engine="openpyxl")
    except Exception as e:
        raise ValueError(f"Could not read Excel file: {e}")

    if not xl.sheet_names:
        raise ValueError("The Excel file contains no sheets.")

    overrides = table_name_overrides or {}
    stem      = Path(filename).stem

    sheet_results: list[dict]  = []
    tables_created: list[str]  = []
    summary_tables: list[dict] = []
    total_rows                 = 0

    for sheet_name in xl.sheet_names:
        try:
            df = xl.parse(sheet_name)
        except Exception as e:
            sheet_results.append({
                "sheet_name": sheet_name,
                "status":     "error",
                "error":      f"Could not read sheet: {e}",
            })
            continue

        if df.empty and len(df.columns) == 0:
            sheet_results.append({
                "sheet_name": sheet_name,
                "status":     "skipped",
                "error":      "Sheet is empty.",
            })
            continue

        suggested = sanitize_table_name(stem, sheet_name)
        target    = sanitize_table_name(overrides[sheet_name]) if sheet_name in overrides else suggested

        try:
            final_table = write_dataframe(session_id, df, target)
            sheet_results.append({
                "sheet_name":  sheet_name,
                "table_name":  final_table,
                "row_count":   int(len(df)),
                "status":      "ok",
            })
            tables_created.append(final_table)
            summary_tables.append(_table_summary(df, final_table))
            total_rows += int(len(df))
        except Exception as e:
            sheet_results.append({
                "sheet_name": sheet_name,
                "status":     "error",
                "error":      f"Could not write to session DB: {e}",
            })

    if not tables_created:
        raise ValueError("No sheets could be ingested. See per-sheet errors.")

    return {
        "file_type":      "xlsx",
        "tables_created": tables_created,
        "sheets":         sheet_results,
        "total_rows":     total_rows,
        "summary": {
            "kind":   "tabular",
            "tables": summary_tables,
        },
    }
