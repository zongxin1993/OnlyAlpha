"""Lazy public Runtime exports which avoid Runtime/Cluster import cycles."""

from importlib import import_module

_EXPORTS = {
    "OnlyRuntimeContext": "onlyalpha.runtime.context",
    "OnlyRuntimeContextView": "onlyalpha.runtime.context",
    "OnlyBacktestRuntime": "onlyalpha.runtime.runtime",
    "OnlyRuntime": "onlyalpha.runtime.runtime",
    "OnlyRuntimeConfig": "onlyalpha.runtime.runtime",
    "OnlyRuntimeManager": "onlyalpha.runtime.runtime",
    "OnlyRuntimeState": "onlyalpha.runtime.runtime",
    "OnlyRuntimeStatus": "onlyalpha.runtime.runtime",
    "OnlyRuntimeTradeResult": "onlyalpha.runtime.runtime",
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
