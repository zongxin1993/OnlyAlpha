from datetime import UTC, datetime

import pytest

from onlyalpha.domain.identifiers import OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution import (
    OnlyExecutionCommitCoordinationStatus,
    OnlyExecutionCommitCoordinator,
    OnlyExecutionEventDeliveryMode,
    OnlyExecutionProjectionApplier,
    OnlyExecutionProjectionComponent,
    OnlyReferenceExecutionProjectionTarget,
)
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore, OnlyRuntimePersistenceStoreError
from tests.execution.factories.transaction_factory import (
    only_test_generic_t0_cash_buy_open_transaction,
    only_test_rehash,
)

_COMMITTED_AT = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
_PROJECTED_AT = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 2, tzinfo=UTC))


def _coordinator(
    store: OnlyInMemoryRuntimePersistenceStore,
    *,
    missing: OnlyExecutionProjectionComponent | None = None,
) -> OnlyExecutionCommitCoordinator:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    targets = {
        component: OnlyReferenceExecutionProjectionTarget(component)
        for component in OnlyExecutionProjectionComponent
        if component is not missing
    }
    for projection in prepared.projections:
        target = targets.get(projection.identity.component)
        if target is not None and projection.identity.expected_version:
            target.seed(
                projection.identity.entity_key,
                projection.identity.expected_version,
                projection.identity.expected_state_hash,
            )
    return OnlyExecutionCommitCoordinator(
        commit_port=store,
        query_port=store,
        projection_state_port=store,
        projection_applier=OnlyExecutionProjectionApplier(targets),
        now=lambda: _PROJECTED_AT,
    )


def test_commit_is_durable_before_projection_ready_and_duplicate_is_already_ready() -> None:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    store = OnlyInMemoryRuntimePersistenceStore()
    coordinator = _coordinator(store)

    first = coordinator.commit(prepared, committed_at=_COMMITTED_AT, projected_at=_PROJECTED_AT)
    duplicate = coordinator.commit(prepared, committed_at=_COMMITTED_AT, projected_at=_PROJECTED_AT)

    assert first.status is OnlyExecutionCommitCoordinationStatus.COMMITTED_AND_PROJECTED
    assert first.transaction_inserted
    assert first.transaction is not None and first.transaction.projection_ready
    assert first.delivery_intent.mode is OnlyExecutionEventDeliveryMode.DURABLE_OUTBOX
    assert duplicate.status is OnlyExecutionCommitCoordinationStatus.ALREADY_READY
    assert not duplicate.transaction_inserted
    assert store.pending_count(prepared.runtime_id) == len(prepared.outbox_events)


def test_same_id_with_changed_prepared_payload_is_a_transaction_conflict() -> None:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    changed = only_test_rehash(
        prepared,
        prepared_at=OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)),
    )
    store = OnlyInMemoryRuntimePersistenceStore()
    coordinator = _coordinator(store)
    assert coordinator.commit(prepared, committed_at=_COMMITTED_AT, projected_at=_PROJECTED_AT).transaction is not None

    result = coordinator.commit(changed, committed_at=_COMMITTED_AT, projected_at=_PROJECTED_AT)

    assert result.status is OnlyExecutionCommitCoordinationStatus.TRANSACTION_CONFLICT
    assert result.transaction is None
    assert result.delivery_intent.mode is OnlyExecutionEventDeliveryMode.NONE


def test_missing_target_marks_projection_failed_and_hides_outbox() -> None:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    store = OnlyInMemoryRuntimePersistenceStore()
    coordinator = _coordinator(store, missing=OnlyExecutionProjectionComponent.FEE)

    result = coordinator.commit(prepared, committed_at=_COMMITTED_AT, projected_at=_PROJECTED_AT)
    persisted = store.get_by_sequence(prepared.runtime_id, 1)

    assert result.status is OnlyExecutionCommitCoordinationStatus.PROJECTION_FAILED
    assert result.failure_component is OnlyExecutionProjectionComponent.FEE
    assert persisted is not None and not persisted.projection_ready
    assert persisted.projection_error == "missing projection target for FEE"
    assert store.pending(prepared.runtime_id, limit=100) == ()


