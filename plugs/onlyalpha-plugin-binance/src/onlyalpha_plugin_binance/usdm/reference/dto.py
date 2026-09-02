"""Strict DTO validation for USD-M reference evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from onlyalpha_plugin_binance.errors import OnlyBinanceSchemaError


def _json(payload: bytes, label: str) -> object:
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise OnlyBinanceSchemaError(f"BINANCE_USDM_{label}_JSON_INVALID") from exc


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmExchangeInfoDto:
    raw: dict[str, Any]

    @classmethod
    def parse(cls, payload: bytes) -> OnlyBinanceUsdmExchangeInfoDto:
        raw = _json(payload, "EXCHANGE_INFO")
        if not isinstance(raw, dict) or not isinstance(raw.get("symbols"), list):
            raise OnlyBinanceSchemaError("BINANCE_USDM_EXCHANGE_INFO_SCHEMA_INVALID")
        return cls(raw)


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmFundingInfoDto:
    raw: list[dict[str, Any]]

    @classmethod
    def parse(cls, payload: bytes) -> OnlyBinanceUsdmFundingInfoDto:
        raw = _json(payload, "FUNDING_INFO")
        if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
            raise OnlyBinanceSchemaError("BINANCE_USDM_FUNDING_INFO_SCHEMA_INVALID")
        return cls(raw)


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmLeverageBracketDto:
    raw: list[dict[str, Any]]

    @classmethod
    def parse(cls, payload: bytes) -> OnlyBinanceUsdmLeverageBracketDto:
        raw = _json(payload, "LEVERAGE_BRACKET")
        if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
            raise OnlyBinanceSchemaError("BINANCE_USDM_LEVERAGE_BRACKET_SCHEMA_INVALID")
        return cls(raw)


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmAccountProfileDto:
    raw: dict[str, Any]

    @classmethod
    def parse(cls, payload: bytes) -> OnlyBinanceUsdmAccountProfileDto:
        raw = _json(payload, "ACCOUNT_PROFILE")
        if (
            not isinstance(raw, dict)
            or raw.get("positionMode") not in {"NETTING", "HEDGING"}
            or not isinstance(raw.get("symbols"), list)
        ):
            raise OnlyBinanceSchemaError("BINANCE_USDM_ACCOUNT_PROFILE_SCHEMA_INVALID")
        return cls(raw)


__all__ = [name for name in globals() if name.startswith("Only")]
