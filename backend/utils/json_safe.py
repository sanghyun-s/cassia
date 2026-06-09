"""
JSON serialization safety helpers.

Wrap objects with sanitize_for_json() before json.dumps() to convert NaN/Inf
to None. Use safe_json_dumps() as a drop-in replacement.
"""

import json
import math


def sanitize_for_json(obj):
    """Recursively replace NaN/Inf floats with None."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_json(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(sanitize_for_json(x) for x in obj)
    return obj


def safe_json_dumps(obj, **kwargs):
    """Drop-in for json.dumps() with NaN/Inf -> null and allow_nan=False."""
    kwargs.setdefault("ensure_ascii", False)
    kwargs["allow_nan"] = False
    return json.dumps(sanitize_for_json(obj), **kwargs)
