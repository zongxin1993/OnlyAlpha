"""Bounded canonical private wire values, with no Trading lifecycle contract."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

MAX_FRAME = 1024 * 1024
MAX_U64 = 2**64 - 1
MAX_COLLECTION_VALUES = 4097


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch("[0-9a-f]{64}", value) is None:
        raise ValueError("IDENTITY_INVALID")
    return value


def integer(value: object, minimum: int = 0, maximum: int = MAX_U64) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("INTEGER_INVALID")
    return value


def exact(value: object, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError("FIELDS_INVALID")
    return value


def _bounded(value: object, depth: int = 0) -> None:
    if depth > 32:
        raise ValueError("RECORD_DEPTH")
    if isinstance(value, str) and len(value) > 4096:
        raise ValueError("STRING_BUDGET")
    if isinstance(value, (list, dict)):
        if len(value) > (MAX_COLLECTION_VALUES if isinstance(value, list) else 4096):
            raise ValueError("COLLECTION_BUDGET")
        for item in value.items() if isinstance(value, dict) else enumerate(value):
            _bounded(item[0], depth + 1)
            _bounded(item[1], depth + 1)
    elif not (value is None or type(value) in (str, int, bool)):
        raise ValueError("RECORD_TYPE")


def encode(value: object) -> bytes:
    _bounded(value)
    result = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    if len(result) > MAX_FRAME:
        raise ValueError("RECORD_BUDGET")
    return result


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_FIELD")
        result[key] = value
    return result


def decode(data: bytes) -> Any:
    if not data or len(data) > MAX_FRAME:
        raise ValueError("RECORD_BUDGET")
    try:
        result = json.loads(data, object_pairs_hook=_pairs)
        _bounded(result)
        return result
    except (RecursionError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("RECORD_INVALID") from exc
