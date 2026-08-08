from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from onlyalpha_plugin_broker_virtual import OnlyVirtualBrokerConfig, OnlyVirtualBrokerGateway
from onlyalpha_plugin_broker_virtual.fill_plan import OnlyVirtualFillDispatchMode, OnlyVirtualFillScheduleMode

from onlyalpha.broker import OnlyBrokerGatewayId, OnlyBrokerOrderRequest, OnlyBrokerRequestId
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyOffset,
    OnlyOrderSide,
    OnlyOrderType,
    OnlyPriceType,
    OnlySessionType,
    OnlyTimeInForce,
)
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClientOrderId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlySymbol,
    OnlyVenueId,
)
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity

CNY = OnlyCurrency("CNY", 2)
ACCOUNT = OnlyAccountId("virtual-account")
INSTRUMENT = OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG"))
START = datetime(2026, 1, 5, 1, 30, tzinfo=UTC)
BAR_TYPE = OnlyBarType(
    INSTRUMENT,
    OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
    OnlyAggregationSource.EXTERNAL,
)


def bar(day: date, minute: int, *, low: str = "9.90", high: str = "10.10") -> OnlyBar:
    start = datetime.combine(day, time(1, 30), tzinfo=UTC) + timedelta(minutes=minute)
    return OnlyBar(
        bar_type=BAR_TYPE,
        open=OnlyPrice(Decimal("10.00"), 2),
        high=OnlyPrice(Decimal(high), 2),
        low=OnlyPrice(Decimal(low), 2),
        close=OnlyPrice(Decimal("10.00"), 2),
        volume=OnlyQuantity(Decimal("1000"), 0),
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
        trading_day=day,
        session_type=OnlySessionType.CONTINUOUS,
    )


def order(sequence: int, side: OnlyOrderSide = OnlyOrderSide.BUY) -> OnlyBrokerOrderRequest:
    return OnlyBrokerOrderRequest(
        OnlyBrokerRequestId(f"request-{sequence}"),
        OnlyOrderId(f"order-{sequence}"),
        OnlyClientOrderId(f"client-{sequence}"),
        ACCOUNT,
        INSTRUMENT,
        side,
        OnlyOffset.OPEN if side is OnlyOrderSide.BUY else OnlyOffset.CLOSE,
        OnlyOrderType.LIMIT,
        OnlyTimeInForce.DAY,
        OnlyQuantity(Decimal("100"), 0),
        OnlyPrice(Decimal("10.00"), 2),
        OnlyTimestamp.from_datetime(START + timedelta(minutes=1)),
    )


def schedule_gateway(
    *, steps: Any, dispatch: OnlyVirtualFillDispatchMode = OnlyVirtualFillDispatchMode.ONE_PER_BAR
) -> tuple[OnlyBacktestClock, OnlyVirtualBrokerGateway, list[object]]:
    clock = OnlyBacktestClock(START)
    updates: list[object] = []
    gateway = OnlyVirtualBrokerGateway(
        OnlyVirtualBrokerConfig(
            OnlyBrokerGatewayId("schedule"),
            ACCOUNT,
            CNY,
            OnlyMoney(Decimal("100000.00"), CNY),
            fill_schedule_mode=OnlyVirtualFillScheduleMode.SCHEDULE,
            fill_dispatch_mode=dispatch,
            fill_schedule_steps=steps,
        ),
        OnlyRuntimeId("schedule-runtime"),
        clock,
        updates.append,
    )
    gateway.connect()
    gateway.authenticate()
    return clock, gateway, updates


def accept_scheduled_order(clock: OnlyBacktestClock, gateway: OnlyVirtualBrokerGateway) -> None:
    first = bar(date(2026, 1, 5), 0)
    clock.advance_to(first.ts_event)
    gateway.on_bar(first)
    gateway.submit_order(order(1))
    gateway.run_due()
