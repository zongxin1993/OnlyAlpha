from onlyalpha.collector import OnlyBacktestResultCollector
from tests.execution.support.real_execution_recovery_harness import OnlyRealExecutionRecoveryHarness


def test_committed_but_unprojected_transaction_is_hidden_from_formal_result_facts() -> None:
    harness = OnlyRealExecutionRecoveryHarness.create()
    runtime = harness.bundle.environment.runtime
    runtime._services.execution_transaction_query = harness.transaction_store
    runtime._services.ready_execution_query = harness.transaction_store
    collector = OnlyBacktestResultCollector()
    collector.start()

    collected = collector.seal(runtime, runtime.clusters)

    assert harness.transaction_store.records(runtime.config.runtime_id)  # type: ignore[arg-type]
    assert harness.transaction_store.ready_records(runtime.config.runtime_id) == ()  # type: ignore[arg-type]
    assert collected.facts.executions == ()


def test_projection_ready_transaction_enters_formal_result_exactly_once() -> None:
    harness = OnlyRealExecutionRecoveryHarness.create()
    assert harness.recover().succeeded
    runtime = harness.bundle.environment.runtime
    runtime._services.execution_transaction_query = harness.transaction_store
    runtime._services.ready_execution_query = harness.transaction_store
    collector = OnlyBacktestResultCollector()
    collector.start()

    collected = collector.seal(runtime, runtime.clusters)

    assert len(collected.facts.executions) == 1
    assert collected.facts.executions[0].execution_id == harness.bundle.transaction.fact.execution_id
