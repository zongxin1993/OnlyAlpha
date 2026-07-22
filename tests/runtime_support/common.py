"""Shared deterministic RuntimeContext demo fixtures."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyMarketType,
    OnlyPriceType,
    OnlyRuntimeMode,
    OnlySessionType,
)
from onlyalpha.domain.identifiers import (
    OnlyCalendarId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyRawSymbol,
    OnlySymbol,
    OnlyVenueId,
)
from onlyalpha.domain.instrument import OnlyEquity
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.time import OnlyTimeZone
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.runtime import OnlyRuntimeAssemblyConfig


def only_demo_bar_types() -> tuple[OnlyBarType, OnlyBarType]:
    instrument_id = OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG"))
    return (
        OnlyBarType(
            instrument_id,
            OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            OnlyAggregationSource.EXTERNAL,
        ),
        OnlyBarType(
            instrument_id,
            OnlyBarSpecification(3, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            OnlyAggregationSource.INTERNAL,
        ),
    )


def only_demo_runtime(runtime_id: str, cluster_ids: tuple[str, ...] = ("cluster",)) -> OnlyBacktestRuntime:
    calendar = OnlyTradingCalendar(
        OnlyCalendarId("XSHG"),
        OnlyVenueId("XSHG"),
        OnlyTimeZone("Asia/Shanghai"),
        (
            OnlyTradingSession("morning", time(9, 30), time(11, 30), OnlySessionType.CONTINUOUS),
            OnlyTradingSession("afternoon", time(13), time(15), OnlySessionType.CONTINUOUS),
        ),
    )
    cny = OnlyCurrency("CNY", 2)
    capital_amount = Decimal("1000000.00") / Decimal(len(cluster_ids))
    capitals = {OnlyClusterId(cluster_id): OnlyMoney(capital_amount, cny) for cluster_id in cluster_ids}
    runtime = OnlyBacktestRuntime(
        OnlyRuntimeAssemblyConfig(
            "engine",
            runtime_id,
            OnlyRuntimeMode.BACKTEST,
            strategy_base_currency=cny,
            strategy_capitals=capitals,
            account_initial_cash=OnlyMoney(Decimal("1000000.00"), cny),
        ),
        calendar,
        datetime(2026, 1, 5, 1, 30, tzinfo=UTC),
    )
    instrument_id = only_demo_bar_types()[0].instrument_id
    runtime.register_instrument(
        OnlyEquity(
            instrument_id=instrument_id,
            raw_symbol=OnlyRawSymbol("600000"),
            market_type=OnlyMarketType.CASH,
            quote_currency=cny,
            settlement_currency=cny,
            price_precision=2,
            quantity_precision=0,
            tick_size=OnlyPrice(Decimal("0.01"), 2),
            step_size=OnlyQuantity(Decimal("1"), 0),
            contract_multiplier=OnlyMultiplier(Decimal("1"), 0),
        )
    )
    return runtime


def only_demo_bar(bar_type: OnlyBarType, minute: int, *, base_price: str = "10.00") -> OnlyBar:
    start = datetime(2026, 1, 5, 1, 30, tzinfo=UTC) + timedelta(minutes=minute)
    price = Decimal(base_price) + Decimal(minute) / Decimal(100)
    return OnlyBar(
        bar_type=bar_type,
        open=OnlyPrice(price, 2),
        high=OnlyPrice(price + Decimal("0.10"), 2),
        low=OnlyPrice(price - Decimal("0.10"), 2),
        close=OnlyPrice(price + Decimal("0.05"), 2),
        volume=OnlyQuantity(Decimal("100"), 0),
        quote_volume=None,
        turnover=None,
        trade_count=1,
        open_interest=None,
        bar_start=start,
        bar_end=start + timedelta(minutes=1),
        ts_event=start + timedelta(minutes=1),
        ts_init=start + timedelta(minutes=1),
        is_closed=True,
        revision=0,
        adjustment_type=OnlyAdjustmentType.RAW,
        trading_day=date(2026, 1, 5),
        session_type=OnlySessionType.CONTINUOUS,
    )
