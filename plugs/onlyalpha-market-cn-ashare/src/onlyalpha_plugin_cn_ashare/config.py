"""Typed composition configuration for CN A-share cash."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from onlyalpha.plugin.api import (
    OnlyCanonicalMarketProductConfig,
    OnlyInvalidMarketProductConfigurationError,
)
from onlyalpha_plugin_cn_ashare.reference import OnlyCnAshareInstrumentReference


@dataclass(frozen=True, slots=True)
class OnlyCnAshareConfig:
    references: tuple[OnlyCnAshareInstrumentReference, ...]

    @classmethod
    def parse(cls, raw: OnlyCanonicalMarketProductConfig) -> OnlyCnAshareConfig:
        unknown = sorted(set(raw.values) - {"references"})
        if unknown:
            raise OnlyInvalidMarketProductConfigurationError(
                "INVALID_CN_A_SHARE_CONFIGURATION",
                f"unknown configuration fields: {', '.join(unknown)}",
            )
        values = raw.values.get("references")
        if not isinstance(values, tuple) or not values:
            raise OnlyInvalidMarketProductConfigurationError(
                "INVALID_CN_A_SHARE_CONFIGURATION",
                "references must be a non-empty array",
            )
        try:
            references = tuple(
                OnlyCnAshareInstrumentReference.from_mapping(value) for value in values if isinstance(value, Mapping)
            )
        except (TypeError, ValueError) as exc:
            raise OnlyInvalidMarketProductConfigurationError("INVALID_CN_A_SHARE_CONFIGURATION", str(exc)) from exc
        if len(references) != len(values):
            raise OnlyInvalidMarketProductConfigurationError(
                "INVALID_CN_A_SHARE_CONFIGURATION", "each reference must be an object"
            )
        return cls(references)


__all__ = ["OnlyCnAshareConfig"]
