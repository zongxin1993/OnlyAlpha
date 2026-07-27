from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from onlyalpha.domain.identifiers import OnlyEngineId, OnlyRuntimeId
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEvent, OnlyEventScope
from onlyalpha.execution import (
    OnlyEventBusDirectExecutionPublisher,
    OnlyExecutionEventBatch,
    OnlyExecutionEventBuffer,
    OnlyExecutionEventDeliveryCoordinator,
    OnlyExecutionEventDeliveryIntent,
    OnlyExecutionEventDeliveryMode,
)


def _event(sequence: int = 1) -> OnlyEvent:
    return OnlyEvent(
        "EXECUTION_TEST",
        datetime(2026, 1, 1, tzinfo=UTC),
        OnlyEngineId("engine"),
        OnlyRuntimeId("runtime"),
        "test",
        sequence,
        payload={"sequence": sequence},
    )


def test_event_buffer_requires_explicit_scope_and_seals_immutable_batch() -> None:
    buffer = OnlyExecutionEventBuffer()
    with pytest.raises(RuntimeError, match="not active"):
        buffer.add(_event())
    with pytest.raises(RuntimeError, match="not active"):
        buffer.extend((_event(),))

    buffer.begin()
    buffer.add(_event())
    buffer.extend((_event(2),))
    with pytest.raises(RuntimeError, match="nested"):
        buffer.begin()
    batch = buffer.seal()

    assert tuple(int(event.sequence) for event in batch.events) == (1, 2)
    with pytest.raises(FrozenInstanceError):
        batch.events = ()  # type: ignore[misc]
    with pytest.raises(RuntimeError, match="not active"):
        buffer.seal()


def test_event_buffer_abort_returns_discarded_events_without_delivery() -> None:
    buffer = OnlyExecutionEventBuffer()
    buffer.begin()
    event = _event()
    buffer.add(event)
    assert buffer.abort() == OnlyExecutionEventBatch((event,))
    with pytest.raises(RuntimeError, match="not active"):
        buffer.abort()


@pytest.mark.parametrize(
    ("mode", "batch", "sequence"),
    [
        (OnlyExecutionEventDeliveryMode.NONE, OnlyExecutionEventBatch(()), None),
        (OnlyExecutionEventDeliveryMode.NONE, None, 1),
        (OnlyExecutionEventDeliveryMode.DIRECT, None, None),
        (OnlyExecutionEventDeliveryMode.DIRECT, OnlyExecutionEventBatch(()), 1),
        (OnlyExecutionEventDeliveryMode.DURABLE_OUTBOX, None, None),
        (OnlyExecutionEventDeliveryMode.DURABLE_OUTBOX, OnlyExecutionEventBatch(()), 1),
    ],
)
def test_delivery_intent_rejects_invalid_field_combinations(
    mode: OnlyExecutionEventDeliveryMode,
    batch: OnlyExecutionEventBatch | None,
    sequence: int | None,
) -> None:
    with pytest.raises(ValueError, match="invalid"):
        OnlyExecutionEventDeliveryIntent(mode, batch, sequence)


def test_delivery_intent_accepts_the_three_valid_shapes() -> None:
    batch = OnlyExecutionEventBatch((_event(),))
    assert OnlyExecutionEventDeliveryIntent(OnlyExecutionEventDeliveryMode.NONE).mode.value == "NONE"
    assert OnlyExecutionEventDeliveryIntent(OnlyExecutionEventDeliveryMode.DIRECT, batch).direct_batch is batch
    assert (
        OnlyExecutionEventDeliveryIntent(
            OnlyExecutionEventDeliveryMode.DURABLE_OUTBOX, committed_execution_sequence=7
        ).committed_execution_sequence
        == 7
    )


def test_direct_publisher_reports_success_empty_and_event_bus_failure() -> None:
    bus = OnlyEventBus(scope=OnlyEventScope(OnlyEngineId("engine"), OnlyRuntimeId("runtime")), capacity=1)
    publisher = OnlyEventBusDirectExecutionPublisher(bus)
    empty = publisher.publish(OnlyExecutionEventBatch(()))
    assert (empty.attempted, empty.published, empty.failed, empty.error) == (0, 0, 0, None)

    failed = publisher.publish(OnlyExecutionEventBatch((_event(), _event(2))))
    assert (failed.attempted, failed.published, failed.failed) == (2, 1, 1)
    assert failed.error is not None


class _UnusedOutboxPublisher:
    def publish_pending(self, runtime_id: OnlyRuntimeId, *, limit: int = 100) -> object:
        del runtime_id, limit
        raise AssertionError("NONE and DIRECT must not call the Outbox publisher")


def test_coordinator_routes_none_and_direct_without_changing_business_result() -> None:
    bus = OnlyEventBus(scope=OnlyEventScope(OnlyEngineId("engine"), OnlyRuntimeId("runtime")))
    coordinator = OnlyExecutionEventDeliveryCoordinator(
        OnlyEventBusDirectExecutionPublisher(bus),
        _UnusedOutboxPublisher(),  # type: ignore[arg-type]
    )
    none = coordinator.deliver(
        OnlyRuntimeId("runtime"), OnlyExecutionEventDeliveryIntent(OnlyExecutionEventDeliveryMode.NONE)
    )
    direct = coordinator.deliver(
        OnlyRuntimeId("runtime"),
        OnlyExecutionEventDeliveryIntent(
            OnlyExecutionEventDeliveryMode.DIRECT,
            direct_batch=OnlyExecutionEventBatch((_event(),)),
        ),
    )
    assert (none.attempted, none.failed) == (0, 0)
    assert (direct.attempted, direct.published, direct.failed) == (1, 1, 0)