@pytest.mark.parametrize(
    "missing",
    (
        OnlyExecutionProjectionComponent.ORDER,
        OnlyExecutionProjectionComponent.FEE,
        OnlyExecutionProjectionComponent.RISK,
    ),
)
def test_failure_before_first_after_middle_and_before_last_projection_preserves_exact_prefix(
    missing: OnlyExecutionProjectionComponent,
) -> None:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    store = OnlyInMemoryRuntimePersistenceStore()
    result = _coordinator(store, missing=missing).commit(
        prepared,
        committed_at=_COMMITTED_AT,
        projected_at=_PROJECTED_AT,
    )

    failed_projection = next(item for item in prepared.projections if item.identity.component is missing)
    assert result.status is OnlyExecutionCommitCoordinationStatus.PROJECTION_FAILED
    assert result.projection_result is not None
    assert len(result.projection_result.applied) == failed_projection.identity.projection_sequence - 1
    assert store.get_by_sequence(prepared.runtime_id, 1) is not None
    assert store.pending(prepared.runtime_id, limit=100) == ()


def test_sequence_gate_requires_the_immediate_predecessor_to_be_ready() -> None:
    first = only_test_generic_t0_cash_buy_open_transaction()
    second = only_test_generic_t0_cash_buy_open_transaction(
        trade_id=OnlyTradeId("trade-2"),
        update_id=type(first.broker_update_id)("update-2"),
        fill_index=2,
    )
    store = OnlyInMemoryRuntimePersistenceStore()
    store.commit(first, committed_at=_COMMITTED_AT)
    store.commit(second, committed_at=OnlyTimestamp(_COMMITTED_AT.unix_nanos + 1))
    coordinator = _coordinator(store)

    result = coordinator.commit(
        second,
        committed_at=OnlyTimestamp(_COMMITTED_AT.unix_nanos + 1),
        projected_at=_PROJECTED_AT,
    )

    assert result.status is OnlyExecutionCommitCoordinationStatus.SEQUENCE_BLOCKED
    assert result.transaction is not None and result.transaction.execution_sequence == 2
    assert not result.transaction.projection_ready


def test_recovery_stops_on_first_failed_transaction() -> None:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    store = OnlyInMemoryRuntimePersistenceStore()
    store.commit(prepared, committed_at=_COMMITTED_AT)
    coordinator = _coordinator(store, missing=OnlyExecutionProjectionComponent.FEE)

    results = coordinator.recover_unprojected(OnlyRuntimeId("runtime"))

    assert len(results) == 1
    assert results[0].status is OnlyExecutionCommitCoordinationStatus.PROJECTION_FAILED


class _OnlyFailingCommitStore(OnlyInMemoryRuntimePersistenceStore):
    def commit(self, prepared, *, committed_at):  # type: ignore[no-untyped-def]
        raise OnlyRuntimePersistenceStoreError("injected commit failure")


def test_store_commit_failure_never_applies_projection() -> None:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    store = _OnlyFailingCommitStore()

    result = _coordinator(store).commit(prepared, committed_at=_COMMITTED_AT, projected_at=_PROJECTED_AT)

    assert result.status is OnlyExecutionCommitCoordinationStatus.STORE_FAILURE
    assert store.records() == ()
    assert result.delivery_intent.mode is OnlyExecutionEventDeliveryMode.NONE


class _OnlyFailReadyOnceStore(OnlyInMemoryRuntimePersistenceStore):
    def __init__(self) -> None:
        super().__init__()
        self._failed = False

    def mark_projection_ready(
        self,
        runtime_id: OnlyRuntimeId,
        execution_sequence: int,
        *,
        projected_at: OnlyTimestamp,
    ) -> None:
        if not self._failed:
            self._failed = True
            raise OnlyRuntimePersistenceStoreError("injected ready failure")
        super().mark_projection_ready(runtime_id, execution_sequence, projected_at=projected_at)


def test_mark_ready_failure_hides_outbox_and_retry_is_projection_idempotent() -> None:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    store = _OnlyFailReadyOnceStore()
    coordinator = _coordinator(store)

    failed = coordinator.commit(prepared, committed_at=_COMMITTED_AT, projected_at=_PROJECTED_AT)
    assert failed.status is OnlyExecutionCommitCoordinationStatus.STORE_FAILURE
    assert failed.projection_result is not None
    assert len(failed.projection_result.applied) == len(prepared.projections)
    assert store.pending(prepared.runtime_id, limit=100) == ()

    recovered = coordinator.recover_unprojected(prepared.runtime_id)
    assert len(recovered) == 1
    assert recovered[0].status is OnlyExecutionCommitCoordinationStatus.COMMITTED_AND_PROJECTED
    assert recovered[0].projection_result is not None
    assert recovered[0].projection_result.applied == ()
    assert len(recovered[0].projection_result.idempotent) == len(prepared.projections)
    assert store.pending_count(prepared.runtime_id) == len(prepared.outbox_events)
