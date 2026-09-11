"""OnlyAlpha public skeleton API."""

from importlib import import_module as _import_module
from typing import TYPE_CHECKING as _TYPE_CHECKING

if _TYPE_CHECKING:
    from onlyalpha.cache.memory import OnlyMemoryCache as OnlyMemoryCache
    from onlyalpha.core.clock import OnlyBacktestClock as OnlyBacktestClock
    from onlyalpha.core.clock import OnlyClock as OnlyClock
    from onlyalpha.core.clock import OnlyClockView as OnlyClockView
    from onlyalpha.core.clock import OnlyLiveClock as OnlyLiveClock
    from onlyalpha.core.clock import OnlyTimerEvent as OnlyTimerEvent
    from onlyalpha.core.clock import OnlyTimerId as OnlyTimerId
    from onlyalpha.core.clock import OnlyVirtualClock as OnlyVirtualClock
    from onlyalpha.domain.account import OnlyAccountEquity as OnlyAccountEquity
    from onlyalpha.domain.value import OnlyCurrency as OnlyCurrency
    from onlyalpha.domain.value import OnlyMoney as OnlyMoney
    from onlyalpha.domain.value import OnlyPrice as OnlyPrice
    from onlyalpha.domain.value import OnlyQuantity as OnlyQuantity
    from onlyalpha.event.bus import OnlyEventBus as OnlyEventBus
    from onlyalpha.event.model import OnlyEvent as OnlyEvent
    from onlyalpha.market_data.cache import OnlyMarketDataCache as OnlyMarketDataCache
    from onlyalpha.market_data.pipeline import OnlyMarketDataPipeline as OnlyMarketDataPipeline
    from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot as OnlyMarketDataSnapshot
    from onlyalpha.market_data.subscriptions import OnlyBarSubscription as OnlyBarSubscription
    from onlyalpha.storage.sqlite import OnlySqliteStorage as OnlySqliteStorage

_LAZY_EXPORTS = {
    "OnlyAccountEquity": "onlyalpha.domain.account",
    "OnlyBacktestClock": "onlyalpha.core.clock",
    "OnlyBarSubscription": "onlyalpha.market_data.subscriptions",
    "OnlyClock": "onlyalpha.core.clock",
    "OnlyClockView": "onlyalpha.core.clock",
    "OnlyCurrency": "onlyalpha.domain.value",
    "OnlyEvent": "onlyalpha.event.model",
    "OnlyEventBus": "onlyalpha.event.bus",
    "OnlyLiveClock": "onlyalpha.core.clock",
    "OnlyMarketDataCache": "onlyalpha.market_data.cache",
    "OnlyMarketDataPipeline": "onlyalpha.market_data.pipeline",
    "OnlyMarketDataSnapshot": "onlyalpha.market_data.snapshot",
    "OnlyMemoryCache": "onlyalpha.cache.memory",
    "OnlyMoney": "onlyalpha.domain.value",
    "OnlyPrice": "onlyalpha.domain.value",
    "OnlyQuantity": "onlyalpha.domain.value",
    "OnlyRuntimeState": "onlyalpha.runtime.runtime",
    "OnlyRuntimeStatus": "onlyalpha.runtime.runtime",
    "OnlySqliteStorage": "onlyalpha.storage.sqlite",
    "OnlyTimerEvent": "onlyalpha.core.clock",
    "OnlyTimerId": "onlyalpha.core.clock",
    "OnlyVirtualClock": "onlyalpha.core.clock",
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
