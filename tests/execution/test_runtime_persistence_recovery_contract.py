from collections.abc import Iterator
from pathlib import Path

import pytest

from onlyalpha.execution import (
    OnlyExecutionProjectionComponent,
    OnlyExecutionRecoveryStatus,
)
from onlyalpha.runtime.persistence.store import (
    OnlyInMemoryRuntimePersistenceStore,
    OnlyRuntimePersistenceStoreError,
    OnlyRuntimePersistenceStorePort,
    OnlySqliteRuntimePersistenceStore,
)
from tests.execution.support.execution_fault_injection import (
    OnlyFailOnceRuntimePersistenceStore,
    OnlyTestRuntimePersistenceFault,
)
from tests.execution.support.generic_t0_trade_harness import (
    OnlyTestGenericT0Scenario,
    only_test_generic_t0_projection_environment,
)
from tests.execution.support.manager_authority_digest import only_test_runtime_authority_digest
from tests.execution.support.real_execution_recovery_harness import OnlyRealExecutionRecoveryHarness


@pytest.fixture(params=("memory", "sqlite"))
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[OnlyRuntimePersistenceStorePort]:
    selected: OnlyRuntimePersistenceStorePort
    if request.param == "memory":
        selected = OnlyInMemoryRuntimePersistenceStore()
    else:
        selected = OnlySqliteRuntimePersistenceStore(tmp_path / "recovery-contract.sqlite3")
    yield selected
    if isinstance(selected, OnlySqliteRuntimePersistenceStore):
        selected.close()


def test_commit_failure_leaves_persistence_and_real_managers_unchanged(
    store: OnlyRuntimePersistenceStorePort,
) -> None:
    environment, context, prepared = only_test_generic_t0_projection_environment(
        OnlyTestGenericT0Scenario("commit-failure")
    )
    before = only_test_runtime_authority_digest(environment)
    faulting = OnlyFailOnceRuntimePersistenceStore(store, OnlyTestRuntimePersistenceFault.COMMIT)

    with pytest.raises(OnlyRuntimePersistenceStoreError, match="COMMIT"):
        faulting.commit(prepared, committed_at=context.prepared_at)

    assert store.records(prepared.runtime_id) == ()
    assert store.outbox_records(prepared.runtime_id) == ()
    assert only_test_runtime_authority_digest(environment) == before


def test_committed_before_projection_interruption_is_forward_recoverable(
    store: OnlyRuntimePersistenceStorePort,
) -> None:
    harness = OnlyRealExecutionRecoveryHarness.create(store=store)
    before = harness.manager_digest()
    assert store.records(harness.bundle.transaction.runtime_id)
    assert store.ready_records(harness.bundle.transaction.runtime_id) == ()
    assert store.pending(harness.bundle.transaction.runtime_id, limit=100) == ()
    assert harness.manager_digest() == before

    assert harness.recover().succeeded
    assert store.ready_count(harness.bundle.transaction.runtime_id) == 1


def test_mark_ready_failure_retries_all_real_targets_idempotently(
    store: OnlyRuntimePersistenceStorePort,
) -> None:
    faulting = OnlyFailOnceRuntimePersistenceStore(store, OnlyTestRuntimePersistenceFault.MARK_READY)
    harness = OnlyRealExecutionRecoveryHarness.create(store=faulting)

    failed = harness.recover()
    manager_after_projection = harness.manager_digest()

    assert failed.status is OnlyExecutionRecoveryStatus.STORE_FAILURE
    assert len(harness.applied_ledger.records()) == 12
    assert store.ready_count(harness.bundle.transaction.runtime_id) == 0
    assert store.pending(harness.bundle.transaction.runtime_id, limit=100) == ()

    recovered = harness.recover()

    assert recovered.succeeded
    assert recovered.idempotent_transactions == 1
    assert harness.manager_digest() == manager_after_projection
    assert store.ready_count(harness.bundle.transaction.runtime_id) == 1


def test_mark_failed_failure_preserves_original_projection_error_and_tail(
    store: OnlyRuntimePersistenceStorePort,
) -> None:
    faulting = OnlyFailOnceRuntimePersistenceStore(store, OnlyTestRuntimePersistenceFault.MARK_FAILED)
    harness = OnlyRealExecutionRecoveryHarness.create(
        store=faulting,
        target_fault=(OnlyExecutionProjectionComponent.FEE, "before"),
    )

    failed = harness.recover()

    assert failed.status is OnlyExecutionRecoveryStatus.STORE_FAILURE
    assert "injected failure before FEE" in (failed.error or "")
    assert "MARK_FAILED" in (failed.error or "")
    assert len(store.records(harness.bundle.transaction.runtime_id)) == 1
    assert store.ready_records(harness.bundle.transaction.runtime_id) == ()
    assert store.pending(harness.bundle.transaction.runtime_id, limit=100) == ()

    recovered = harness.recover()
    assert recovered.succeeded


def test_query_failure_blocks_recovery_instead_of_reporting_no_work(
    store: OnlyRuntimePersistenceStorePort,
) -> None:
    faulting = OnlyFailOnceRuntimePersistenceStore(store, OnlyTestRuntimePersistenceFault.QUERY)
    harness = OnlyRealExecutionRecoveryHarness.create(store=faulting)

    failed = harness.recover()

    assert failed.status is OnlyExecutionRecoveryStatus.STORE_FAILURE
    assert store.ready_records(harness.bundle.transaction.runtime_id) == ()


def test_sqlite_reopen_with_fresh_bootstrap_authority_recovers_transaction_tail(tmp_path: Path) -> None:
    path = tmp_path / "runtime-restart.sqlite3"
    first_store = OnlySqliteRuntimePersistenceStore(path)
    first = OnlyRealExecutionRecoveryHarness.create(
        store=first_store,
        target_fault=(OnlyExecutionProjectionComponent.FEE, "before"),
    )
    failed = first.recover()
    assert failed.status is OnlyExecutionRecoveryStatus.FAILED
    transaction_before = first_store.records(first.bundle.transaction.runtime_id)
    outbox_before = first_store.outbox_records(first.bundle.transaction.runtime_id)
    first_store.close()

    reopened = OnlySqliteRuntimePersistenceStore(path)
    try:
        restarted = OnlyRealExecutionRecoveryHarness.create(store=reopened)
        recovered = restarted.recover()

        assert recovered.succeeded
        assert reopened.ready_count(restarted.bundle.transaction.runtime_id) == 1
        assert (
            reopened.records(restarted.bundle.transaction.runtime_id)[0].transaction_id
            == transaction_before[0].transaction_id
        )
        assert reopened.records(restarted.bundle.transaction.runtime_id)[0].committed_payload_hash != ""
        assert tuple(
            item.event.event_id for item in reopened.outbox_records(restarted.bundle.transaction.runtime_id)
        ) == tuple(item.event.event_id for item in outbox_before)
    finally:
        reopened.close()
