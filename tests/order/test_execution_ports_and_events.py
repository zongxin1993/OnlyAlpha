import inspect
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from onlyalpha.data.enums import OnlyDataSequenceSemantics, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.identity import only_trade_update_id
from onlyalpha.data.models import OnlyMarketDataInboundUpdate, OnlyMarketDataQuality, OnlyTradeTickUpdate
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderStatus, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyOrderRequestId,
    OnlyRuntimeId,
    OnlyTradeId,
    OnlyVenueOrderId,
)
from onlyalpha.domain.market import OnlyTradeTick
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.execution.reference import (
    OnlyExecutionReferenceFallback,
    OnlyExecutionReferenceKind,
    OnlyExecutionReferencePlanningService,
    OnlyExecutionReferenceProfile,
)
from onlyalpha.market_data.realtime_state import OnlyRealtimeMarketStateStore
from onlyalpha.order.execution.gateway import OnlyTradeGateway
from onlyalpha.order.execution.models import (
    OnlyExecutionCancelResult,
    OnlyExecutionSubmissionOutcome,
    OnlyExecutionSubmitResult,
    OnlyGatewayOrderAcceptedUpdate,
    OnlyGatewayOrderFillUpdate,
)
from onlyalpha.order.execution.placeholder import OnlyPlaceholderExecutionService, OnlyPlaceholderTradeGateway
from onlyalpha.order.execution.processor import OnlyOrderUpdateProcessor
from onlyalpha.order.id_generator import OnlySequenceClientOrderIdGenerator, OnlySequenceOrderIdGenerator
from onlyalpha.order.intent import OnlyOrderIntentDurabilityResult, OnlyRuntimeIntentReference
from onlyalpha.order.manager import OnlyOrderManager
from onlyalpha.order.publisher import OnlyInMemoryOrderEventPublisher
from onlyalpha.order.service import OnlyOrderService
from tests.order.fee_contract import only_test_zero_fee_contract


class _PlanningReservationSpy:
    def __init__(self) -> None:
        self.prices: list[OnlyPrice | None] = []

    def reserve(self, order, timestamp, *, planning_price=None) -> None:
        del order, timestamp
        self.prices.append(planning_price)

    def sent(self, order_id, timestamp) -> None:
        del order_id, timestamp

    def acknowledged(self, order_id, timestamp) -> None:
        del order_id, timestamp

    def consume(self, fill, timestamp) -> None:
        del fill, timestamp

    def release(self, order_id, timestamp) -> None:
        del order_id, timestamp


def _reference_planner(runtime_id, instrument_id, *, advance_after_capture=False):
    now = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, tzinfo=UTC))
    source = OnlyMarketDataSourceId("planning-source")
    version = OnlyDataVersion("planning-v1")
    trade = OnlyTradeTick(
        instrument_id,
        now.to_datetime(),
        now.to_datetime(),
        1,
        str(source),
        OnlyPrice(Decimal("100.00"), 2),
        OnlyQuantity(Decimal("100"), 0),
        OnlyOrderSide.BUY,
        OnlyTradeId("planning-trade-1"),
    )
    update = OnlyMarketDataInboundUpdate(
        only_trade_update_id(source, instrument_id, trade.trade_id, version),
        runtime_id,
        source,
        OnlyDataSequence(1),
        version,
        instrument_id,
        OnlyMarketDataType.TRADE,
        OnlyTradeTickUpdate(trade),
        now,
        now,
        sequence_semantics=OnlyDataSequenceSemantics.CONTIGUOUS,
    )
    state = OnlyRealtimeMarketStateStore(runtime_id)
    state.apply_trade(update, OnlyMarketDataQuality(), 1)
    profile = OnlyExecutionReferenceProfile(
        "planning-v1",
        1,
        OnlyExecutionReferenceKind.LAST_TRADE,
        OnlyExecutionReferenceFallback.NONE,
        10_000_000_000,
        str(source),
    )
    if not advance_after_capture:
        return now, OnlyExecutionReferencePlanningService(state, profile)

    class CaptureThenAdvance:
        def capture(self, captured_at):
            snapshot = state.capture(captured_at)
            later_trade = replace(
                trade,
                sequence=2,
                price=OnlyPrice(Decimal("101.00"), 2),
                trade_id=OnlyTradeId("planning-trade-2"),
            )
            state.apply_trade(
                replace(
                    update,
                    update_id=only_trade_update_id(source, instrument_id, later_trade.trade_id, version),
                    source_sequence=OnlyDataSequence(2),
                    payload=OnlyTradeTickUpdate(later_trade),
                ),
                OnlyMarketDataQuality(),
                2,
            )
            return snapshot

    return now, OnlyExecutionReferencePlanningService(CaptureThenAdvance(), profile)  # type: ignore[arg-type]


