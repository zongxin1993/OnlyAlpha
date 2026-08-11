"""Typed composition configuration for Generic T0 Cash."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.plugin.api import OnlyCanonicalMarketProductConfig, OnlyInvalidMarketProductConfigurationError


@dataclass(frozen=True, slots=True)
class OnlyGenericT0CashConfig:
    @classmethod
    def parse(cls, raw: OnlyCanonicalMarketProductConfig) -> OnlyGenericT0CashConfig:
        unknown = sorted(raw.values)
        if unknown:
            raise OnlyInvalidMarketProductConfigurationError(
                "INVALID_GENERIC_T0_CASH_CONFIGURATION",
                f"unknown configuration fields: {', '.join(unknown)}",
            )
        return cls()


__all__ = ["OnlyGenericT0CashConfig"]
