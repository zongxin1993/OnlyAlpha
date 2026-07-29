import pytest

from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore
from onlyalpha.runtime.recovery.tail import OnlyExecutionTransactionTailAnalyzer
from tests.execution.support.generic_t0_trade_harness import OnlyTestGenericT0Scenario
from tests.execution.targets.support import only_test_projection_target_bundle


def test_tail_analyzer_classifies_multiple_ready_then_unprojected_transactions() -> None:
    store = OnlyInMemoryRuntimePersistenceStore()
    first = only_test_projection_target_bundle(OnlyTestGenericT0Scenario("tail-1"), store).transaction
    second = only_test_projection_target_bundle(OnlyTestGenericT0Scenario("tail-2"), store).transaction
    only_test_projection_target_bundle(OnlyTestGenericT0Scenario("tail-3"), store)
    runtime_id = first.runtime_id
    store.mark_projection_ready(runtime_id, 1, projected_at=first.committed_at)
    store.mark_projection_ready(runtime_id, 2, projected_at=second.committed_at)
    tail = OnlyExecutionTransactionTailAnalyzer(store).analyze(
        runtime_id,
        checkpoint_sequence=1,
        covered_execution_sequence=0,
    )
    assert tuple(item.execution_sequence for item in tail.ready_prefix) == (1, 2)
    assert tuple(item.execution_sequence for item in tail.unprojected_suffix) == (3,)


def test_tail_analyzer_rejects_ready_after_unprojected() -> None:
    store = OnlyInMemoryRuntimePersistenceStore()
    first = only_test_projection_target_bundle(OnlyTestGenericT0Scenario("invalid-tail-1"), store).transaction
    second = only_test_projection_target_bundle(OnlyTestGenericT0Scenario("invalid-tail-2"), store).transaction
    runtime_id = first.runtime_id
    store.mark_projection_ready(runtime_id, 2, projected_at=second.committed_at)
    with pytest.raises(ValueError, match="TRANSACTION_TAIL_ORDER_INVALID"):
        OnlyExecutionTransactionTailAnalyzer(store).analyze(
            runtime_id,
            checkpoint_sequence=1,
            covered_execution_sequence=0,
        )
