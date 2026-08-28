"""Strict typed access to execution-relevant Binance reference fields."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from onlyalpha_plugin_binance.errors import OnlyBinanceSchemaError


def _object(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise OnlyBinanceSchemaError(f"{label}_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise OnlyBinanceSchemaError(f"{label}_OBJECT_REQUIRED")
    return value


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotExchangeInfo:
    raw: dict[str, Any]

    @classmethod
    def parse(cls, payload: bytes) -> OnlyBinanceSpotExchangeInfo:
        raw = _object(payload, "EXCHANGE_INFO")
        if not isinstance(raw.get("timezone"), str) or not isinstance(raw.get("symbols"), list):
            raise OnlyBinanceSchemaError("EXCHANGE_INFO_REQUIRED_FIELD_INVALID")
        return cls(raw)


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotExecutionRules:
    raw: dict[str, Any]

    @classmethod
    def parse(cls, payload: bytes) -> OnlyBinanceSpotExecutionRules:
        raw = _object(payload, "EXECUTION_RULES")
        if not isinstance(raw.get("symbolRules"), list):
            raise OnlyBinanceSchemaError("EXECUTION_RULES_REQUIRED_FIELD_INVALID")
        return cls(raw)
