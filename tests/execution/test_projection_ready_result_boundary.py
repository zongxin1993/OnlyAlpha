from onlyalpha.collector import OnlyBacktestResultCollector
from onlyalpha.execution import OnlyExecutionProcessingStatus
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind
from tests.execution.support.real_execution_recovery_harness import OnlyRealExecutionRecoveryHarness
from tests.execution.test_long_close_terminal_planner import _terminal_update


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
    assert collected.facts.settlement_maturities == ()
    assert collected.facts.runtime_transactions == ()


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


def test_projection_ready_terminal_fact_does_not_enter_trade_result() -> None:
    environment, _, update = _terminal_update("CANCELLED")
    terminal = environment.runtime.execution_processor.process(update)
    assert terminal.status is not OnlyExecutionProcessingStatus.FAILED
    collector = OnlyBacktestResultCollector()
    collector.start()

    collected = collector.seal(environment.runtime, environment.runtime.clusters)

    ready = environment.runtime.ready_execution_query.ready_records(update.runtime_id)
    assert len(ready) == 5
    assert tuple(item.operation_kind for item in ready).count(OnlyRuntimeOperationKind.ORDER_ACCEPTED) == 2
    assert tuple(item.operation_kind for item in ready).count(OnlyRuntimeOperationKind.ORDER_TERMINAL) == 1
    assert len(collected.facts.executions) == 2
