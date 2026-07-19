"""One deterministic environment assembling the existing OnlyAlpha components."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from onlyalpha.account.models import OnlyAccountSnapshot
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.models import OnlyBrokerAccountSnapshot, OnlyBrokerOrderSnapshot
from onlyalpha.broker.virtual import OnlyFixedCommissionModel, OnlyVirtualBrokerConfig
from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.data.audit import OnlyMarketDataAuditStore
from onlyalpha.data.gateway import OnlyInMemoryMarketDataGateway
from onlyalpha.data.processor import (
    OnlyMarketDataDeduplicator,
    OnlyMarketDataGapDetector,
    OnlyMarketDataProcessor,
    OnlyMarketDataSequenceTracker,
)
from onlyalpha.data.queue import OnlyMarketDataInboundQueue
from onlyalpha.data.registry import OnlyMarketDataSourceRegistry
from onlyalpha.data.replay import OnlyHistoricalReplayService
from onlyalpha.data.sources import OnlyInMemoryHistoricalDataSource, OnlyInMemoryReferenceDataSource
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyCurrencyType,
    OnlyMarketType,
    OnlyOffset,
    OnlyOrderSide,
    OnlyOrderStatus,
    OnlyOrderType,
    OnlyPriceType,
    OnlyRuntimeMode,
    OnlySessionType,
)
from onlyalpha.domain.execution import OnlyOrderRequest, OnlyOrderSnapshot
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyCalendarId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderRequestId,
    OnlyRawSymbol,
    OnlySymbol,
    OnlyVenueId,
)
from onlyalpha.domain.instrument import OnlyEquity
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.time import OnlyTimeZone, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEvent
from onlyalpha.execution import OnlyExecutionProcessingResult
from onlyalpha.market.models import OnlyMarketProfileId
from onlyalpha.market.profiles import only_builtin_market_profile_registry
from onlyalpha.market.registry import OnlyMarketProfileRequest
from onlyalpha.market.runtime_rules import OnlyMarketRuleCompiler, OnlyMarketRuleEngine, only_instrument_reference
from onlyalpha.market_data.pipeline import OnlyMarketDataUpdateResult
from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot
from onlyalpha.market_data.subscriptions import OnlyBarSubscription
from onlyalpha.order.results import OnlyOrderSubmitResult
from onlyalpha.position.enums import OnlyPositionMutationStatus
from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionSnapshot
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.runtime import OnlyRuntimeAssemblyConfig
from onlyalpha.strategy.base import OnlyStrategy
from onlyalpha.strategy.config import OnlyStrategyConfig
from onlyalpha.strategy.context import OnlyStrategyBarContext
from onlyalpha.strategy.identifiers import OnlyStrategyId
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
    account_snapshots: tuple[OnlyAccountSnapshot, ...]
    broker_account_snapshot: OnlyBrokerAccountSnapshot | None
    broker_order_snapshots: tuple[OnlyBrokerOrderSnapshot, ...]
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
            env.runtime.account_manager.list_accounts(),
            (
                None
                if env.runtime.broker_gateway is None
                else env.runtime.broker_gateway.query_account(OnlyAccountId(ACCOUNT_ID))
            ),
            (
                ()
                if env.runtime.broker_gateway is None
                else env.runtime.broker_gateway.query_orders(OnlyAccountId(ACCOUNT_ID))
            ),
            len(env.runtime.risk_service.reservations.snapshot_active()),
            position_reservation,
            env.event_recorder.events,
        )


class OnlyIntegrationStrategy(OnlyStrategy):
    """Small strategy fixture using only the production Strategy Context."""

    def __init__(self, strategy_id: str) -> None:
        super().__init__(OnlyStrategyConfig(OnlyStrategyId(strategy_id)))
        self.pending_order: OnlyOrderRequest | None = None
        self.submit_results: list[OnlyOrderSubmitResult] = []
        self.snapshots: list[OnlyMarketDataSnapshot] = []

    def on_initialize(self) -> None:
        pass

    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        if not isinstance(context.snapshot, OnlyMarketDataSnapshot):
            raise TypeError("integration Strategy requires MarketDataSnapshot")
        self.snapshots.append(context.snapshot)
        if self.pending_order is not None:
            self.submit_results.append(context.strategy.orders.submit(self.pending_order))  # type: ignore[union-attr]
            self.pending_order = None


class OnlyIntegrationCluster(OnlyCluster):
    """Container fixture; callback behavior is delegated to one Strategy."""

    def __init__(
        self,
        bar_types: tuple[OnlyBarType, ...],
        cluster_id: OnlyClusterId = CLUSTER_ID,
        primary_bar_type: OnlyBarType | None = None,
    ) -> None:
        strategy = OnlyIntegrationStrategy(f"{cluster_id}-strategy")
        super().__init__(
            OnlyClusterConfig(
                str(cluster_id),
                OnlyBarSubscription(bar_types, primary_bar_type=primary_bar_type),
            ),
            strategy,
        )
        self.integration_strategy = strategy

    @property
    def pending_order(self) -> OnlyOrderRequest | None:
        return self.integration_strategy.pending_order

    @pending_order.setter
    def pending_order(self, value: OnlyOrderRequest | None) -> None:
        self.integration_strategy.pending_order = value

    @property
    def submit_results(self) -> list[OnlyOrderSubmitResult]:
        return self.integration_strategy.submit_results

    @property
    def snapshots(self) -> list[OnlyMarketDataSnapshot]:
        return self.integration_strategy.snapshots


class OnlyIntegrationEnvironment:
    """Owns one Runtime and drives the complete deterministic vertical slice."""

    def __init__(
        self,
        *,
        maximum_fill_quantity: OnlyQuantity | None = None,
        virtual_broker: bool = True,
    ) -> None:
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
        market_rules = OnlyMarketRuleEngine(
            registry=only_builtin_market_profile_registry(),
            compiler=OnlyMarketRuleCompiler(),
            request=OnlyMarketProfileRequest(OnlyMarketProfileId.CN_A_SHARE_CASH),
            runtime_mode=OnlyRuntimeMode.BACKTEST,
            references={
                str(self.instrument.instrument_id): only_instrument_reference(
                    self.instrument, profile_id=OnlyMarketProfileId.CN_A_SHARE_CASH.value, board="MAIN"
                )
            },
            advance_trading_day=lambda day, lag: OnlyTradingDay(date.fromordinal(day.value.toordinal() + lag)),
        )
        self.runtime = OnlyBacktestRuntime(
            OnlyRuntimeAssemblyConfig(
                ENGINE_ID,
                RUNTIME_ID,
                OnlyRuntimeMode.BACKTEST,
                strategy_initial_capital="1000000.00",
                strategy_base_currency=CNY,
                market_rule_engine=market_rules,
                virtual_broker_config=(
                    OnlyVirtualBrokerConfig(
                        OnlyBrokerGatewayId("virtual-integration"),
                        OnlyAccountId(ACCOUNT_ID),
                        CNY,
                        OnlyMoney(Decimal("1000000.00"), CNY),
                        maximum_fill_quantity=maximum_fill_quantity,
                        commission_model=OnlyFixedCommissionModel(OnlyMoney(Decimal("1.00"), CNY)),
                    )
                    if virtual_broker
                    else None
                ),
            ),
            self.calendar,
            datetime(2026, 1, 5, 1, 30, tzinfo=UTC),
        )
        self.runtime.register_instrument(self.instrument)
        self.market_data_source_registry: OnlyMarketDataSourceRegistry = self.runtime.market_data_source_registry
        self.historical_data_source: OnlyInMemoryHistoricalDataSource = self.runtime.historical_data_source
        self.reference_data_source: OnlyInMemoryReferenceDataSource = self.runtime.reference_data_source
        self.market_data_gateway: OnlyInMemoryMarketDataGateway = self.runtime.market_data_gateway
        self.market_data_inbound_queue: OnlyMarketDataInboundQueue = self.runtime.market_data_inbound_queue
        self.market_data_processor: OnlyMarketDataProcessor = self.runtime.market_data_processor
        self.market_data_deduplicator: OnlyMarketDataDeduplicator = self.runtime.market_data_deduplicator
        self.market_data_sequence_tracker: OnlyMarketDataSequenceTracker = self.runtime.market_data_sequence_tracker
        self.market_data_gap_detector: OnlyMarketDataGapDetector = self.runtime.market_data_gap_detector
        self.historical_replay_service: OnlyHistoricalReplayService = self.runtime.historical_replay_service
        self.market_data_audit_store: OnlyMarketDataAuditStore = self.runtime.market_data_audit_store
        self.cluster = OnlyIntegrationCluster((self.bar_1m, self.bar_3m))
        self.runtime.add_cluster(ENGINE_ID, self.cluster)
        self.event_recorder = OnlyEventRecorder()
        self.report_builder = OnlyReportBuilder()
        self.market_updates: list[OnlyMarketDataUpdateResult] = []
        self.buy_order: OnlyOrderSubmitResult | None = None
        self.sell_order: OnlyOrderSubmitResult | None = None
        self.buy_trade_result: OnlyExecutionProcessingResult | None = None
        self.sell_trade_result: OnlyExecutionProcessingResult | None = None
        self.product_backtest_fingerprint: str | None = None

    @property
    def context(self) -> object:
        if self.cluster.context is None:
            raise RuntimeError("Cluster Context is unavailable")
        return self.cluster.context

    def start(self) -> None:
        self.runtime.start()
        self.event_recorder.capture(self.runtime.event_bus)

    def process_bar(self, day: date, minute: int, close: str) -> OnlyMarketDataUpdateResult:
        result = self.runtime.process_bar(self.make_bar(day, minute, close))
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

    def fill_buy(self) -> OnlyExecutionProcessingResult:
        if self.buy_order is None or self.buy_order.order_id is None:
            raise RuntimeError("buy Order must be submitted first")
        before = len(self.runtime.broker_results)
        self.process_bar(DAY_ONE, 4, "10.00")
        self.buy_trade_result = next(
            item
            for item in self.runtime.broker_results[before:]
            if isinstance(item, OnlyExecutionProcessingResult) and item.update_type == "OnlyBrokerTradeUpdate"
        )
        return self.buy_trade_result

    def settle_next_day(self) -> tuple[object, ...]:
        # Close the final day-one aggregation window before changing TradingDay.
        self.process_bar(DAY_ONE, 5, "10.00")
        results = self.runtime.settle_positions(OnlyTradingDay(DAY_ONE), OnlyTradingDay(DAY_TWO))
        # The day-two Bar advances the independent Broker settlement and sends its snapshots inbound.
        self.process_bar(DAY_TWO, 0, "10.00")
        self.event_recorder.capture(self.runtime.event_bus)
        return results

    def submit_and_fill_sell(self) -> OnlyExecutionProcessingResult:
        self.cluster.pending_order = OnlyOrderRequest(
            OnlyOrderRequestId("integration-sell"),
            INSTRUMENT_ID,
            OnlyOrderSide.SELL,
            OnlyOrderType.LIMIT,
            OnlyQuantity(Decimal("100"), 0),
            price=OnlyPrice(Decimal("12.00"), 2),
            offset=OnlyOffset.CLOSE,
        )
        self.process_bar(DAY_TWO, 1, "12.00")
        self.sell_order = self.cluster.submit_results[-1]
        if self.sell_order.order_id is None:
            raise RuntimeError("sell Order was not created")
        before = len(self.runtime.broker_results)
        self.process_bar(DAY_TWO, 2, "12.00")
        self.sell_trade_result = next(
            item
            for item in self.runtime.broker_results[before:]
            if isinstance(item, OnlyExecutionProcessingResult) and item.update_type == "OnlyBrokerTradeUpdate"
        )
        return self.sell_trade_result

    def final_snapshot(self) -> OnlyIntegrationSnapshot:
        self.event_recorder.capture(self.runtime.event_bus)
        return self.report_builder.final_snapshot(self)

    def deterministic_projection(self) -> tuple[object, ...]:
        snapshot = self.final_snapshot()
        execution_results = tuple(
            (
                str(item.update_id),
                item.update_type,
                item.status.value,
                item.sequence,
                tuple((step.step.value, step.status.value, step.summary) for step in item.mutation_bundle.steps),
                None if item.order_snapshot is None else item.order_snapshot.to_json(),
                None if item.position_snapshot is None else item.position_snapshot.to_json(),
                None if item.allocation_snapshot is None else item.allocation_snapshot.to_json(),
                None if item.ledger_snapshot is None else item.ledger_snapshot.to_json(),
                None if item.account_snapshot is None else item.account_snapshot.to_json(),
                None if item.risk_snapshot is None else item.risk_snapshot.to_json(),
                item.audit_record.to_json(),
                (None if item.reconciliation_request is None else item.reconciliation_request.to_json()),
                tuple(str(event.event_type) for event in item.generated_events),
            )
            for item in self.runtime.broker_results
            if isinstance(item, OnlyExecutionProcessingResult)
        )
        return (
            snapshot.runtime_state,
            tuple(item.to_json() for item in snapshot.order_snapshots),
            tuple(item.to_json() for item in snapshot.account_positions),
            tuple(item.to_json() for item in snapshot.cluster_allocations),
            tuple(item.to_json() for item in snapshot.ledger_snapshots),
            tuple(item.to_json() for item in snapshot.account_snapshots),
            None if snapshot.broker_account_snapshot is None else snapshot.broker_account_snapshot.to_json(),
            tuple(item.to_json() for item in snapshot.broker_order_snapshots),
            snapshot.active_risk_reservations,
            snapshot.position_reservation_state,
            tuple(item.to_json() for item in self.runtime.risk_service.reservations.snapshot_all()),
            execution_results,
            tuple(item.to_json() for item in self.runtime.execution_reconciliation_queue.requests()),
            tuple(
                (
                    item.audit_id,
                    str(item.source_id),
                    str(item.update_id),
                    item.status.value,
                    item.source_sequence,
                    item.processing_sequence,
                    str(item.data_version),
                    tuple(sorted(flag.value for flag in item.quality_flags)),
                    item.ts_event.unix_nanos,
                )
                for item in self.market_data_audit_store.records()
            ),
            tuple(
                (
                    item.index,
                    str(item.update.update_id),
                    item.clock_time_ns,
                    item.result.status.value,
                )
                for item in self.historical_replay_service.events
            ),
            tuple(
                (item.event_type, item.source, item.sequence, item.timestamp_ns, item.cluster_id)
                for item in snapshot.event_trace
            ),
            self.product_backtest_fingerprint,
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
        account = self.runtime.account_manager.list_accounts()[0]
        assert account.cash.cash_balance.amount == Decimal("1000198.00")
        assert account.equity.amount == Decimal("1000198.00")
        assert self.runtime.broker_gateway is not None
        broker_account = self.runtime.broker_gateway.query_account(OnlyAccountId(ACCOUNT_ID))
        assert broker_account.cash_balance == account.cash.cash_balance
        assert self.buy_trade_result is not None
        assert self.sell_trade_result is not None
        assert self.buy_trade_result.allocation_status is OnlyPositionMutationStatus.APPLIED
        assert self.sell_trade_result.allocation_status is OnlyPositionMutationStatus.APPLIED
        if self.sell_order is None or self.sell_order.order_id is None:
            raise AssertionError("sell Order is missing")
        reservation = self.runtime.position_reservation_manager.get(self.sell_order.order_id)
        assert reservation is not None and reservation.remaining_quantity.value == 0

    def make_bar(self, day: date, minute: int, close: str) -> OnlyBar:
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
