"""Exact Binance Spot intraday kline intervals admitted by this plugin."""

from onlyalpha.domain.enums import OnlyPriceType
from onlyalpha.domain.market import OnlyBarSemantic
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


def only_binance_bar_interval(semantic: OnlyBarSemantic) -> str:
    if not semantic.is_fixed_duration or not semantic.is_aligned or semantic.price_type is not OnlyPriceType.LAST:
        raise OnlyBinanceError("BINANCE_BAR_SPECIFICATION_UNSUPPORTED")
    try:
        return NATIVE_INTERVALS[semantic.window_minutes]
    except KeyError as exc:
        raise OnlyBinanceError("BINANCE_BAR_SPECIFICATION_UNSUPPORTED") from exc