def test_gateway_is_abstract_and_placeholders_generate_no_venue_facts() -> None:
    assert inspect.isabstract(OnlyTradeGateway)
    gateway = OnlyPlaceholderTradeGateway()
    assert gateway.query_orders.__call__
    assert gateway.query_trades.__call__


def test_submit_publishes_created_then_submitted_and_never_accepts(order_manager, order_request, risk_service) -> None:
    publisher = OnlyInMemoryOrderEventPublisher()
    execution = OnlyPlaceholderExecutionService()
    service = OnlyOrderService(
        order_manager,
        execution,
        publisher,
        lambda: OnlyTimestamp.from_unix_nanos(1),
        risk_service,
        risk_service.make_evaluation_context,
        fee_contract_factory=only_test_zero_fee_contract,
    )
    result = service.submit(order_request, OnlyClusterId("cluster-a"), OnlyAccountId("account"))
    assert result.snapshot.status is OnlyOrderStatus.SUBMITTED
    assert result.venue_accepted is None
    assert result.snapshot.venue_order_id is None
    assert [str(event.event_type) for event in publisher.events] == ["ORDER_CREATED", "ORDER_SUBMITTED"]
    assert len(execution.submissions) == 1


def test_market_planning_price_is_propagated_to_fee_cash_margin_and_risk(
    order_manager,
    order_request,
    risk_service,
) -> None:
    now, planner = _reference_planner(
        order_manager.runtime_id,
        order_request.instrument_id,
        advance_after_capture=True,
    )
    cash = _PlanningReservationSpy()
    margin = _PlanningReservationSpy()
    fee_prices: list[OnlyPrice | None] = []

    def planning_fee(order, timestamp, planning_price):
        fee_prices.append(planning_price)
        return only_test_zero_fee_contract(order, timestamp)

    service = OnlyOrderService(
        order_manager,
        OnlyPlaceholderExecutionService(),
        OnlyInMemoryOrderEventPublisher(),
        lambda: now,
        risk_service,
        risk_service.make_evaluation_context,
        cash_reservations=cash,
        margin_reservations=margin,
        execution_reference_planning=planner,
        planning_fee_contract_factory=planning_fee,
    )
    request = OnlyOrderRequest(
        OnlyOrderRequestId("market-planning-propagation"),
        order_request.instrument_id,
        OnlyOrderSide.BUY,
        OnlyOrderType.MARKET,
        OnlyQuantity(Decimal("100"), 0),
        offset=OnlyOffset.OPEN,
    )

    result = service.submit(request, OnlyClusterId("cluster-a"), OnlyAccountId("account"))

    planning_price = OnlyPrice(Decimal("100.00"), 2)
    assert result.created
    assert fee_prices == [planning_price]
    assert cash.prices == [planning_price]
    assert margin.prices == [planning_price]
    risk_reservation = risk_service.reservations.get_for_order(result.order_id)
    assert risk_reservation is not None and risk_reservation.reserved_notional is not None
    assert risk_reservation.reserved_notional.amount == Decimal("10000.00")


