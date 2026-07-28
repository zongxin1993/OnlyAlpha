from pathlib import Path

from onlyalpha.execution import (
    OnlyExecutionOutboxPublisher,
    OnlyExecutionProjectionComponent,
    OnlyExecutionRecoveryStatus,
    OnlySqliteExecutionTransactionStore,
    only_committed_execution_transaction_payload_hash,
)
from onlyalpha.runtime.runtime import OnlyRuntimeState
from tests.execution.support.real_execution_recovery_harness import OnlyRealExecutionRecoveryHarness


def test_fresh_bootstrap_runtime_authority_recovers_sqlite_tail_and_stable_outbox_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime-restart.sqlite3"
    first_store = OnlySqliteExecutionTransactionStore(path)
    first = OnlyRealExecutionRecoveryHarness.create(
        store=first_store,
        target_fault=(OnlyExecutionProjectionComponent.ACCOUNT, "before"),
    )
    assert first.recover().status is OnlyExecutionRecoveryStatus.FAILED
    committed = first_store.records(first.bundle.transaction.runtime_id)[0]
    event_ids = tuple(item.event.event_id for item in first_store.outbox_records(committed.runtime_id))
    first_store.close()

    reopened = OnlySqliteExecutionTransactionStore(path)
    try:
        restarted = OnlyRealExecutionRecoveryHarness.create(store=reopened)
        runtime = restarted.bundle.environment.runtime
        runtime._services.execution_commit_coordinator = restarted.coordinator
        runtime._services.execution_recovery_service = restarted.recovery_service
        runtime._services.execution_transaction_query = reopened
        runtime._services.ready_execution_query = reopened
        runtime._services.execution_projection_state = reopened
        runtime._services.execution_transaction_outbox = reopened
        runtime._services.execution_outbox_publisher = OnlyExecutionOutboxPublisher(
            reopened,
            runtime.event_bus,
            lambda: type(committed.committed_at).from_unix_nanos(runtime.clock.timestamp_ns()),
        )
        runtime._services.cluster_manager._clusters.clear()
        runtime._execution_recovery_diagnostics.clear()
        runtime._state = OnlyRuntimeState.CREATED

        runtime.initialize()
        result = runtime.execution_recovery_diagnostics[-1]

        assert result.succeeded
        assert result.status is OnlyExecutionRecoveryStatus.RECOVERED
        assert runtime.state is OnlyRuntimeState.READY
        ready = reopened.ready_records(committed.runtime_id)
        assert len(ready) == 1
        assert ready[0].transaction_id == committed.transaction_id
        assert ready[0].execution_sequence == committed.execution_sequence
        assert ready[0].prepared_authority_hash == committed.prepared_authority_hash
        assert ready[0].prepared_payload_hash == committed.prepared_payload_hash
        assert ready[0].committed_payload_hash == only_committed_execution_transaction_payload_hash(ready[0])
        assert tuple(item.event.event_id for item in reopened.outbox_records(committed.runtime_id)) == event_ids
        assert reopened.pending_count(committed.runtime_id) == len(event_ids)
        runtime.start()
        assert runtime.state is OnlyRuntimeState.RUNNING
        assert reopened.pending_count(committed.runtime_id) == 0
    finally:
        reopened.close()
