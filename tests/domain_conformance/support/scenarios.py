"""Ten deterministic pure-Domain market scenarios."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal

from onlyalpha.domain.account import OnlyPnL, OnlyPnLCalculator, OnlyPosition
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyLiquiditySide,
    OnlyOffset,
    OnlyOrderSide,
    OnlyOrderStatus,
    OnlyOrderType,
    OnlyPositionDirection,
    OnlyPriceType,
    OnlySessionType,
    OnlyTimeInForce,
)
from onlyalpha.domain.execution import OnlyOrderFill, OnlyOrderRequest, OnlyTrade
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyOrderRequestId,
    OnlyPositionId,
    OnlyRuntimeId,
    OnlyTradeId,
    OnlyVenueOrderId,
)
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType, OnlyTradeTick
from onlyalpha.domain.market_rules import (
    OnlyFeeSchedule,
    OnlyLotSizeRule,
    OnlyMarketRule,
    OnlySettlementRule,
    OnlyTradingRule,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity, OnlyRate
from onlyalpha.order.id_generator import OnlySequenceClientOrderIdGenerator, OnlySequenceOrderIdGenerator
from onlyalpha.order.manager import OnlyOrderManager

from .instruments import build_instruments


@dataclass(frozen=True, slots=True)
class OnlyScenarioResult:
    name: str
    passed: bool
    reason: str = ""


ONLY_PRICES = {
    "a_share": "10.00",
    "a_share_etf": "4.00",
    "hong_kong_equity": "300.00",
    "us_fractional": "200.00",
    "china_future": "4000.0",
    "option": "5.00",
    "fx_pair": "1.1000",
    "crypto_spot": "50000.00",
    "linear_perpetual": "50000.00",
    "inverse_perpetual": "50000.00",
}
ONLY_QUANTITIES = {
    "a_share": "100",
    "a_share_etf": "100",
    "hong_kong_equity": "100",
    "us_fractional": "0.500",
    "china_future": "1",
    "option": "1",
    "fx_pair": "1000",
    "crypto_spot": "0.001000",
    "linear_perpetual": "1",
    "inverse_perpetual": "100",
}


def _run(name: str, instrument: OnlyInstrument) -> OnlyScenarioResult:
    try:
        now = datetime(2026, 1, 5, 1, 30, tzinfo=UTC)
        price = OnlyPrice(Decimal(ONLY_PRICES[name]), instrument.price_precision)
        quantity = OnlyQuantity(Decimal(ONLY_QUANTITIES[name]), instrument.quantity_precision)
        lot = instrument.lot_size.value if instrument.lot_size else instrument.step_size.value
        minimum = instrument.minimum_notional
        calendar = OnlyTradingCalendar(
            f"{name}-calendar",
            instrument.instrument_id.venue,
            "UTC",
            (OnlyTradingSession("regular", time(0), time(23, 59, 59)),),
            (),
            (),
        )
        fee = OnlyFeeSchedule(
            f"{name}-fees",
            OnlyRate(Decimal("0.0001"), 4),
            OnlyRate(Decimal("0.0002"), 4),
            OnlyMoney(Decimal(1).scaleb(-instrument.quote_currency.precision), instrument.quote_currency),
            datetime(2020, 1, 1, tzinfo=UTC),
        )
        rule = OnlyMarketRule(
            name,
            OnlyLotSizeRule(lot, instrument.step_size.value),
            OnlySettlementRule(1),
            OnlyTradingRule(minimum),
            fee_schedule=fee,
            calendar=calendar,
        )
        offset = OnlyOffset.OPEN if instrument.market_type.value == "DERIVATIVE" else OnlyOffset.NONE
        request = OnlyOrderRequest(
            OnlyOrderRequestId(f"{name}-request"),
            instrument.instrument_id,
            OnlyOrderSide.BUY,
            OnlyOrderType.LIMIT,
            quantity,
            OnlyTimeInForce.DAY,
            account_id=OnlyAccountId("demo"),
            offset=offset,
            price=price,
        )
        validation = rule.validate_order(instrument, request)
        if not validation.is_valid:
            return OnlyScenarioResult(name, False, ",".join(validation.violations))
        runtime_id = OnlyRuntimeId("demo-runtime")
        manager = OnlyOrderManager(
            OnlyEngineId("demo-engine"),
            runtime_id,
            OnlySequenceOrderIdGenerator(runtime_id),
            OnlySequenceClientOrderIdGenerator(runtime_id),
        )
        timestamp = OnlyTimestamp.from_datetime(now)
        created = manager.create_order(request, OnlyClusterId("demo"), OnlyAccountId("demo"), timestamp)
        manager.mark_submitted(created.order_id, timestamp)
        manager.apply_accepted(created.order_id, timestamp, OnlyVenueOrderId(f"{name}-venue"))
        order = manager.apply_fill(
            OnlyOrderFill(
                OnlyTradeId(f"{name}-fill"),
                created.order_id,
                price,
                quantity,
                timestamp,
                timestamp,
            )
        ).snapshot
        if order.status is not OnlyOrderStatus.FILLED:
            return OnlyScenarioResult(name, False, "order_not_filled")
        notional_quantum = Decimal(1).scaleb(-instrument.quote_currency.precision)
        notional = OnlyMoney(
            (price.value * quantity.value).quantize(notional_quantum),
            instrument.quote_currency,
        )
        commission = fee.calculate(notional, OnlyLiquiditySide.TAKER)
        trade = OnlyTrade(
            OnlyTradeId(f"{name}-trade"),
            order.order_id,
            order.account_id,
            instrument.instrument_id,
            request.side,
            request.offset,
            price,
            quantity,
            commission,
            OnlyLiquiditySide.TAKER,
            now,
        )
        current = OnlyPrice(price.value + instrument.tick_size.value, instrument.price_precision)
        unrealized = OnlyPnLCalculator.unrealized(instrument, OnlyPositionDirection.LONG, quantity, price, current)
        zero = OnlyMoney(Decimal(0).quantize(Decimal(1).scaleb(-unrealized.currency.precision)), unrealized.currency)
        position = OnlyPosition(
            OnlyPositionId(f"{name}-position"),
            order.account_id,
            instrument.instrument_id,
            OnlyPositionDirection.LONG,
            quantity,
            quantity,
            price,
            OnlyPnL(zero, unrealized),
            now,
            now,
            trade_ids=(trade.trade_id,),
            settlement_currency=instrument.settlement_currency,
        )
        tick = OnlyTradeTick(
            instrument.instrument_id, now, now, 1, "demo", price, quantity, request.side, trade.trade_id
        )
        bar = OnlyBar(
            bar_type=OnlyBarType(
                instrument.instrument_id,
                OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
                OnlyAggregationSource.EXTERNAL,
            ),
            open=price,
            high=current,
            low=price,
            close=current,
            volume=quantity,
            quote_volume=None,
            turnover=notional,
            trade_count=1,
            open_interest=None,
            bar_start=now,
            bar_end=datetime(2026, 1, 5, 1, 31, tzinfo=UTC),
            ts_event=datetime(2026, 1, 5, 1, 31, tzinfo=UTC),
            ts_init=datetime(2026, 1, 5, 1, 31, tzinfo=UTC),
            is_closed=True,
            revision=0,
            adjustment_type=OnlyAdjustmentType.RAW,
            trading_day=date(2026, 1, 5),
            session_type=OnlySessionType.REGULAR,
        )
        objects = (instrument, rule, tick, bar, order, trade, position)
        if not all(type(item).from_json(item.to_json()) == item for item in objects):
            return OnlyScenarioResult(name, False, "serialization")
        return OnlyScenarioResult(name, True)
    except Exception as exc:
        return OnlyScenarioResult(name, False, f"{type(exc).__name__}: {exc}")


def run_all_scenarios() -> tuple[OnlyScenarioResult, ...]:
    return tuple(_run(name, instrument) for name, instrument in build_instruments().items())
