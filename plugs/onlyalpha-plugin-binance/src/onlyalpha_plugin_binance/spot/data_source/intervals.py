"""Exact Binance Spot intraday kline intervals admitted by this plugin."""

from onlyalpha.domain.enums import OnlyBarAggregation, OnlyPriceType
from onlyalpha.domain.market import OnlyBarSpecification
from onlyalpha_plugin_binance.errors import OnlyBinanceError

NATIVE_INTERVALS: dict[int, str] = {
    1: "1m",
    3: "3m",
    5: "5m",
    15: "15m",
    30: "30m",
    60: "1h",
    120: "2h",
    240: "4h",
}


def only_binance_bar_interval(specification: OnlyBarSpecification) -> str:
    if specification.aggregation is not OnlyBarAggregation.TIME or specification.price_type is not OnlyPriceType.LAST:
        raise OnlyBinanceError("BINANCE_BAR_SPECIFICATION_UNSUPPORTED")
    try:
        return NATIVE_INTERVALS[specification.step]
    except KeyError as exc:
        raise OnlyBinanceError("BINANCE_BAR_SPECIFICATION_UNSUPPORTED") from exc
