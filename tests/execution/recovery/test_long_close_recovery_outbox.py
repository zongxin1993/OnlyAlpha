from datetime import UTC, datetime

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEventScope
from onlyalpha.execution import OnlyExecutionOutboxPublisher
from onlyalpha.runtime.events import OnlyRuntimeEventRouter, OnlyRuntimeRecoveryEventGate
from tests.execution.support.real_execution_recovery_harness import OnlyRealExecutionRecoveryHarness


def test_long_close_recovered_outbox_publishes_same_stable_events_once() -> None:
    harness = OnlyRealExecutionRecoveryHarness.create(long_close=True)
    assert harness.recover().succeeded
    transaction = harness.bundle.transaction
    scope = OnlyEventScope(OnlyEngineId("integration-engine"), transaction.runtime_id)
    bus = OnlyEventBus(capacity=100, scope=scope)
    router = OnlyRuntimeEventRouter(bus, OnlyRuntimeRecoveryEventGate(100), scope)
    router.complete_fresh_bootstrap()
    router.open()
    now = OnlyTimestamp.from_datetime(datetime(2026, 1, 7, tzinfo=UTC))
    publisher = OnlyExecutionOutboxPublisher(harness.transaction_store, router, lambda: now)

    first = publisher.publish_pending(transaction.runtime_id)
    second = publisher.publish_pending(transaction.runtime_id)
    bus.drain()

    assert first.published == len(transaction.outbox_events)
    assert first.remaining == 0
    assert second.published == 0 and second.remaining == 0
    assert tuple(item.event.event_id for item in bus.dispatch_results) == tuple(
        item.event_id for item in transaction.outbox_events
    )
