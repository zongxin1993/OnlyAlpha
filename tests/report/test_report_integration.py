import json
from pathlib import Path

from onlyalpha.cli import main
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig

CONFIG = "tests/fixtures/legacy_macd/cluster.json"


def test_engine_publishes_concise_reports_without_recalculating(tmp_path: Path) -> None:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("report-engine"), tmp_path))
    engine.add_cluster_from_file(CONFIG)

    result = engine.run()

    assert result.status == "COMPLETED"
    assert len(result.backtest_reports) == len(result.console_reports) == len(result.report_paths) == 1
    projection = result.backtest_reports[0]
    assert projection["order_count"] == 2
    assert projection["execution_count"] == 2
    assert projection["trade_count"] == 1
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


def test_cli_keeps_single_json_line_and_adds_report_fields(tmp_path: Path, capsys: object) -> None:
    assert main(["run", "--config", CONFIG, "--user-data", str(tmp_path)]) == 0

    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["status"] == "COMPLETED"
    assert payload["cluster_count"] == 1
    assert payload["trade_count"] == 1
    assert Path(payload["report_path"]).is_file()
    assert Path(payload["manifest_path"]).is_file()


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
