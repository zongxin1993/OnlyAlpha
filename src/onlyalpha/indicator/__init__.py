"""Public Indicator API with lazy exports to preserve dependency direction."""

from importlib import import_module

from onlyalpha.indicator.identifiers import OnlyIndicatorId, OnlyIndicatorTypeId

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
}


def __getattr__(name: str) -> object:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    return getattr(import_module(module_name), attribute)


__all__ = ["OnlyIndicatorId", "OnlyIndicatorTypeId", *_EXPORTS]
