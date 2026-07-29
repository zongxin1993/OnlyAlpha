from pathlib import Path

from onlyalpha.execution import (
    OnlyExecutionProjectionComponent,
    OnlyExecutionRecoveryStatus,
)
from onlyalpha.runtime.persistence.store import OnlySqliteRuntimePersistenceStore
from tests.execution.support.real_execution_recovery_harness import OnlyRealExecutionRecoveryHarness


def test_coordinator_recovers_reopened_persistence_with_fresh_test_authority(tmp_path: Path) -> None:
    """Component contract only; product restart is covered by the Engine integration test."""

    path = tmp_path / "runtime-recovery-component.sqlite3"
    first_store = OnlySqliteRuntimePersistenceStore(path)
    first = OnlyRealExecutionRecoveryHarness.create(
        store=first_store,
        target_fault=(OnlyExecutionProjectionComponent.ORDER, "before"),
    )
    assert first.recover().status is OnlyExecutionRecoveryStatus.FAILED
    committed = first_store.records(first.bundle.transaction.runtime_id)[0]
    first_store.close()

    reopened = OnlySqliteRuntimePersistenceStore(path)
    restarted = OnlyRealExecutionRecoveryHarness.create(store=reopened)
    recovery = restarted.recover()
    assert recovery.status is OnlyExecutionRecoveryStatus.RECOVERED
    ready = reopened.ready_records(committed.runtime_id)
    assert len(ready) == 1
    assert ready[0].transaction_id == committed.transaction_id
    assert ready[0].execution_sequence == committed.execution_sequence
    reopened.close()
