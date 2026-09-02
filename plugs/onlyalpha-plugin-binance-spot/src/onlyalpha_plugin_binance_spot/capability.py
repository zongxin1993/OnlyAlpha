"""Binance protocol vocabulary interpreted at the plugin boundary."""

from enum import StrEnum

from onlyalpha.plugin.api import OnlyOrderType, OnlyTimeInForce


class OnlyBinanceSpotCompatibilityStatus(StrEnum):
    COMPATIBLE = "COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"


class OnlyBinanceSpotOrderGroupCapability(StrEnum):
    OCO = "OCO"
    OTO = "OTO"
    OPO = "OPO"


class OnlyBinanceSpotExecutionInstruction(StrEnum):
    POST_ONLY = "POST_ONLY"


_ORDER_TYPES = {
    "LIMIT": (OnlyOrderType.LIMIT, None),
    "MARKET": (OnlyOrderType.MARKET, None),
    "STOP_LOSS": (OnlyOrderType.STOP_MARKET, None),
    "STOP_LOSS_LIMIT": (OnlyOrderType.STOP_LIMIT, None),
    "TAKE_PROFIT": (OnlyOrderType.MARKET_IF_TOUCHED, None),
    "TAKE_PROFIT_LIMIT": (OnlyOrderType.LIMIT_IF_TOUCHED, None),
    "LIMIT_MAKER": (OnlyOrderType.LIMIT, OnlyBinanceSpotExecutionInstruction.POST_ONLY),
}


def only_map_order_type(value: str) -> tuple[OnlyOrderType, OnlyBinanceSpotExecutionInstruction | None]:
    try:
        return _ORDER_TYPES[value]
    except KeyError as exc:
        raise ValueError(f"BINANCE_SPOT_ORDER_TYPE_UNKNOWN: {value}") from exc


def only_map_time_in_force(value: str) -> OnlyTimeInForce:
    if value not in {"GTC", "IOC", "FOK"}:
        raise ValueError(f"BINANCE_SPOT_TIME_IN_FORCE_UNKNOWN: {value}")
    return OnlyTimeInForce(value)


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
