import inspect

from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyRuntimeId,
    OnlyVenueOrderId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.order.execution.gateway import OnlyTradeGateway
from onlyalpha.order.execution.models import (
    OnlyExecutionCancelResult,
    OnlyExecutionSubmissionOutcome,
    OnlyGatewayOrderAcceptedUpdate,
    OnlyGatewayOrderFillUpdate,
)
from onlyalpha.order.execution.placeholder import OnlyPlaceholderExecutionService, OnlyPlaceholderTradeGateway
from onlyalpha.order.execution.processor import OnlyOrderUpdateProcessor
from onlyalpha.order.id_generator import OnlySequenceClientOrderIdGenerator, OnlySequenceOrderIdGenerator
from onlyalpha.order.manager import OnlyOrderManager
from onlyalpha.order.publisher import OnlyInMemoryOrderEventPublisher
from onlyalpha.order.service import OnlyOrderService
from tests.order.fee_contract import only_test_zero_fee_contract


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
