from examples.integration_demo.environment import OnlyIntegrationEnvironment, OnlyScenarioReport
from onlyalpha.config import OnlyRunConfig
from onlyalpha.runtime.backtest.result import OnlyBacktestStatus
from onlyalpha.runtime.defaults import only_default_run_service


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    result = only_default_run_service().run(OnlyRunConfig.load("examples/configs/backtest/macd/run.yaml"), export=False)
    assert result.status is OnlyBacktestStatus.COMPLETED
    assert result.execution.order_count == 2
    assert result.execution.trade_count == 2
    signals = result.cluster_results[0].strategy_result_extension["signals"]
    assert isinstance(signals, list)
    assert sum(item["signal_type"] == "DEATH_CROSS_BLOCKED" for item in signals) == 1
    env.product_backtest_fingerprint = result.determinism_fingerprint
    return env.report_builder.scenario(
        "034",
        "合成 MACD Product Backtest",
        "配置 → Runtime → Replay → VirtualBroker → ExecutionProcessor → Result",
    )
