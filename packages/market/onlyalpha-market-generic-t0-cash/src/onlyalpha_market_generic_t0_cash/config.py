"""Minimal composition-only configuration for Generic T0 Cash."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.plugin.api import (
    OnlyCanonicalMarketProductConfig,
    OnlyInvalidMarketProductConfigurationError,
)


@dataclass(frozen=True, slots=True)
class OnlyGenericT0CashConfig:
    reference_resource_id: str

    @classmethod
    def parse(cls, raw: OnlyCanonicalMarketProductConfig) -> OnlyGenericT0CashConfig:
        unknown = sorted(set(raw.values) - {"reference_resource_id"})
        if unknown:
            raise OnlyInvalidMarketProductConfigurationError(
                "INVALID_GENERIC_T0_CASH_CONFIGURATION",
                f"unknown configuration fields: {', '.join(unknown)}",
            )
        value = raw.values.get("reference_resource_id")
        if not isinstance(value, str) or not value.strip():
            raise OnlyInvalidMarketProductConfigurationError(
                "INVALID_GENERIC_T0_CASH_CONFIGURATION",
                "reference_resource_id must be a non-empty string",
            )
        return cls(value.strip())


__all__ = ["OnlyGenericT0CashConfig"]
