from datetime import UTC, datetime
from typing import cast

import pytest

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEventScope
from onlyalpha.execution import (
    OnlyExecutionOutboxPublisher,
)
from onlyalpha.runtime.events import OnlyRuntimeEventRouter, OnlyRuntimeRecoveryEventGate
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore, OnlyRuntimePersistenceStorePort
from tests.execution.factories.transaction_factory import only_test_generic_t0_cash_buy_open_transaction
from tests.execution.support.execution_fault_injection import (
    OnlyFailOnceRuntimePersistenceStore,
    OnlyTestRuntimePersistenceFault,
)
from tests.execution.support.real_execution_recovery_harness import OnlyRealExecutionRecoveryHarness

_NOW = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, tzinfo=UTC))


def _open_router(bus: OnlyEventBus, scope: OnlyEventScope) -> OnlyRuntimeEventRouter:
    router = OnlyRuntimeEventRouter(bus, OnlyRuntimeRecoveryEventGate(100), scope)
    router.complete_fresh_bootstrap()
    router.open()
    return router


def test_outbox_is_inaccessible_before_projection_ready() -> None:
    harness = OnlyRealExecutionRecoveryHarness.create()
    store = harness.transaction_store
    records = store.outbox_records(harness.bundle.transaction.runtime_id)

    assert records and store.pending(harness.bundle.transaction.runtime_id, limit=100) == ()
    with pytest.raises(ValueError, match="not projection-ready"):
        store.begin_attempt(records[0].key, _NOW)


def test_event_bus_failure_keeps_ready_transaction_and_manager_authority_for_retry() -> None:
    harness = OnlyRealExecutionRecoveryHarness.create()
    assert harness.recover().succeeded
    manager_before = harness.manager_digest()
    runtime_id = harness.bundle.transaction.runtime_id
    events = harness.bundle.transaction.outbox_events
    scope = OnlyEventScope(OnlyEngineId("integration-engine"), runtime_id)
    bus = OnlyEventBus(capacity=1, scope=scope)
    router = _open_router(bus, scope)
    bus.publish(events[0])
    publisher = OnlyExecutionOutboxPublisher(harness.transaction_store, router, lambda: _NOW)

    failed = publisher.publish_pending(runtime_id)
    records = harness.transaction_store.outbox_records(runtime_id)

    assert failed.failed == 1 and failed.remaining == len(events)
    assert harness.transaction_store.ready_count(runtime_id) == 1
    assert records[0].attempt_count == 1
    assert records[0].last_error is not None
    assert records[0].event.event_id == events[0].event_id
    assert harness.manager_digest() == manager_before


def test_mark_published_failure_retries_same_event_without_reprojecting() -> None:
    store = OnlyInMemoryRuntimePersistenceStore()
    faulting = OnlyFailOnceRuntimePersistenceStore(store, OnlyTestRuntimePersistenceFault.OUTBOX_MARK_PUBLISHED)
    harness = OnlyRealExecutionRecoveryHarness.create(store=faulting)
    assert harness.recover().succeeded
    manager_before = harness.manager_digest()
    runtime_id = harness.bundle.transaction.runtime_id
    events = harness.bundle.transaction.outbox_events
    scope = OnlyEventScope(OnlyEngineId("integration-engine"), runtime_id)
    bus = OnlyEventBus(capacity=100, scope=scope)
    publisher = OnlyExecutionOutboxPublisher(faulting, _open_router(bus, scope), lambda: _NOW)

    failed = publisher.publish_pending(runtime_id)
    retried = publisher.publish_pending(runtime_id)

    assert failed.failed == 1
    assert retried.failed == 0 and retried.remaining == 0
    assert bus.drain() == len(events) + 1
    assert tuple(item.event.event_id for item in bus.dispatch_results) == (
        events[0].event_id,
        *(event.event_id for event in events),
    )
    assert harness.manager_digest() == manager_before
    assert len(harness.applied_ledger.records()) == 13


def test_recovered_outbox_events_are_dispatched_before_runtime_started() -> None:
    from tests.runtime_support.common import only_demo_runtime

    runtime = only_demo_runtime("runtime")
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    store = cast(OnlyRuntimePersistenceStorePort, runtime._services.execution_transaction_query)
    committed_at = OnlyTimestamp.from_datetime(runtime.clock.now_utc())
    transaction = store.commit(prepared, committed_at=committed_at).transaction
    store.mark_projection_ready(
        prepared.runtime_id,
        transaction.execution_sequence,
        projected_at=committed_at,
    )

    runtime.start()

    dispatched = tuple(item.event for item in runtime.event_bus.dispatch_results)
    runtime_started = next(
        index for index, event in enumerate(dispatched) if event.event_type.value == "RUNTIME_STARTED"
    )
    recovered_indexes = tuple(
        next(index for index, dispatched_event in enumerate(dispatched) if dispatched_event.event_id == event.event_id)
        for event in prepared.outbox_events
    )
    assert recovered_indexes
    assert max(recovered_indexes) < runtime_started
