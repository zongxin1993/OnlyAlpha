"""Bounded component records. No historical Definition2 reader or executable objects."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import fields
from decimal import Decimal
from enum import Enum
from typing import Any, cast

from onlyalpha.calculation.definition import OnlyCalculationDefinition

MAX_FRAME = 1024 * 1024
MAX_BATCH = 256
MAX_INSTANCES = 16
# Native SMA retains period+1 values, including the outgoing sample.
MAX_STATE_VALUES = 4097
MAX_U64 = 2**64 - 1


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
        if len(value) > (MAX_STATE_VALUES if isinstance(value, list) else 4096):
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


def scalar(value: object) -> dict[str, object]:
    if isinstance(value, Decimal):
        if not value.is_finite() or abs(cast(int, value.as_tuple().exponent)) > 4096:
            raise ValueError("DECIMAL_INVALID")
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        text = "0" if not value else text
        return {"type": "DECIMAL", "value": text}
    tag = {str: "STRING", int: "INTEGER", bool: "BOOLEAN", type(None): "NULL"}.get(type(value))
    if tag is None:
        raise ValueError("SCALAR_INVALID")
    return {"type": tag, "value": value}


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f") if cast(int, value.as_tuple().exponent) <= 0 else str(value)
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    return value


def component_definition(native: OnlyCalculationDefinition) -> dict[str, Any]:
    # Construct from live semantic fields, retaining native identity separately.
    result = {
        name: _plain(getattr(native, name))
        for name in (
            "kind",
            "type_id",
            "semantic_version",
            "inputs",
            "input_bindings",
            "outputs",
            "warmup",
            "missing_values",
            "timestamp",
            "numeric",
            "factor_kind",
        )
    }
    result.update(
        schema_version=3,
        parameters={k: scalar(v) for k, v in native.parameters.items()},
        extensions={k: scalar(v) for k, v in native.extensions.items()},
    )
    encode(result)
    return result


def binding(value: object) -> dict[str, Any]:
    row = exact(value, {"schema_version", "digests", "scope"})
    if type(row["schema_version"]) is not int or row["schema_version"] != 1:
        raise ValueError("BINDING_SCHEMA")
    if type(row["digests"]) is not list or len(row["digests"]) != 6:
        raise ValueError("BINDING_DIGESTS")
    for item in row["digests"]:
        sha(item)
    scope = row["scope"]
    if (
        not isinstance(scope, str)
        or not 1 <= len(scope) <= 1024
        or scope.strip() != scope
        or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in scope)
    ):
        raise ValueError("SCOPE_INVALID")
    return cast(dict[str, Any], decode(encode(row)))


def input_context(bar_type: object, source: str) -> str:
    return digest(encode({"schema_version": 1, "bar_type": bar_type, "source_fingerprint": sha(source)}))
