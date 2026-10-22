"""Public API; individual capabilities load only when explicitly requested."""

from importlib import import_module

_EXPORTS = {
    "OnlyMacdIndicator": ("onlyalpha_plugin_indicators.macd", "OnlyMacdIndicator"),
    "OnlyMacdIndicatorConfig": ("onlyalpha_plugin_indicators.macd", "OnlyMacdIndicatorConfig"),
    "ATR_V2": ("onlyalpha_plugin_indicators.registration", "ATR_V2"),
    "FINANCIAL_TYPES": ("onlyalpha_plugin_indicators.registration", "FINANCIAL_TYPES"),
    "OnlyIndicatorBackendRequest": ("onlyalpha_plugin_indicators.registration", "OnlyIndicatorBackendRequest"),
    "registrations": ("onlyalpha_plugin_indicators.registration", "registrations"),
    "resolve_definition": ("onlyalpha_plugin_indicators.registration", "resolve_definition"),
    "OnlyOfficialResearchIndicatorBackend": (
        "onlyalpha_plugin_indicators.research",
        "OnlyOfficialResearchIndicatorBackend",
    ),
    "OnlyAtrSnapshot": ("onlyalpha_plugin_indicators.snapshots", "OnlyAtrSnapshot"),
    "OnlyBollingerSnapshot": ("onlyalpha_plugin_indicators.snapshots", "OnlyBollingerSnapshot"),
    "OnlyMacdCrossState": ("onlyalpha_plugin_indicators.snapshots", "OnlyMacdCrossState"),
    "OnlyMacdSnapshot": ("onlyalpha_plugin_indicators.snapshots", "OnlyMacdSnapshot"),
    "OnlyRsiSnapshot": ("onlyalpha_plugin_indicators.snapshots", "OnlyRsiSnapshot"),
}


def __getattr__(name: str) -> object:
    try:
        module, member = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(name) from error
    value = getattr(import_module(module), member)
    globals()[name] = value
    return value


__all__ = sorted(
    set(_EXPORTS)
    | {name for name in globals() if name.startswith(("Only", "only_", "FACTOR_", "PREDICATE_", "TARGET_"))}
)