def test_standardized_update_mutates_before_publishing(order_manager, order_request, risk_service) -> None:
    publisher = OnlyInMemoryOrderEventPublisher()
    service = OnlyOrderService(
        order_manager,
        OnlyPlaceholderExecutionService(),
        publisher,
        lambda: OnlyTimestamp.from_unix_nanos(1),
        risk_service,
        risk_service.make_evaluation_context,
        fee_contract_factory=only_test_zero_fee_contract,
    )
    submitted = service.submit(order_request, OnlyClusterId("cluster-a"), OnlyAccountId("account"))
    processor = OnlyOrderUpdateProcessor(OnlyRuntimeId("runtime"), order_manager, publisher)
    result = processor.process(
        OnlyGatewayOrderAcceptedUpdate(
            runtime_id=OnlyRuntimeId("runtime"),
            order_id=submitted.order_id,
            venue_order_id=OnlyVenueOrderId("venue-1"),
            ts_event=OnlyTimestamp.from_unix_nanos(2),
            ts_init=OnlyTimestamp.from_unix_nanos(3),
            external_sequence=1,
            external_event_id="accepted-1",
        )
    )
    assert result.snapshot.status is OnlyOrderStatus.ACCEPTED
    assert result.events[0].payload["snapshot"]["status"] == "ACCEPTED"
    before = len(publisher.events)
    duplicate = processor.process(
        OnlyGatewayOrderAcceptedUpdate(
            runtime_id=OnlyRuntimeId("runtime"),
            order_id=submitted.order_id,
            venue_order_id=OnlyVenueOrderId("venue-1"),
            ts_event=OnlyTimestamp.from_unix_nanos(2),
            ts_init=OnlyTimestamp.from_unix_nanos(3),
            external_sequence=1,
            external_event_id="accepted-1",
        )
    )
    assert not duplicate.changed and len(publisher.events) == before


def test_standardized_fill_update_validates_nested_order_id(created_order) -> None:
    from .conftest import only_fill

    fill = only_fill(created_order.order_id, "trade-1", "1", "10.00", 2)
    update = OnlyGatewayOrderFillUpdate(
        runtime_id=created_order.snapshot.runtime_id,
        order_id=created_order.order_id,
        ts_event=fill.ts_event,
        ts_init=fill.ts_init,
        fill=fill,
    )
    assert update.fill == fill


class _ResponseLostExecution:
    def __init__(self) -> None:
        self.submission_count = 0

    def submit_order(self, _order):
        self.submission_count += 1
        raise TimeoutError("response lost after possible dispatch")

    def cancel_order(self, _request) -> OnlyExecutionCancelResult:
        return OnlyExecutionCancelResult(True, "recorded")


class _DurableBoundaryExecution:
    requires_durable_intent = True

    def __init__(self) -> None:
        self.submission_count = 0
        self.reference = None

    def record_runtime_intent(self, _order_id, reference) -> None:
        self.reference = reference

    def submit_order(self, _order) -> OnlyExecutionSubmitResult:
        self.submission_count += 1
        return OnlyExecutionSubmitResult(True, "known", OnlyExecutionSubmissionOutcome.KNOWN_RESULT)

    def cancel_order(self, _request) -> OnlyExecutionCancelResult:
        return OnlyExecutionCancelResult(True, "known")


class _IntentDurability:
    def __init__(self, ready: bool) -> None:
        self.ready = ready

    def begin(self, request, cluster_id, account_id, prepared_at):
        return request, cluster_id, account_id, prepared_at

    def commit(self, _token, _order) -> OnlyOrderIntentDurabilityResult:
        return OnlyOrderIntentDurabilityResult(
            self.ready,
            OnlyRuntimeIntentReference("OINT-test", "0" * 64) if self.ready else None,
            None if self.ready else "injected durable commit/projection failure",
        )


