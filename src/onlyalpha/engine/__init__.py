"""Engine composition values; the concrete Engine constructor is internal."""

from importlib import import_module as _import_module

from onlyalpha.engine.models import (
    OnlyClusterHandle,
    OnlyClusterLoadError,
    OnlyClusterOperationResult,
    OnlyClusterRemovalPolicy,
    OnlyClusterRemovalResult,
    OnlyEngineConfig,
    OnlyEngineRunResult,
    OnlyEngineSnapshot,
    OnlyEngineState,
    OnlyEngineValidationResult,
)

__all__ = [
    "OnlyClusterHandle",
    "OnlyClusterLoadError",
    "OnlyClusterOperationResult",
    "OnlyClusterRemovalPolicy",
    "OnlyClusterRemovalResult",
    "OnlyEngineConfig",
    "OnlyEngineRunResult",
    "OnlyEngineSnapshot",
    "OnlyEngineState",
    "OnlyEngineValidationResult",
    "OnlyResearchWorkloadPlan",
]

_LAZY_EXPORTS = {"OnlyResearchWorkloadPlan": "onlyalpha.runtime.research.plan"}


def __getattr__(name: str) -> object:
    try:
        module_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value: object = getattr(_import_module(module_name), name)
    globals()[name] = value
    return value
