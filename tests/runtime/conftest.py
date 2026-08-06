from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest

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
from onlyalpha.domain.time import OnlyTimeZone, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.fee.packs import only_generic_t0_cash_fee_pack
from onlyalpha.market.models import OnlyMarketProfileId
from onlyalpha.market.profiles import only_builtin_market_profile_registry
from onlyalpha.market.registry import OnlyMarketProfileRequest
from onlyalpha.market.runtime_rules import OnlyMarketRuleCompiler, OnlyMarketRuleEngine, only_instrument_reference
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore
from onlyalpha.runtime.runtime import OnlyRuntimeAssemblyConfig


@pytest.fixture
def runtime_types() -> tuple[OnlyBarType, OnlyBarType]:
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


@pytest.fixture
def runtime_calendar() -> OnlyTradingCalendar:
    return OnlyTradingCalendar(
        OnlyCalendarId("XSHG"),
        OnlyVenueId("XSHG"),
        OnlyTimeZone("Asia/Shanghai"),
        (
            OnlyTradingSession("morning", time(9, 30), time(11, 30), OnlySessionType.CONTINUOUS),
            OnlyTradingSession("afternoon", time(13), time(15), OnlySessionType.CONTINUOUS),
        ),
    )


@pytest.fixture
def make_runtime(
    runtime_calendar: OnlyTradingCalendar,
) -> Callable[[str, Mapping[str, str] | None], OnlyBacktestRuntime]:
    def build(runtime_id: str, capitals: Mapping[str, str] | None = None) -> OnlyBacktestRuntime:
        configured = capitals or {"demo": "1000000.00"}
        currency = OnlyCurrency("CNY", 2)
        capital = {
            OnlyClusterId(cluster_id): OnlyMoney(Decimal(amount), currency) for cluster_id, amount in configured.items()
        }
        account_cash = OnlyMoney(sum((item.amount for item in capital.values()), Decimal(0)), currency)
        instrument_id = OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG"))
        instrument = OnlyEquity(
            instrument_id=instrument_id,
            raw_symbol=OnlyRawSymbol("600000"),
            market_type=OnlyMarketType.CASH,
            quote_currency=currency,
            settlement_currency=currency,
            price_precision=2,
            quantity_precision=0,
            tick_size=OnlyPrice(Decimal("0.01"), 2),
            step_size=OnlyQuantity(Decimal("1"), 0),
            contract_multiplier=OnlyMultiplier(Decimal("1"), 0),
        )
        reference = only_instrument_reference(
            instrument,
            profile_id=OnlyMarketProfileId.GENERIC_T0_CASH.value,
        )
        market_rules = OnlyMarketRuleEngine(
            registry=only_builtin_market_profile_registry(),
            compiler=OnlyMarketRuleCompiler(),
            request=OnlyMarketProfileRequest(OnlyMarketProfileId.GENERIC_T0_CASH),
            runtime_mode=OnlyRuntimeMode.BACKTEST,
            references={str(instrument_id): reference},
            advance_trading_day=lambda day, lag: OnlyTradingDay(date.fromordinal(day.value.toordinal() + lag)),
        )
        runtime = OnlyBacktestRuntime(
            OnlyRuntimeAssemblyConfig(
                "engine",
                runtime_id,
                OnlyRuntimeMode.BACKTEST,
                strategy_base_currency=currency,
                strategy_capitals=capital,
                account_initial_cash=account_cash,
                market_rule_engine=market_rules,
                fee_policy_pack=only_generic_t0_cash_fee_pack(),
            ),
            runtime_calendar,
            datetime(2026, 1, 5, 1, 30, tzinfo=UTC),
            runtime_persistence_store=OnlyInMemoryRuntimePersistenceStore(),
        )
        runtime.register_instrument(instrument)
        return runtime

    return build


@pytest.fixture
def make_runtime_bar(runtime_types: tuple[OnlyBarType, OnlyBarType]) -> Callable[[int, str], OnlyBar]:
    bar_1m, _ = runtime_types

    def build(minute: int, close: str = "10.00") -> OnlyBar:
        start = datetime(2026, 1, 5, 1, 30, tzinfo=UTC) + timedelta(minutes=minute)
        price = Decimal(close) + Decimal(minute) / Decimal(100)
        return OnlyBar(
            bar_type=bar_1m,
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

    return build
