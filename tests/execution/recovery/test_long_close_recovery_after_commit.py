import pytest

from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore, OnlySqliteRuntimePersistenceStore
from tests.execution.support.real_execution_recovery_harness import OnlyRealExecutionRecoveryHarness


@pytest.mark.parametrize("sqlite", (False, True))
def test_long_close_committed_before_projection_is_forward_recoverable(tmp_path, sqlite: bool) -> None:
    store = (
        OnlySqliteRuntimePersistenceStore(tmp_path / "long-close.sqlite3")
        if sqlite
        else OnlyInMemoryRuntimePersistenceStore()
    )
    try:
        harness = OnlyRealExecutionRecoveryHarness.create(store=store, long_close=True)
        runtime_id = harness.bundle.transaction.runtime_id
        assert len(store.records(runtime_id)) == 1
        assert store.ready_records(runtime_id) == ()
        assert store.pending(runtime_id, limit=100) == ()

        recovered = harness.recover()

        assert recovered.succeeded
        assert store.ready_count(runtime_id) == 1
        assert len(harness.applied_ledger.records()) == len(harness.bundle.transaction.projections)
    finally:
        store.close()
