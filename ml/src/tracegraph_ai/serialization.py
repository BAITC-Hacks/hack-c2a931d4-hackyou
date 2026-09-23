"""Strict JSON encoding without converting identifiers through floating point."""

from datetime import date, datetime
import hashlib
import json
import math
from numbers import Integral, Real
from pathlib import Path

SCHEMA_VERSION = "1.0"
ENGINE_VERSION = "0.3.1"
ID_FIELDS = {"gid", "src", "dst", "target_gid", "source_gid"}
ID_LIST_FIELDS = {"reachable_seed_ids", "top_gids", "target_gids", "related_gids", "seed_ids"}


def parse_gid(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (Integral, str)):
        raise ValueError("gid must be an integer or a decimal string, never float")
    if isinstance(value, str) and (not value.isascii() or not value.isdecimal()):
        raise ValueError("gid must be a nonnegative decimal integer")
    result = int(value)
    if result < 0 or result > 2**63 - 1:
        raise ValueError("gid is outside nonnegative int64 range")
    return result


def json_safe(value, key: str = ""):
    if value is None:
        return None
    if key in ID_FIELDS:
        return str(parse_gid(value))
    if isinstance(value, dict):
        return {str(k): json_safe(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        values = sorted(value) if isinstance(value, set) else value
        return [str(parse_gid(v)) if key in ID_LIST_FIELDS else json_safe(v) for v in values]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        return float(value) if math.isfinite(value) else None
    if hasattr(value, "item"):
        return json_safe(value.item(), key)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return value
    raise TypeError(f"Not JSON serializable: {type(value).__name__}")


def canonical_hash(value) -> str:
    encoded = json.dumps(json_safe(value), ensure_ascii=False, allow_nan=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, value):
    path.write_text(json.dumps(json_safe(value), ensure_ascii=False, allow_nan=False,
                               indent=2) + "\n", encoding="utf-8")
