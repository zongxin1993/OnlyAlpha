from decimal import Decimal
from pathlib import Path

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from tests.runtime_runner import only_migrate_cluster_to_strategy


def test_macd_backtest_product_api_and_result_export(tmp_path: Path) -> None:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("product-api"), tmp_path))
    engine.add_cluster(
        only_migrate_cluster_to_strategy(OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json"), tmp_path)
    )
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
    projection = result.cluster_results[0]
    assert projection["run"]["status"] == "COMPLETED"
    assert projection["data"]["generated_bar_count"] == 720
    assert projection["data"]["processed_bar_count"] == 720
    assert projection["orders"] == []
    assert projection["trades"] == []
    assert Decimal(projection["runtime_performance"]["final_equity"]["amount"]) == Decimal("1000000.00")
