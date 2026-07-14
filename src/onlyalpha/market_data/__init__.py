"""Lazy public exports which keep market-data submodules cycle-free."""

from importlib import import_module

_EXPORTS = {
    "OnlyBarCache": "onlyalpha.market_data.cache",
    "OnlyMarketDataCache": "onlyalpha.market_data.cache",
    "OnlyBarDispatchResult": "onlyalpha.market_data.dispatcher",
    "OnlyClusterBarSubscription": "onlyalpha.market_data.dispatcher",
    "OnlyStrategyBarDispatcher": "onlyalpha.market_data.dispatcher",
    "OnlyDataReadyBarrier": "onlyalpha.market_data.pipeline",
    "OnlyMarketDataPipeline": "onlyalpha.market_data.pipeline",
    "OnlyMarketDataUpdateResult": "onlyalpha.market_data.pipeline",
    "OnlyBarSnapshot": "onlyalpha.market_data.snapshot",
    "OnlyMarketDataSnapshot": "onlyalpha.market_data.snapshot",
    "OnlyBarDeliveryMode": "onlyalpha.market_data.subscriptions",
    "OnlyBarSubscription": "onlyalpha.market_data.subscriptions",
    "OnlyBarSubscriptionSet": "onlyalpha.market_data.subscriptions",
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
