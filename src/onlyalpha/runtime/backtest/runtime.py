"""Finite historical Runtime facade."""

from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.runtime.trading_facade import OnlyTradingRuntimeFacade


class OnlyBacktestRuntime(OnlyTradingRuntimeFacade):
    """Trading Kernel composed with the finite historical Backtest driver."""

    _supported_modes = frozenset({OnlyRuntimeMode.BACKTEST})
