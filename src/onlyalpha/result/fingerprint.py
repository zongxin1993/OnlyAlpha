"""Canonical result hashing without volatile run metadata."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum

_EXCLUDED = frozenset({"run_id", "started_at", "finished_at", "traceback", "created_at", "absolute_path"})


def _canonical(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _canonical(getattr(value, item.name)) for item in fields(value) if item.name not in _EXCLUDED
        }
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _EXCLUDED
        }
    if isinstance(value, tuple | list):
        return [_canonical(item) for item in value]
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, timedelta):
        return ((value.days * 86400 + value.seconds) * 1_000_000) + value.microseconds
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, str | int | bool):
        return value
    raise TypeError(f"unsupported result fingerprint value: {type(value).__name__}")


def only_result_fingerprint(value: object) -> str:
    """Hash stable result content, excluding volatile identity and diagnostics text."""

    encoded = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
