import inspect

from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyRuntimeId,
    OnlyVenueOrderId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.order.execution.gateway import OnlyTradeGateway
from onlyalpha.order.execution.models import OnlyGatewayOrderAcceptedUpdate, OnlyGatewayOrderFillUpdate
from onlyalpha.order.execution.placeholder import OnlyPlaceholderExecutionService, OnlyPlaceholderTradeGateway
from onlyalpha.order.execution.processor import OnlyOrderUpdateProcessor
from onlyalpha.order.publisher import OnlyInMemoryOrderEventPublisher
from onlyalpha.order.service import OnlyOrderService


def test_gateway_is_abstract_and_placeholders_generate_no_venue_facts() -> None:
    assert inspect.isabstract(OnlyTradeGateway)
    gateway = OnlyPlaceholderTradeGateway()
    assert gateway.query_orders.__call__
    assert gateway.query_trades.__call__


def test_submit_publishes_created_then_submitted_and_never_accepts(order_manager, order_request) -> None:
    publisher = OnlyInMemoryOrderEventPublisher()
    execution = OnlyPlaceholderExecutionService()
    service = OnlyOrderService(
        order_manager,
        execution,
        publisher,
        lambda: OnlyTimestamp.from_unix_nanos(1),
    )
    result = service.submit(order_request, OnlyClusterId("cluster-a"), OnlyAccountId("account"))
    assert result.snapshot.status is OnlyOrderStatus.SUBMITTED
    assert result.venue_accepted is None
    assert result.snapshot.venue_order_id is None
    assert [str(event.event_type) for event in publisher.events] == ["ORDER_CREATED", "ORDER_SUBMITTED"]
    assert len(execution.submissions) == 1


def test_standardized_update_mutates_before_publishing(order_manager, order_request) -> None:
    publisher = OnlyInMemoryOrderEventPublisher()
    service = OnlyOrderService(
        order_manager,
        OnlyPlaceholderExecutionService(),
        publisher,
        lambda: OnlyTimestamp.from_unix_nanos(1),
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
