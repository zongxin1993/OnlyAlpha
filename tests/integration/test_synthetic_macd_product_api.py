import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from onlyalpha.config import OnlyRunConfig
from onlyalpha.runtime.backtest.result import OnlyBacktestStatus
from onlyalpha.runtime.defaults import only_default_run_service


def test_macd_backtest_product_api_and_result_export(tmp_path: Path) -> None:
    config = OnlyRunConfig.load("examples/backtest_macd/config.yaml")
    config = replace(config, output=replace(config.output, root_directory=str(tmp_path), overwrite=True))
    service = only_default_run_service()
    result = service.run(config)
    assert result.status is OnlyBacktestStatus.COMPLETED
    assert service.last_manifest is not None
    run_directory = service.last_manifest.layout.run_directory
    assert {
        "config",
        "runtime",
        "market_data",
        "execution",
        "portfolio",
        "strategies",
        "reports",
        "logs",
    } <= {item.name for item in run_directory.iterdir()}
    expected = json.loads(Path("examples/backtest_macd/expected_result.json").read_text(encoding="utf-8"))
    assert result.status.value == expected["status"]
    assert result.data.generated_bar_count == expected["generated_bar_count"]
    assert result.data.processed_bar_count == expected["processed_bar_count"]
    assert result.execution.order_count == expected["order_count"]
    assert result.execution.trade_count == expected["trade_count"]
    assert result.performance.final_equity.amount == Decimal(expected["final_equity"])
    assert result.determinism_fingerprint == expected["determinism_fingerprint"]
