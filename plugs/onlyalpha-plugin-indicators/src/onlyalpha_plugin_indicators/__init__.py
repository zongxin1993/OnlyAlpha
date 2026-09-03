"""Official Indicator plugin public API."""
# ruff: noqa: F401

from onlyalpha_plugin_indicators.macd import OnlyMacdIndicator, OnlyMacdIndicatorConfig
from onlyalpha_plugin_indicators.registration import (
    ATR_V2,
    B1_FINANCIAL_TYPES,
    OnlyIndicatorBackendRequest,
    registrations,
    resolve_definition,
)
from onlyalpha_plugin_indicators.research import OnlyOfficialResearchIndicatorBackend
from onlyalpha_plugin_indicators.snapshots import (
    OnlyAtrSnapshot,
    OnlyBollingerSnapshot,
    OnlyMacdCrossState,
    OnlyMacdSnapshot,
    OnlyRsiSnapshot,
)

__all__ = [
    name
    for name in globals()
    if name.startswith("Only") or name in {"ATR_V2", "B1_FINANCIAL_TYPES", "registrations", "resolve_definition"}
]
