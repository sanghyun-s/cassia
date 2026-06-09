#!/usr/bin/env python3
"""
CASSIA NaN diagnostic — finds where NaN might be generated.

Checks three things:
  1. Raw text search for NaN/nan/Infinity in stored JSON fields
  2. After-parse check: parse each JSON field and recursively look for
     actual float('nan') or float('inf') values
  3. Optional: load each save row exactly the way the API endpoint does
     and try to JSON-serialize it strictly — replicates the FastAPI failure
"""

import sqlite3
import json
import math
import sys
from pathlib import Path


def has_nan_or_inf(obj):
    """Recursively check if any value in obj is NaN or Inf."""
    if isinstance(obj, float):
        return math.isnan(obj) or math.isinf(obj)
    if isinstance(obj, list):
        return any(has_nan_or_inf(x) for x in obj)
    if isinstance(obj, dict):
        return any(has_nan_or_inf(v) for v in obj.values())
    return False


def find_nan_paths(obj, path=""):
    """Return list of dotted paths where NaN/Inf was found."""
    out = []
    if isinstance(obj, float):
        if math.isnan(obj):
            out.append(f"{path} = NaN")
        elif math.isinf(obj):
            out.append(f"{path} = Inf")
    elif isinstance(obj, list):
        for i, x in enumerate(obj):
            out.extend(find_nan_paths(x, f"{path}[{i}]"))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(find_nan_paths(v, f"{path}.{k}" if path else k))
    return out


DB_PATH = Path("outputs/coreckoner.db")
if not DB_PATH.exists():
    print(f"DB not found at {DB_PATH.absolute()}")
    print("Run this script from the app2/ project root.")
    sys.exit(1)

conn = sqlite3.connect(str(DB_PATH))
cur = conn.cursor()

print("=" * 70)
print("CASSIA NaN diagnostic")
print("=" * 70)

# ─────────────────────────────────────────────────────────────────
# Phase 1: raw text search across all JSON fields
# ─────────────────────────────────────────────────────────────────
print("\n[Phase 1] Raw text search for NaN/Inf in stored JSON fields")
print("-" * 70)

phase1_hits = 0
for label, table, id_col, json_cols in [
    ("core_saves", "core_saves", "save_id",
     ["embedding_json", "metadata_json", "content"]),
    ("artifacts",  "artifacts",  "artifact_id",
     ["content_json"]),
    ("uploads",    "uploads",    "upload_id",
     ["summary_json", "table_names"]),
]:
    for col in json_cols:
        try:
            rows = cur.execute(
                f"SELECT {id_col}, {col} FROM {table} WHERE {col} IS NOT NULL"
            ).fetchall()
        except sqlite3.OperationalError:
            continue  # column doesn't exist in this table; skip
        for rid, v in rows:
            sv = str(v)
            for needle in ("NaN", "nan,", ":nan", "Infinity", "-Infinity"):
                if needle in sv:
                    print(f"  HIT {label}.{col} id={rid[:16]}... matched {needle!r}")
                    phase1_hits += 1
                    break

if phase1_hits == 0:
    print("  (no raw-text matches — NaN is not stored as text)")
else:
    print(f"  total raw-text hits: {phase1_hits}")

# ─────────────────────────────────────────────────────────────────
# Phase 2: after-parse check
# ─────────────────────────────────────────────────────────────────
print("\n[Phase 2] After-JSON-parse check for actual NaN/Inf floats")
print("-" * 70)

phase2_hits = 0
for label, table, id_col, title_col, json_cols in [
    ("core_saves", "core_saves", "save_id", "title",
     ["embedding_json", "metadata_json"]),
    ("artifacts",  "artifacts",  "artifact_id", "artifact_type",
     ["content_json"]),
    ("uploads",    "uploads",    "upload_id", "filename",
     ["summary_json"]),
]:
    for col in json_cols:
        try:
            rows = cur.execute(
                f"SELECT {id_col}, {title_col}, {col} FROM {table} "
                f"WHERE {col} IS NOT NULL"
            ).fetchall()
        except sqlite3.OperationalError:
            continue
        for rid, title, v in rows:
            try:
                parsed = json.loads(v)
            except Exception as e:
                print(f"  PARSE-ERR {label}.{col} id={rid[:16]}... err={e}")
                phase2_hits += 1
                continue
            if has_nan_or_inf(parsed):
                paths = find_nan_paths(parsed)
                title_str = str(title)[:50] if title else ""
                print(f"  HIT {label}.{col} id={rid[:16]}...  title={title_str!r}")
                for p in paths[:5]:
                    print(f"       at  {p}")
                if len(paths) > 5:
                    print(f"       ...and {len(paths)-5} more")
                phase2_hits += 1