def test_real_execution_never_dispatches_until_runtime_intent_is_projection_ready(
    order_manager, order_request, risk_service
) -> None:
    blocked_execution = _DurableBoundaryExecution()
    blocked = OnlyOrderService(
        order_manager,
        blocked_execution,
        OnlyInMemoryOrderEventPublisher(),
        lambda: OnlyTimestamp.from_unix_nanos(1),
        risk_service,
        risk_service.make_evaluation_context,
        fee_contract_factory=only_test_zero_fee_contract,
        intent_durability=_IntentDurability(False),
        intent_reference_sink=blocked_execution,
    ).submit(order_request, OnlyClusterId("cluster-a"), OnlyAccountId("account"))
    assert blocked.submission_outcome is OnlyExecutionSubmissionOutcome.NOT_DISPATCHED
    assert blocked_execution.submission_count == 0

    second_manager = OnlyOrderManager(
        OnlyEngineId("engine"),
        OnlyRuntimeId("runtime"),
        OnlySequenceOrderIdGenerator(OnlyRuntimeId("runtime")),
        OnlySequenceClientOrderIdGenerator(OnlyRuntimeId("runtime")),
    )
    ready_execution = _DurableBoundaryExecution()
    ready = OnlyOrderService(
        second_manager,
        ready_execution,
        OnlyInMemoryOrderEventPublisher(),
        lambda: OnlyTimestamp.from_unix_nanos(1),
        risk_service,
        risk_service.make_evaluation_context,
        fee_contract_factory=only_test_zero_fee_contract,
        intent_durability=_IntentDurability(True),
        intent_reference_sink=ready_execution,
    ).submit(order_request, OnlyClusterId("cluster-a"), OnlyAccountId("account"))
    assert ready.submission_outcome is OnlyExecutionSubmissionOutcome.KNOWN_RESULT
    assert ready_execution.submission_count == 1
    assert ready_execution.reference == OnlyRuntimeIntentReference("OINT-test", "0" * 64)


def test_unknown_submit_is_orthogonal_durable_and_cannot_blindly_resubmit(
    order_manager, order_request, risk_service
) -> None:
    execution = _ResponseLostExecution()
    publisher = OnlyInMemoryOrderEventPublisher()
    service = OnlyOrderService(
        order_manager,
        execution,
        publisher,
        lambda: OnlyTimestamp.from_unix_nanos(1),
        risk_service,
        risk_service.make_evaluation_context,
        fee_contract_factory=only_test_zero_fee_contract,
    )
    first = service.submit(order_request, OnlyClusterId("cluster-a"), OnlyAccountId("account"))
    second = service.submit(order_request, OnlyClusterId("cluster-a"), OnlyAccountId("account"))
    assert first.snapshot.status is OnlyOrderStatus.SUBMITTED
    assert first.submission_outcome is OnlyExecutionSubmissionOutcome.UNKNOWN
    assert second.order_id == first.order_id and second.client_order_id == first.client_order_id
    assert execution.submission_count == 1
    assert order_manager.submission_outcome(first.order_id) is OnlyExecutionSubmissionOutcome.UNKNOWN

    runtime_id = OnlyRuntimeId("runtime")
    restored = OnlyOrderManager(
        OnlyEngineId("engine"),
        runtime_id,
        OnlySequenceOrderIdGenerator(runtime_id),
        OnlySequenceClientOrderIdGenerator(runtime_id),
    )
    restored.restore_checkpoint(order_manager.capture_checkpoint())
    assert restored.require_snapshot(first.order_id).client_order_id == first.client_order_id
    assert restored.submission_outcome(first.order_id) is OnlyExecutionSubmissionOutcome.UNKNOWN

    restored.begin_submission_reconciliation(first.order_id)
    OnlyOrderUpdateProcessor(runtime_id, restored, publisher).process(
        OnlyGatewayOrderAcceptedUpdate(
            runtime_id=runtime_id,
            order_id=first.order_id,
            venue_order_id=OnlyVenueOrderId("venue-unknown-resolved"),
            ts_event=OnlyTimestamp.from_unix_nanos(2),
            ts_init=OnlyTimestamp.from_unix_nanos(2),
            external_sequence=1,
            external_event_id="accepted-after-query",
        )
    )
    assert restored.submission_outcome(first.order_id) is OnlyExecutionSubmissionOutcome.RESOLVED
