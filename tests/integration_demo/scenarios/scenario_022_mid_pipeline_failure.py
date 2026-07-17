from collections.abc import Callable

from onlyalpha.execution import OnlyExecutionProcessingResult, OnlyExecutionProcessingStatus
from tests.integration_demo.environment import DAY_ONE, OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    failed = OnlyIntegrationEnvironment()
    failed.start()
    for minute in range(3):
        failed.process_bar(DAY_ONE, minute, "10.00")
    failed.submit_buy()
    manager = failed.runtime.strategy_ledger_manager
    original: Callable[..., object] = manager.apply_trade_accounting

    def explicit_failure_adapter(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("explicit integration Ledger failure adapter")

    manager.apply_trade_accounting = explicit_failure_adapter  # type: ignore[method-assign]
    try:
        failed.process_bar(DAY_ONE, 4, "10.00")
    finally:
        manager.apply_trade_accounting = original  # type: ignore[method-assign]
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
    assert "EXECUTION_PROCESSING_FAILED" in event_types
    return env.report_builder.scenario(
        "022",
        "中途失败",
        "Ledger Test Adapter 失败后仅发布失败事实并保留 completed steps/Reconciliation Request",
    )
