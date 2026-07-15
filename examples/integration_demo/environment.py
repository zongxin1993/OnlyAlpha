"""One deterministic environment assembling the existing OnlyAlpha components."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyCurrencyType,
    OnlyDirection,
    OnlyMarketType,
    OnlyOffset,
    OnlyOrderSide,
    OnlyOrderStatus,
    OnlyOrderType,
    OnlyPriceType,
    OnlyRuntimeMode,
    OnlySessionType,
)
from onlyalpha.domain.execution import OnlyOrderFill, OnlyOrderRequest, OnlyOrderSnapshot
from onlyalpha.domain.identifiers import (
    OnlyCalendarId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderRequestId,
    OnlyRawSymbol,
    OnlyRuntimeId,
    OnlySymbol,
    OnlyTradeId,
    OnlyVenueId,
    OnlyVenueOrderId,
    OnlyVenueTradeId,
)
from onlyalpha.domain.instrument import OnlyEquity
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp, OnlyTimeZone, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEvent
from onlyalpha.market_data.pipeline import OnlyMarketDataUpdateResult
from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot
from onlyalpha.market_data.subscriptions import OnlyBarSubscription
from onlyalpha.order.execution.models import OnlyGatewayOrderAcceptedUpdate, OnlyGatewayOrderFillUpdate
from onlyalpha.order.results import OnlyOrderSubmitResult
from onlyalpha.position.enums import OnlyPositionMutationStatus, OnlyPositionSide, OnlySettlementBucket
from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionSnapshot, OnlyPositionTrade
from onlyalpha.runtime.runtime import (
    OnlyBacktestRuntime,
    OnlyRuntimeConfig,
    OnlyRuntimeTradeResult,
)
from onlyalpha.strategy_ledger.models import OnlyStrategyLedgerSnapshot

ENGINE_ID = "integration-engine"
RUNTIME_ID = "integration-runtime"
CLUSTER_ID = OnlyClusterId("integration-cluster")
ACCOUNT_ID = "integration-runtime-DEFAULT"
CNY = OnlyCurrency("CNY", 2, OnlyCurrencyType.FIAT)
INSTRUMENT_ID = OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG"))
DAY_ONE = date(2026, 1, 5)
DAY_TWO = date(2026, 1, 6)


@dataclass(frozen=True, slots=True)
class OnlyRecordedEvent:
    event_type: str
    source: str
    sequence: int
    timestamp_ns: int
    cluster_id: str | None


class OnlyEventRecorder:
    """Read-only recorder over EventBus dispatch history."""

    def __init__(self) -> None:
        self._cursor = 0
        self._events: list[OnlyRecordedEvent] = []

    @property
    def events(self) -> tuple[OnlyRecordedEvent, ...]:
        return tuple(self._events)

    def capture(self, event_bus: OnlyEventBus) -> None:
        results = event_bus.dispatch_results
        for result in results[self._cursor :]:
            self._events.append(self._record(result.event))
        self._cursor = len(results)

    @staticmethod
    def _record(event: OnlyEvent) -> OnlyRecordedEvent:
        return OnlyRecordedEvent(
            str(event.event_type),
            str(event.source),
            int(event.sequence),
            0 if event.timestamp_ns is None else event.timestamp_ns,
            None if event.cluster_id is None else str(event.cluster_id),
        )


@dataclass(frozen=True, slots=True)
class OnlyIntegrationSnapshot:
    runtime_state: str
    order_snapshots: tuple[OnlyOrderSnapshot, ...]
    account_positions: tuple[OnlyPositionSnapshot, ...]
    cluster_allocations: tuple[OnlyPositionAllocationSnapshot, ...]
    ledger_snapshots: tuple[OnlyStrategyLedgerSnapshot, ...]
    active_risk_reservations: int
    position_reservation_state: str | None
    event_trace: tuple[OnlyRecordedEvent, ...]


@dataclass(frozen=True, slots=True)
class OnlyScenarioReport:
    scenario_id: str
    title: str
    passed: bool
    details: tuple[str, ...]


class OnlyReportBuilder:
    """Builds immutable scenario and final reports from public snapshots."""

    def scenario(self, scenario_id: str, title: str, *details: str) -> OnlyScenarioReport:
        return OnlyScenarioReport(scenario_id, title, True, tuple(details))

    def final_snapshot(self, env: OnlyIntegrationEnvironment) -> OnlyIntegrationSnapshot:
        position_reservation = None
        if env.sell_order is not None and env.sell_order.order_id is not None:
            reservation = env.runtime.position_reservation_manager.get(env.sell_order.order_id)
            position_reservation = None if reservation is None else reservation.state.value
        return OnlyIntegrationSnapshot(
            env.runtime.state.value,
            env.runtime.order_manager.snapshot_all(),
            env.runtime.position_manager.snapshot_all(),
            env.runtime.allocation_manager.snapshot_all(),
            env.runtime.strategy_ledger_manager.list_ledgers(),
            len(env.runtime.risk_service.reservations.snapshot_active()),
            position_reservation,
            env.event_recorder.events,
        )


class OnlyIntegrationCluster(OnlyCluster):
    """Small strategy fixture using only the production Runtime Context."""

    def __init__(self, bar_types: tuple[OnlyBarType, ...]) -> None:
        super().__init__(OnlyClusterConfig(str(CLUSTER_ID)))
        self._subscription = OnlyBarSubscription(bar_types)
        self.pending_order: OnlyOrderRequest | None = None
        self.submit_results: list[OnlyOrderSubmitResult] = []
        self.snapshots: list[OnlyMarketDataSnapshot] = []

    def on_initialize(self) -> None:
        assert self.context is not None
        self.context.subscriptions.subscribe_bars(self._subscription)

    def on_bar(self, bar: OnlyBar, context: object) -> None:
        del bar
        from onlyalpha.cluster.bar_context import OnlyBarContext

        if not isinstance(context, OnlyBarContext):
            raise TypeError("integration Cluster requires OnlyBarContext")
        self.snapshots.append(context.snapshot)
        if self.pending_order is not None:
            self.submit_results.append(context.runtime.orders.submit(self.pending_order))
            self.pending_order = None


class OnlyIntegrationEnvironment:
    """Owns one Runtime and drives the complete deterministic vertical slice."""

    def __init__(self) -> None:
        self.calendar = OnlyTradingCalendar(
            OnlyCalendarId("XSHG"),
            OnlyVenueId("XSHG"),
            OnlyTimeZone("Asia/Shanghai"),
            (
                OnlyTradingSession("morning", time(9, 30), time(11, 30), OnlySessionType.CONTINUOUS),
                OnlyTradingSession("afternoon", time(13), time(15), OnlySessionType.CONTINUOUS),
            ),
        )
        self.instrument = OnlyEquity(
            instrument_id=INSTRUMENT_ID,
            raw_symbol=OnlyRawSymbol("600000"),
            market_type=OnlyMarketType.CASH,
            quote_currency=CNY,
            settlement_currency=CNY,
            price_precision=2,
            quantity_precision=0,
            tick_size=OnlyPrice(Decimal("0.01"), 2),
            step_size=OnlyQuantity(Decimal("100"), 0),
            contract_multiplier=OnlyMultiplier(Decimal(1), 0),
            minimum_quantity=OnlyQuantity(Decimal("100"), 0),
            maximum_quantity=OnlyQuantity(Decimal("100000"), 0),
            trading_calendar_id=OnlyCalendarId("XSHG"),
            timezone="Asia/Shanghai",
        )
        self.bar_1m = OnlyBarType(
            INSTRUMENT_ID,
            OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            OnlyAggregationSource.EXTERNAL,
        )
        self.bar_3m = OnlyBarType(
            INSTRUMENT_ID,
            OnlyBarSpecification(3, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            OnlyAggregationSource.INTERNAL,
        )
        self.runtime = OnlyBacktestRuntime(
            OnlyRuntimeConfig(
                ENGINE_ID,
                RUNTIME_ID,
                OnlyRuntimeMode.BACKTEST,
                strategy_initial_capital="1000000.00",
                strategy_base_currency=CNY,
            ),
            self.calendar,
            datetime(2026, 1, 5, 1, 30, tzinfo=UTC),
        )
        self.runtime.register_instrument(self.instrument)
        self.cluster = OnlyIntegrationCluster((self.bar_1m, self.bar_3m))
        self.runtime.add_cluster(ENGINE_ID, self.cluster)
        self.event_recorder = OnlyEventRecorder()
        self.report_builder = OnlyReportBuilder()
        self.market_updates: list[OnlyMarketDataUpdateResult] = []
        self.buy_order: OnlyOrderSubmitResult | None = None
        self.sell_order: OnlyOrderSubmitResult | None = None
        self.buy_trade_result: OnlyRuntimeTradeResult | None = None
        self.sell_trade_result: OnlyRuntimeTradeResult | None = None

    @property
    def context(self) -> object:
        if self.cluster.context is None:
            raise RuntimeError("Cluster Context is unavailable")
        return self.cluster.context

    def start(self) -> None:
        self.runtime.start()
        self.event_recorder.capture(self.runtime.event_bus)

    def process_bar(self, day: date, minute: int, close: str) -> OnlyMarketDataUpdateResult:
        result = self.runtime.process_bar(self._bar(day, minute, close))
        self.market_updates.append(result.update)
        self.event_recorder.capture(self.runtime.event_bus)
        return result.update

    def submit_buy(self) -> OnlyOrderSubmitResult:
        self.cluster.pending_order = OnlyOrderRequest(
            OnlyOrderRequestId("integration-buy"),
            INSTRUMENT_ID,
            OnlyOrderSide.BUY,
            OnlyOrderType.LIMIT,
            OnlyQuantity(Decimal("100"), 0),
            price=OnlyPrice(Decimal("10.00"), 2),
            offset=OnlyOffset.OPEN,
        )
        self.process_bar(DAY_ONE, 3, "10.00")
        self.buy_order = self.cluster.submit_results[-1]
        return self.buy_order

    def fill_buy(self) -> OnlyRuntimeTradeResult:
        if self.buy_order is None or self.buy_order.order_id is None:
            raise RuntimeError("buy Order must be submitted first")
        self._accept(self.buy_order, 1)
        self.buy_trade_result = self._fill(self.buy_order, 2, "10.00", "1.00", OnlyOrderSide.BUY)
        return self.buy_trade_result

    def settle_next_day(self) -> tuple[object, ...]:
        results = self.runtime.settle_positions(OnlyTradingDay(DAY_ONE), OnlyTradingDay(DAY_TWO))
        self.event_recorder.capture(self.runtime.event_bus)
        return results

    def submit_and_fill_sell(self) -> OnlyRuntimeTradeResult:
        # Close the current shared 3m aggregation window before advancing the calendar day.
        self.process_bar(DAY_ONE, 4, "10.00")
        self.process_bar(DAY_ONE, 5, "10.00")
        self.cluster.pending_order = OnlyOrderRequest(
            OnlyOrderRequestId("integration-sell"),
            INSTRUMENT_ID,
            OnlyOrderSide.SELL,
            OnlyOrderType.LIMIT,
            OnlyQuantity(Decimal("100"), 0),
            price=OnlyPrice(Decimal("12.00"), 2),
            offset=OnlyOffset.CLOSE,
        )
        self.process_bar(DAY_TWO, 0, "12.00")
        self.sell_order = self.cluster.submit_results[-1]
        if self.sell_order.order_id is None:
            raise RuntimeError("sell Order was not created")
        self._accept(self.sell_order, 3)
        self.sell_trade_result = self._fill(self.sell_order, 4, "12.00", "1.00", OnlyOrderSide.SELL)
        return self.sell_trade_result

    def final_snapshot(self) -> OnlyIntegrationSnapshot:
        self.event_recorder.capture(self.runtime.event_bus)
        return self.report_builder.final_snapshot(self)

    def deterministic_projection(self) -> tuple[object, ...]:
        snapshot = self.final_snapshot()
        return (
            snapshot.runtime_state,
            tuple(item.to_json() for item in snapshot.order_snapshots),
            tuple(item.to_json() for item in snapshot.account_positions),
            tuple(item.to_json() for item in snapshot.cluster_allocations),
            tuple(item.to_json() for item in snapshot.ledger_snapshots),
            snapshot.active_risk_reservations,
            snapshot.position_reservation_state,
            tuple(
                (item.event_type, item.source, item.sequence, item.timestamp_ns, item.cluster_id)
                for item in snapshot.event_trace
            ),
        )

    def assert_core_invariants(self) -> None:
        orders = self.runtime.order_manager.snapshot_all()
        assert orders and all(item.status is OnlyOrderStatus.FILLED for item in orders)
        assert not self.runtime.position_manager.snapshot_all()
        assert not self.runtime.allocation_manager.snapshot_all()
        assert not self.runtime.risk_service.reservations.snapshot_active()
        ledger = self.runtime.strategy_ledger_manager.list_ledgers()[0]
        assert ledger.cash.cash_balance.amount == Decimal("1000198.00")
        assert ledger.pnl.realized_pnl.amount == Decimal("200.00")
        assert ledger.pnl.net_pnl.amount == Decimal("198.00")
        assert ledger.equity.equity_by_cash_view == ledger.equity.equity_by_pnl_view
        assert self.buy_trade_result is not None
        assert self.sell_trade_result is not None
        assert self.buy_trade_result.allocation_status is OnlyPositionMutationStatus.APPLIED
        assert self.sell_trade_result.allocation_status is OnlyPositionMutationStatus.APPLIED
        if self.sell_order is None or self.sell_order.order_id is None:
            raise AssertionError("sell Order is missing")
        reservation = self.runtime.position_reservation_manager.get(self.sell_order.order_id)
        assert reservation is not None and reservation.remaining_quantity.value == 0

    def _accept(self, order: OnlyOrderSubmitResult, sequence: int) -> None:
        if order.order_id is None:
            raise RuntimeError("Order ID is unavailable")
        now = OnlyTimestamp.from_unix_nanos(self.runtime.clock.timestamp_ns())
        self.runtime.process_order_update(
            OnlyGatewayOrderAcceptedUpdate(
                runtime_id=OnlyRuntimeId(RUNTIME_ID),
                order_id=order.order_id,
                ts_event=now,
                ts_init=now,
                external_sequence=sequence,
                external_event_id=f"accepted-{sequence}",
                venue_order_id=OnlyVenueOrderId(f"venue-order-{sequence}"),
            )
        )
        self.event_recorder.capture(self.runtime.event_bus)

    def _fill(
        self,
        order: OnlyOrderSubmitResult,
        sequence: int,
        price: str,
        fee: str,
        side: OnlyOrderSide,
    ) -> OnlyRuntimeTradeResult:
        if order.order_id is None or order.snapshot is None:
            raise RuntimeError("Order Snapshot is unavailable")
        now = OnlyTimestamp.from_unix_nanos(self.runtime.clock.timestamp_ns())
        trade_id = OnlyTradeId(f"trade-{sequence}")
        venue_trade_id = OnlyVenueTradeId(f"venue-trade-{sequence}")
        money = OnlyMoney(Decimal(fee), CNY)
        fill = OnlyOrderFill(
            trade_id,
            order.order_id,
            OnlyPrice(Decimal(price), 2),
            OnlyQuantity(Decimal("100"), 0),
            now,
            now,
            venue_trade_id=venue_trade_id,
            fee=money,
            external_sequence=sequence,
            external_event_id=f"fill-{sequence}",
        )
        update = OnlyGatewayOrderFillUpdate(
            runtime_id=OnlyRuntimeId(RUNTIME_ID),
            order_id=order.order_id,
            ts_event=now,
            ts_init=now,
            external_sequence=sequence,
            external_event_id=f"fill-{sequence}",
            fill=fill,
        )
        trade = OnlyPositionTrade(
            trade_id,
            venue_trade_id,
            order.order_id,
            CLUSTER_ID,
            OnlyRuntimeId(RUNTIME_ID),
            order.snapshot.account_id,
            INSTRUMENT_ID,
            side,
            OnlyDirection.BUY if side is OnlyOrderSide.BUY else OnlyDirection.SELL,
            OnlyOffset.OPEN if side is OnlyOrderSide.BUY else OnlyOffset.CLOSE,
            OnlyPositionSide.LONG,
            OnlyPrice(Decimal(price), 2),
            OnlyQuantity(Decimal("100"), 0),
            money,
            now,
            now,
            sequence,
            execution_id=f"execution-{sequence}",
            settlement_bucket=(
                OnlySettlementBucket.UNSETTLED if side is OnlyOrderSide.BUY else OnlySettlementBucket.SETTLED
            ),
            multiplier=self.instrument.contract_multiplier,
        )
        result = self.runtime.process_trade(update, trade)
        self.event_recorder.capture(self.runtime.event_bus)
        return result

    def _bar(self, day: date, minute: int, close: str) -> OnlyBar:
        start = datetime.combine(day, time(1, 30), tzinfo=UTC) + timedelta(minutes=minute)
        value = Decimal(close)
        return OnlyBar(
            bar_type=self.bar_1m,
            open=OnlyPrice(value, 2),
            high=OnlyPrice(value + Decimal("0.01"), 2),
            low=OnlyPrice(value - Decimal("0.01"), 2),
            close=OnlyPrice(value, 2),
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
            trading_day=day,
            session_type=OnlySessionType.CONTINUOUS,
        )
