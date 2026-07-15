import json
from decimal import Decimal
from pathlib import Path

from onlyalpha.backtest import OnlyBacktestConfig, OnlyBacktestStatus
from onlyalpha.runtime import OnlyBacktestRuntime


def test_macd_backtest_product_api_and_result_export(tmp_path: Path) -> None:
    config = OnlyBacktestConfig.load("examples/backtest_macd/config.yaml")
    runtime = OnlyBacktestRuntime.from_config(config)
    result = runtime.run()
    result.save(tmp_path)
    assert result.status is OnlyBacktestStatus.COMPLETED
    assert runtime.state.value == "CLOSED"
    assert {
        "result.json",
        "orders.json",
        "trades.json",
        "positions.json",
        "allocations.json",
        "ledgers.json",
        "accounts.json",
        "equity.csv",
        "run_report.md",
    } <= {item.name for item in tmp_path.iterdir()}
    expected = json.loads(Path("examples/backtest_macd/expected_result.json").read_text(encoding="utf-8"))
    assert result.status.value == expected["status"]
    assert result.data.generated_bar_count == expected["generated_bar_count"]
    assert result.data.processed_bar_count == expected["processed_bar_count"]
    assert result.execution.order_count == expected["order_count"]
    assert result.execution.trade_count == expected["trade_count"]
    assert result.performance.final_equity.amount == Decimal(expected["final_equity"])
    assert result.determinism_fingerprint == expected["determinism_fingerprint"]
