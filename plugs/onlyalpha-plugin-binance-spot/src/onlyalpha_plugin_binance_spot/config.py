"""Exact Binance Spot composition configuration."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.plugin.api import OnlyCanonicalMarketProductConfig, OnlyInvalidMarketProductConfigurationError


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotConfig:
    reference_resource_id: str
    expected_reference_fingerprint: str
    maker_fee_rate: Decimal
    taker_fee_rate: Decimal

    @classmethod
    def parse(cls, raw: OnlyCanonicalMarketProductConfig) -> OnlyBinanceSpotConfig:
        allowed = {"reference_resource_id", "expected_reference_fingerprint", "maker_fee_rate", "taker_fee_rate"}
        unknown = sorted(set(raw.values) - allowed)
        if unknown:
            raise OnlyInvalidMarketProductConfigurationError("INVALID_BINANCE_SPOT_CONFIGURATION", unknown[0])
        try:
            resource = raw.values["reference_resource_id"]
            expected = raw.values["expected_reference_fingerprint"]
            maker = raw.values["maker_fee_rate"]
            taker = raw.values["taker_fee_rate"]
        except KeyError as exc:
            raise OnlyInvalidMarketProductConfigurationError(
                "INVALID_BINANCE_SPOT_CONFIGURATION", f"missing {exc.args[0]}"
            ) from exc
        if not isinstance(resource, str) or not resource:
            raise OnlyInvalidMarketProductConfigurationError(
                "INVALID_BINANCE_SPOT_CONFIGURATION", "reference_resource_id must be text"
            )
        if not isinstance(expected, str) or not expected:
            raise OnlyInvalidMarketProductConfigurationError(
                "INVALID_BINANCE_SPOT_CONFIGURATION", "expected_reference_fingerprint must be text"
            )
        if not isinstance(maker, str) or not isinstance(taker, str) or not maker or not taker:
            raise OnlyInvalidMarketProductConfigurationError(
                "INVALID_BINANCE_SPOT_CONFIGURATION", "fee rates must be quoted Decimal text"
            )
        rates = (Decimal(maker), Decimal(taker))
        if any(rate < 0 or rate >= 1 for rate in rates):
            raise OnlyInvalidMarketProductConfigurationError(
                "INVALID_BINANCE_SPOT_CONFIGURATION", "fee rate out of range"
            )
        return cls(resource, expected, *rates)


__all__ = ["OnlyBinanceSpotConfig"]
