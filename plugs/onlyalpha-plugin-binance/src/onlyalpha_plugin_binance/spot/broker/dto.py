"""Strict private REST payload envelopes owned by the Binance plugin."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from onlyalpha_plugin_binance.errors import OnlyBinanceSchemaError


def _json(payload: bytes, *, array: bool) -> dict[str, Any] | list[Any]:
    try:
        decoded = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise OnlyBinanceSchemaError("BINANCE_PRIVATE_JSON_INVALID") from exc
    expected = list if array else dict
    if not isinstance(decoded, expected):
        raise OnlyBinanceSchemaError("BINANCE_PRIVATE_RESPONSE_SHAPE_INVALID")
    return decoded


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotAccountDto:
    raw: dict[str, Any]

    @classmethod
    def parse(cls, payload: bytes) -> OnlyBinanceSpotAccountDto:
        raw = _json(payload, array=False)
        if not isinstance(raw, dict) or not isinstance(raw.get("balances"), list):
            raise OnlyBinanceSchemaError("BINANCE_ACCOUNT_REQUIRED_FIELD_INVALID")
        return cls(raw)


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotOrderDto:
    raw: dict[str, Any]

    @classmethod
    def parse(cls, payload: bytes) -> OnlyBinanceSpotOrderDto:
        raw = _json(payload, array=False)
        if not isinstance(raw, dict):
            raise OnlyBinanceSchemaError("BINANCE_ORDER_OBJECT_REQUIRED")
        return cls(raw)


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotOrdersDto:
    raw: list[dict[str, Any]]

    @classmethod
    def parse(cls, payload: bytes) -> OnlyBinanceSpotOrdersDto:
        raw = _json(payload, array=True)
        if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
            raise OnlyBinanceSchemaError("BINANCE_ORDERS_ARRAY_INVALID")
        return cls(raw)


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotTradesDto:
    raw: list[dict[str, Any]]

    @classmethod
    def parse(cls, payload: bytes) -> OnlyBinanceSpotTradesDto:
        raw = _json(payload, array=True)
        if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
            raise OnlyBinanceSchemaError("BINANCE_TRADES_ARRAY_INVALID")
        return cls(raw)


__all__ = [name for name in globals() if name.startswith("Only")]
