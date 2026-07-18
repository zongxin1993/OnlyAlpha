import json
from decimal import Decimal
from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig


def test_macd_backtest_product_api_and_result_export(tmp_path: Path) -> None:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("product-api"), tmp_path))
    engine.add_cluster_from_file("tests/fixtures/legacy_macd/cluster.json")
    result = engine.run()
    assert result.status == "COMPLETED"
    assert result.manifest_path is not None
    run_directory = result.manifest_path.parent
    assert {
        "engine",
        "clusters",
        "runtimes",
        "shared",
        "logs",
    } <= {item.name for item in run_directory.iterdir()}
    expected = json.loads(Path("tests/fixtures/legacy_macd/expected_result.json").read_text(encoding="utf-8"))
    projection = result.cluster_results[0]
    assert projection["run"]["status"] == expected["status"]
    assert projection["data"]["generated_bar_count"] == expected["generated_bar_count"]
    assert projection["data"]["processed_bar_count"] == expected["processed_bar_count"]
    assert len(projection["orders"]) == expected["order_count"]
    assert len(projection["trades"]) == expected["trade_count"]
    assert Decimal(projection["performance"]["final_equity"]["amount"]) == Decimal(expected["final_equity"])
