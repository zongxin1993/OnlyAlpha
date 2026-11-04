"""Exact immutable USD-M Market Product composition configuration."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.enums import OnlyMarginMode
from onlyalpha.domain.trading import OnlyPositionMode
from onlyalpha.market.product import OnlyCanonicalMarketProductConfig, OnlyInvalidMarketProductConfigurationError


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmConfig:
    public_reference_resource_id: str
    expected_public_reference_fingerprint: str
    account_reference_resource_id: str
    expected_account_reference_fingerprint: str
    requested_position_mode: OnlyPositionMode
    requested_margin_mode: OnlyMarginMode
    requested_leverage: Decimal
    maker_fee_rate: Decimal
    taker_fee_rate: Decimal

    @classmethod
    def parse(cls, raw: OnlyCanonicalMarketProductConfig) -> OnlyBinanceUsdmConfig:
        expected = {
            "public_reference_resource_id",
            "expected_public_reference_fingerprint",
            "account_reference_resource_id",
            "expected_account_reference_fingerprint",
            "requested_position_mode",
            "requested_margin_mode",
            "requested_leverage",
            "maker_fee_rate",
            "taker_fee_rate",
        }
        if set(raw.values) != expected:
            raise OnlyInvalidMarketProductConfigurationError(
                "INVALID_BINANCE_USDM_CONFIGURATION", "configuration fields are incomplete or unknown"
            )
        try:
            text = {name: _required_text(raw, name) for name in expected}
            leverage = Decimal(text["requested_leverage"])
            maker = Decimal(text["maker_fee_rate"])
            taker = Decimal(text["taker_fee_rate"])
            if leverage < 1 or any(rate < 0 or rate >= 1 for rate in (maker, taker)):
                raise ValueError
            return cls(
                text["public_reference_resource_id"],
                text["expected_public_reference_fingerprint"],
                text["account_reference_resource_id"],
                text["expected_account_reference_fingerprint"],
                OnlyPositionMode(text["requested_position_mode"]),
                OnlyMarginMode(text["requested_margin_mode"]),
                leverage,
                maker,
                taker,
            )
        except (KeyError, ValueError) as exc:
            raise OnlyInvalidMarketProductConfigurationError(
                "INVALID_BINANCE_USDM_CONFIGURATION", "invalid configuration value"
            ) from exc


def _required_text(raw: OnlyCanonicalMarketProductConfig, name: str) -> str:
    value = raw.values[name]
    if not isinstance(value, str) or not value:
        raise ValueError(name)
    return value


__all__ = ["OnlyBinanceUsdmConfig"]
