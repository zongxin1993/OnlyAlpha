from datetime import UTC, datetime

from onlyalpha.domain.identifiers import OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution import (
    OnlyExecutionCommitCoordinationStatus,
    OnlyExecutionCommitCoordinator,
    OnlyExecutionProjectionApplier,
    OnlyExecutionProjectionComponent,
    OnlyExecutionRecoveryService,
    OnlyExecutionRecoveryStatus,
    OnlyReferenceExecutionProjectionTarget,
)
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore, OnlyRuntimePersistenceStoreError
from tests.execution.factories.transaction_factory import only_test_generic_t0_cash_buy_open_transaction

_NOW = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 10, tzinfo=UTC))


def _service(
    store: OnlyInMemoryRuntimePersistenceStore,
    *,
    missing: OnlyExecutionProjectionComponent | None = None,
) -> OnlyExecutionRecoveryService:
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
    return OnlyExecutionRecoveryService(
        OnlyExecutionCommitCoordinator(
            commit_port=store,
            query_port=store,
            projection_state_port=store,
            projection_applier=OnlyExecutionProjectionApplier(targets),
            now=lambda: _NOW,
        )
    )


def test_recovery_reports_no_work_without_committed_tail() -> None:
    result = _service(OnlyInMemoryRuntimePersistenceStore()).recover(OnlyRuntimeId("runtime"))

    assert result.status is OnlyExecutionRecoveryStatus.NO_WORK
    assert result.succeeded
    assert result.attempted_transactions == 0


def test_recovery_completes_committed_tail_and_reports_component_counts() -> None:
    store = OnlyInMemoryRuntimePersistenceStore()
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    store.commit(prepared, committed_at=_NOW)

    result = _service(store).recover(prepared.runtime_id)

    assert result.status is OnlyExecutionRecoveryStatus.RECOVERED
    assert result.succeeded
    assert result.attempted_transactions == result.completed_transactions == 1
    assert store.ready_count(prepared.runtime_id) == 1


def test_recovery_stops_and_preserves_diagnostic_on_projection_failure() -> None:
    store = OnlyInMemoryRuntimePersistenceStore()
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    store.commit(prepared, committed_at=_NOW)

    result = _service(store, missing=OnlyExecutionProjectionComponent.FEE).recover(prepared.runtime_id)

    assert result.status is OnlyExecutionRecoveryStatus.FAILED
    assert not result.succeeded
    assert result.failed_sequence == 1
    assert result.failed_transaction_id == prepared.transaction_id
    assert result.failure_component is OnlyExecutionProjectionComponent.FEE
    assert result.coordinator_status is OnlyExecutionCommitCoordinationStatus.PROJECTION_FAILED
    assert store.ready_records(prepared.runtime_id) == ()


class _OnlyQueryFailingStore(OnlyInMemoryRuntimePersistenceStore):
    def unprojected(self, runtime_id: OnlyRuntimeId, *, after_sequence: int = 0):  # type: ignore[no-untyped-def]
        raise OnlyRuntimePersistenceStoreError("injected query failure")


def test_recovery_query_failure_is_not_misreported_as_no_work() -> None:
    store = _OnlyQueryFailingStore()
    result = _service(store).recover(OnlyRuntimeId("runtime"))

    assert result.status is OnlyExecutionRecoveryStatus.STORE_FAILURE
    assert not result.succeeded
    assert result.coordinator_status is OnlyExecutionCommitCoordinationStatus.STORE_FAILURE
    assert "injected query failure" in (result.error or "")


class _OnlySecondOnlyRecoveryStore(OnlyInMemoryRuntimePersistenceStore):
    def unprojected(self, runtime_id: OnlyRuntimeId, *, after_sequence: int = 0):  # type: ignore[no-untyped-def]
        return super().unprojected(runtime_id, after_sequence=after_sequence)[1:]


def test_recovery_does_not_skip_an_unready_predecessor() -> None:
    store = _OnlySecondOnlyRecoveryStore()
    first = only_test_generic_t0_cash_buy_open_transaction()
    second = only_test_generic_t0_cash_buy_open_transaction(
        trade_id=OnlyTradeId("trade-2"),
        update_id=type(first.broker_update_id)("update-2"),
        fill_index=2,
    )
    store.commit(first, committed_at=_NOW)
    store.commit(second, committed_at=OnlyTimestamp(_NOW.unix_nanos + 1))

    result = _service(store).recover(first.runtime_id)

    assert result.status is OnlyExecutionRecoveryStatus.SEQUENCE_BLOCKED
    assert result.blocked_sequence == 2
    assert result.failed_sequence == 2
    assert store.ready_count(first.runtime_id) == 0
