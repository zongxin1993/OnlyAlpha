"""Lazy public exports for the shared long-lived Runtime kernel."""

from importlib import import_module

_EXPORTS = {
    "OnlyExecutionSubmissionCapability": "onlyalpha.runtime.streaming.execution",
    "OnlyLiveBarFinalizationError": "onlyalpha.runtime.streaming.live_bar",
    "OnlyLiveBarFinalizer": "onlyalpha.runtime.streaming.live_bar",
    "OnlyShadowExecutionService": "onlyalpha.runtime.streaming.execution",
    "OnlyStreamingDataState": "onlyalpha.runtime.streaming.phase",
    "OnlyStreamingMarketDataWorker": "onlyalpha.runtime.streaming.worker",
    "OnlyStreamingPhase": "onlyalpha.runtime.streaming.phase",
    "OnlyStreamingRecoveryPlan": "onlyalpha.runtime.streaming.recovery",
    "OnlyStreamingRecoveryReason": "onlyalpha.runtime.streaming.recovery",
    "OnlyStreamingRuntime": "onlyalpha.runtime.streaming.runtime",
    "OnlyStreamingRuntimeConfig": "onlyalpha.runtime.streaming.config",
    "OnlyStreamingRuntimeHealth": "onlyalpha.runtime.streaming.health",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> object:
    try:
        module_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value: object = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
