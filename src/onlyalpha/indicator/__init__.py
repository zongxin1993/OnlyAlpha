"""Public Indicator API with lazy exports to preserve dependency direction."""

from importlib import import_module
from typing import TYPE_CHECKING

from onlyalpha.indicator.identifiers import OnlyIndicatorId, OnlyIndicatorTypeId

if TYPE_CHECKING:
    from onlyalpha.indicator.registry import OnlyIndicatorFactoryRegistry

_EXPORTS = {
    "OnlyIndicator": ("onlyalpha.indicator.base", "OnlyIndicator"),
    "OnlyBarIndicator": ("onlyalpha.indicator.base", "OnlyBarIndicator"),
    "OnlyIndicatorCreateRequest": ("onlyalpha.indicator.factory", "OnlyIndicatorCreateRequest"),
    "OnlyIndicatorFactoryRegistry": ("onlyalpha.indicator.registry", "OnlyIndicatorFactoryRegistry"),
    "OnlyIndicatorInstanceKey": ("onlyalpha.indicator.registry", "OnlyIndicatorInstanceKey"),
    "OnlyIndicatorScore": ("onlyalpha.indicator.score", "OnlyIndicatorScore"),
    "OnlyIndicatorScoreDimension": ("onlyalpha.indicator.score", "OnlyIndicatorScoreDimension"),
    "OnlyIndicatorSnapshot": ("onlyalpha.indicator.snapshot", "OnlyIndicatorSnapshot"),
    "OnlyWarmupProgress": ("onlyalpha.indicator.snapshot", "OnlyWarmupProgress"),
    "OnlyMacdIndicator": ("onlyalpha.indicator.macd", "OnlyMacdIndicator"),
    "OnlyMacdIndicatorConfig": ("onlyalpha.indicator.macd", "OnlyMacdIndicatorConfig"),
    "OnlyMacdIndicatorFactory": ("onlyalpha.indicator.macd", "OnlyMacdIndicatorFactory"),
    "OnlyMacdSnapshot": ("onlyalpha.indicator.macd", "OnlyMacdSnapshot"),
    "OnlyMacdCrossState": ("onlyalpha.indicator.macd", "OnlyMacdCrossState"),
    "OnlyRsiSnapshot": ("onlyalpha.indicator.rsi", "OnlyRsiSnapshot"),
    "OnlyAtrSnapshot": ("onlyalpha.indicator.atr", "OnlyAtrSnapshot"),
    "OnlyBollingerSnapshot": ("onlyalpha.indicator.bollinger", "OnlyBollingerSnapshot"),
}


def __getattr__(name: str) -> object:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    return getattr(import_module(module_name), attribute)


def only_default_indicator_factories() -> "OnlyIndicatorFactoryRegistry":
    from onlyalpha.indicator.atr import OnlyAtrIndicatorFactory
    from onlyalpha.indicator.bollinger import OnlyBollingerIndicatorFactory
    from onlyalpha.indicator.ema import OnlyEmaIndicatorFactory
    from onlyalpha.indicator.macd import OnlyMacdIndicatorFactory
    from onlyalpha.indicator.registry import OnlyIndicatorFactoryRegistry
    from onlyalpha.indicator.rolling_return import OnlyRollingReturnIndicatorFactory
    from onlyalpha.indicator.rolling_volatility import OnlyRollingVolatilityIndicatorFactory
    from onlyalpha.indicator.rsi import OnlyRsiIndicatorFactory
    from onlyalpha.indicator.sma import OnlySmaIndicatorFactory
    from onlyalpha.indicator.zscore import OnlyZscoreIndicatorFactory

    registry = OnlyIndicatorFactoryRegistry()
    for factory in (
        OnlyMacdIndicatorFactory(),
        OnlyRsiIndicatorFactory(),
        OnlyEmaIndicatorFactory(),
        OnlySmaIndicatorFactory(),
        OnlyAtrIndicatorFactory(),
        OnlyBollingerIndicatorFactory(),
        OnlyRollingReturnIndicatorFactory(),
        OnlyRollingVolatilityIndicatorFactory(),
        OnlyZscoreIndicatorFactory(),
    ):
        registry.register(factory)
    return registry


__all__ = ["OnlyIndicatorId", "OnlyIndicatorTypeId", "only_default_indicator_factories", *_EXPORTS]
