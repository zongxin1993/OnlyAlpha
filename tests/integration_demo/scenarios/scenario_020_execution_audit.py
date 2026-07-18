from onlyalpha.execution import OnlyExecutionMutationStep, OnlyExecutionProcessingStatus

from ..environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    trade = next(
        item for item in env.runtime.execution_audit_store.records() if item.update_type == "OnlyBrokerTradeUpdate"
    )
    assert trade.status is OnlyExecutionProcessingStatus.APPLIED
    assert trade.completed_steps[:6] == (
        OnlyExecutionMutationStep.VALIDATION,
        OnlyExecutionMutationStep.ORDER,
        OnlyExecutionMutationStep.POSITION,
        OnlyExecutionMutationStep.ALLOCATION,
        OnlyExecutionMutationStep.STRATEGY_LEDGER,
        OnlyExecutionMutationStep.ACCOUNT,
    )
    assert trade.invariant_result.passed
    return env.report_builder.scenario(
        "020",
        "ExecutionProcessor Audit",
        "Trade 固定步骤、跨组件不变量与事实发布均有确定性 Audit",
    )
