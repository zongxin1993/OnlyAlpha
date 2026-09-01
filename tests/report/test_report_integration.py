from pathlib import Path

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from tests.runtime_runner import only_write_migrated_cluster_config

CONFIG = "tests/fixtures/legacy_macd/cluster.json"


def test_engine_publishes_concise_reports_without_recalculating(tmp_path: Path) -> None:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("report-engine"), tmp_path))
    engine.add_cluster(OnlyClusterRunConfig.load(only_write_migrated_cluster_config(CONFIG, tmp_path)))

    result = engine.run()

    assert result.status == "COMPLETED"
    assert len(result.backtest_reports) == len(result.console_reports) == len(result.report_paths) == 1
    projection = result.backtest_reports[0]
    assert projection["order_count"] == 0
    assert projection["execution_count"] == 0
    assert projection["trade_count"] == 0
    assert projection["result_fingerprint"]
    assert "orders" not in projection
    report = result.report_paths[0].read_text(encoding="utf-8")
    for heading in (
        "Run Summary",
        "Data Summary",
        "Strategy Summary",
        "Order Summary",
        "Execution Summary",
        "Trade Summary",
        "Runtime Portfolio Performance (Account authority)",
        "Cluster Performance (Strategy Ledger authority)",
        "Runtime/Cluster Reconciliation",
        "Final Account",
        "Final Positions",
        "Diagnostics",
        "Artifacts",
        "Fingerprints",
    ):
        assert f"## {heading}" in report


def test_report_module_has_no_runtime_service_or_plugin_dependencies() -> None:
    source = Path("src/onlyalpha/report/renderers.py").read_text(encoding="utf-8")
    for forbidden in (
        "onlyalpha.cluster",
        "onlyalpha.broker",
        "onlyalpha.data",
        "onlyalpha.strategy",
        "onlyalpha.engine",
    ):
        assert forbidden not in source
