from onlyalpha.execution import (
    OnlyExecutionProcessingResult,
    OnlyExecutionProcessingStatus,
    OnlyRuntimeProjectionComponent,
)
from onlyalpha.transaction import OnlyRuntimeOperationKind
from tests.execution.support.execution_fault_injection import OnlyFailOnceExecutionProjectionTarget

from ..environment import DAY_ONE, OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    failed = OnlyIntegrationEnvironment()
    failed.start()
    for minute in range(3):
        failed.process_bar(DAY_ONE, minute, "10.00")
    failed.submit_buy()
    coordinator = failed.runtime.execution_processor._execution_commit_coordinator
    applier = coordinator._projection_applier
    component = OnlyRuntimeProjectionComponent.STRATEGY_LEDGER
    applier._targets[component] = OnlyFailOnceExecutionProjectionTarget(
        applier._targets[component],
        fail_before=True,
    )
    failed.process_bar(DAY_ONE, 4, "10.00")
    result = next(
        item
        for item in reversed(failed.runtime.broker_results)
        if isinstance(item, OnlyExecutionProcessingResult) and item.update_type == "OnlyBrokerTradeUpdate"
    )
    event_types = tuple(str(item.event.event_type) for item in failed.runtime.event_bus.dispatch_results)
    assert result.status is OnlyExecutionProcessingStatus.RECONCILIATION_REQUIRED
    assert result.reconciliation_request is not None
    assert "ORDER_FILLED" not in event_types
    assert "STRATEGY_TRADE_APPLIED" not in event_types
    committed = failed.runtime.execution_transaction_query.records(failed.runtime.config.runtime_id)
    assert tuple(item.operation_kind for item in committed) == (
        OnlyRuntimeOperationKind.ORDER_ACCEPTED,
        OnlyRuntimeOperationKind.TRADE_FILL,
    )
    assert committed[0].projection_ready
    assert not committed[1].projection_ready
    assert failed.runtime.ready_execution_query.ready_records(failed.runtime.config.runtime_id) == (committed[0],)
    assert failed.runtime.execution_reconciliation_queue.requests() == (result.reconciliation_request,)
    return env.report_builder.scenario(
        "022",
        "中途失败",
        "Ledger Test Adapter 失败后仅发布失败事实并保留 completed steps/Reconciliation Request",
    )
