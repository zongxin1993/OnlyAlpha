"""Small exact parsing primitives for persisted Dataset contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timedelta

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def require_exact_fields(value: Mapping[str, object], expected: set[str], context: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{context} fields are invalid; missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}"
        )


def require_str(value: Mapping[str, object], name: str, context: str) -> str:
    item = value[name]
    if not isinstance(item, str):
        raise ValueError(f"{context} {name} must be a string")
    return item


def require_optional_str(value: Mapping[str, object], name: str, context: str) -> str | None:
    item = value[name]
    if item is not None and not isinstance(item, str):
        raise ValueError(f"{context} {name} must be a string or null")
    return item


def require_int(value: Mapping[str, object], name: str, context: str) -> int:
    item = value[name]
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"{context} {name} must be an integer")
    return item


def require_bool(value: Mapping[str, object], name: str, context: str) -> bool:
    item = value[name]
    if not isinstance(item, bool):
        raise ValueError(f"{context} {name} must be a boolean")
    return item


def require_mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object")
    return value


def require_list(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be an array")
    return value


def require_sha256(value: Mapping[str, object], name: str, context: str) -> str:
    item = require_str(value, name, context)
    if _SHA256.fullmatch(item) is None:
        raise ValueError(f"{context} {name} must be a lower-case SHA256")
    return item


def require_utc_datetime(value: Mapping[str, object], name: str, context: str) -> datetime:
    raw = require_str(value, name, context)
    try:
        result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{context} {name} must be an ISO datetime") from exc
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError(f"{context} {name} must be timezone-aware UTC")
    return result
