"""Bounded component records. No historical Definition2 reader or executable objects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from decimal import Decimal
from enum import Enum
from typing import Any, cast

from onlyalpha.calculation.definition import OnlyCalculationDefinition
from onlyalpha_calculation_worker.codec import decode as decode
from onlyalpha_calculation_worker.codec import digest as digest
from onlyalpha_calculation_worker.codec import encode as encode
from onlyalpha_calculation_worker.codec import exact as exact
from onlyalpha_calculation_worker.codec import integer as integer
from onlyalpha_calculation_worker.codec import sha as sha

MAX_FRAME = 1024 * 1024
MAX_BATCH = 256
MAX_INSTANCES = 16
# Native SMA retains period+1 values, including the outgoing sample.
MAX_STATE_VALUES = 4097
MAX_U64 = 2**64 - 1


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
