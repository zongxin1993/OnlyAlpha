"""Factor API with lazy exports to avoid importing outer configuration layers."""

from importlib import import_module

from onlyalpha.factor.identifiers import OnlyFactorId

_EXPORTS = {
    "OnlyFactor": ("onlyalpha.factor.base", "OnlyFactor"),
    "OnlyTimeSeriesFactor": ("onlyalpha.factor.base", "OnlyTimeSeriesFactor"),
    "OnlyCrossSectionFactor": ("onlyalpha.factor.base", "OnlyCrossSectionFactor"),
    "OnlyFactorConfig": ("onlyalpha.factor.config", "OnlyFactorConfig"),
    "OnlyFactorType": ("onlyalpha.factor.config", "OnlyFactorType"),
    "OnlyIndicatorSpec": ("onlyalpha.factor.config", "OnlyIndicatorSpec"),
    "OnlyFactorDependencyGraph": ("onlyalpha.factor.dependency", "OnlyFactorDependencyGraph"),
    "OnlyFactorExecutionPlan": ("onlyalpha.factor.dependency", "OnlyFactorExecutionPlan"),
    "OnlyCrossSectionUniverseSnapshot": ("onlyalpha.factor.context", "OnlyCrossSectionUniverseSnapshot"),
    "OnlyFactorScore": ("onlyalpha.factor.score", "OnlyFactorScore"),
    "OnlyFactorScoreDimension": ("onlyalpha.factor.score", "OnlyFactorScoreDimension"),
    "OnlyFactorSnapshot": ("onlyalpha.factor.snapshot", "OnlyFactorSnapshot"),
}


def __getattr__(name: str) -> object:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    return getattr(import_module(module_name), attribute)


__all__ = ["OnlyFactorId", *_EXPORTS]
