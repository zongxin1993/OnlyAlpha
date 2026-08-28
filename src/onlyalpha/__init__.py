"""OnlyAlpha public skeleton API."""

# ruff: noqa: F401

from importlib import import_module as _import_module

from onlyalpha.cache.memory import OnlyMemoryCache
from onlyalpha.core.clock import (
    OnlyBacktestClock,
    OnlyClock,
    OnlyClockView,
    OnlyLiveClock,
    OnlyTimerEvent,
    OnlyTimerId,
    OnlyVirtualClock,
)
from onlyalpha.domain.account import OnlyAccountEquity
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEvent
from onlyalpha.market_data.cache import OnlyMarketDataCache
from onlyalpha.market_data.pipeline import OnlyMarketDataPipeline
from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot
from onlyalpha.market_data.subscriptions import OnlyBarSubscription
from onlyalpha.storage.sqlite import OnlySqliteStorage

_LAZY_EXPORTS = {
    "OnlyRuntimeState": "onlyalpha.runtime.runtime",
    "OnlyRuntimeStatus": "onlyalpha.runtime.runtime",
}

__all__ = [
    "OnlyBacktestClock",
    "OnlyBarSubscription",
    "OnlyClock",
    "OnlyClockView",
    "OnlyEvent",
    "OnlyEventBus",
    "OnlyLiveClock",
    "OnlyMarketDataCache",
    "OnlyMarketDataPipeline",
    "OnlyMarketDataSnapshot",
    "OnlyMemoryCache",
    "OnlyRuntimeState",
    "OnlyRuntimeStatus",
    "OnlySqliteStorage",
    "OnlyTimerEvent",
    "OnlyTimerId",
    "OnlyVirtualClock",
]


def __getattr__(name: str) -> object:
    try:
        module_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value: object = getattr(_import_module(module_name), name)
    globals()[name] = value
    return value