if phase2_hits == 0:
    print("  (no NaN/Inf found after parsing — NaN is generated at runtime)")
else:
    print(f"  total parse-time NaN hits: {phase2_hits}")

# ─────────────────────────────────────────────────────────────────
# Phase 3: replicate API failure — try strict JSON dump of every save
# ─────────────────────────────────────────────────────────────────
print("\n[Phase 3] Replicating API failure — strict JSON.dumps each save row")
print("-" * 70)

phase3_hits = 0
rows = cur.execute(
    "SELECT save_id, title, kind, content, metadata_json, embedding_json, "
    "topic_id, source_session_id, source_message_id, created_at "
    "FROM core_saves"
).fetchall()

for row in rows:
    save_id, title, kind, content, meta_json, emb_json, *_ = row
    # build a dict similar to what the API would return
    record = {
        "save_id": save_id,
        "title":   title,
        "kind":    kind,
        "content": content,
    }
    if meta_json:
        try:
            record["metadata"] = json.loads(meta_json)
        except Exception:
            pass
    if emb_json:
        try:
            record["embedding"] = json.loads(emb_json)
        except Exception:
            pass
    # strict serialize
    try:
        json.dumps(record, allow_nan=False)
    except ValueError as e:
        title_str = str(title)[:50] if title else ""
        print(f"  STRICT-FAIL save_id={save_id[:16]}...  title={title_str!r}")
        print(f"       err={e}")
        # show where exactly
        paths = find_nan_paths(record)
        for p in paths[:5]:
            print(f"       at  {p}")
        phase3_hits += 1

if phase3_hits == 0:
    print("  (all saves serialize cleanly with allow_nan=False)")
else:
    print(f"  total strict-fail records: {phase3_hits}")

# ─────────────────────────────────────────────────────────────────
# Phase 4: same for artifacts (which restore in /sessions/{id})
# ─────────────────────────────────────────────────────────────────
print("\n[Phase 4] Strict JSON.dumps each artifact row")
print("-" * 70)

phase4_hits = 0
rows = cur.execute(
    "SELECT artifact_id, message_id, artifact_type, content_json FROM artifacts"
).fetchall()

for aid, mid, atype, content in rows:
    if not content:
        continue
    try:
        parsed = json.loads(content)
    except Exception as e:
        print(f"  PARSE-ERR artifact_id={aid[:16]}... type={atype} err={e}")
        phase4_hits += 1
        continue
    try:
        json.dumps(parsed, allow_nan=False)
    except ValueError as e:
        print(f"  STRICT-FAIL artifact_id={aid[:16]}... type={atype}")
        print(f"       msg={mid[:16]}...  err={e}")
        paths = find_nan_paths(parsed)
        for p in paths[:5]:
            print(f"       at  {p}")
        phase4_hits += 1

if phase4_hits == 0:
    print("  (all artifacts serialize cleanly with allow_nan=False)")
else:
    print(f"  total strict-fail artifacts: {phase4_hits}")

# ─────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"  Phase 1 (raw text search):  {phase1_hits} hits")
print(f"  Phase 2 (post-parse):       {phase2_hits} hits")
print(f"  Phase 3 (saves strict):     {phase3_hits} hits")
print(f"  Phase 4 (artifacts strict): {phase4_hits} hits")
print()
if phase3_hits + phase4_hits == 0:
    print("  ⚠  All stored data is clean. The NaN must be generated dynamically")
    print("     by the API endpoint code (e.g., in main.py response builder).")
    print("     Next step: inspect the /core/saves/list and /sessions/{id}")
    print("     handlers in backend/main.py for any float math, pandas operations,")
    print("     or numeric processing that could produce NaN.")
else:
    print("  ✓  Bad records identified. Either delete them or sanitize the NaN")
    print("     to null in those specific records.")
print()

conn.close()
