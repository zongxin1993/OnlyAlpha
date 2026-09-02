import json
from pathlib import Path

import pyarrow.parquet as pq

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.engine.models import OnlyEngineRunResult
from tests.runtime_runner import only_migrate_cluster_to_strategy


def _run(target: Path) -> tuple[OnlyEngineRunResult, Path, dict[str, object]]:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("artifact-engine"), target))
    engine.add_cluster(
        only_migrate_cluster_to_strategy(
            OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json"),
            target,
        )
    )
    result = engine.run()
    assert result.manifest_path is not None
    root = result.manifest_path.parent
    manifest = json.loads((root / "artifact_manifest.json").read_text(encoding="utf-8"))
    return result, root, manifest


def test_engine_publishes_verified_standard_artifacts(tmp_path: Path) -> None:
    result, root, manifest = _run(tmp_path)

    assert result.status == "COMPLETED"
    assert manifest["result_fingerprint"] == result.cluster_results[0]["result_fingerprint"]
    assert manifest["analysis_fingerprint"]
    assert manifest["artifact_content_fingerprint"]
    assert manifest["artifacts"]
    assert manifest["schema_version"] == 6
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    assert summary["market_product"]["product_id"] == "GENERIC_T0_CASH"
    assert summary["market_product"]["product_version"] == "1"
    assert summary["market_product"]["provider_plugin_id"] == "onlyalpha-plugin-generic-t0-cash"
    assert len(summary["market_product"]["composition_fingerprint"]) == 64
    expected_rows = {
        "orders.parquet": 0,
        "executions.parquet": 0,
        "trades.parquet": 0,
        "positions.parquet": 0,
        "accounts.parquet": 1,
        "equity.parquet": 722,
        "cluster_equity.parquet": 722,
        "signals.parquet": 0,
    }
    for relative_path, row_count in expected_rows.items():
        table = pq.read_table(root / relative_path)
        assert table.num_rows == row_count
        assert table.num_columns > 0
    executions = pq.read_table(root / "executions.parquet").to_pylist()
    assert executions == []
    assert all(
        item["turnover"] == item["price"] * item["quantity"] * item["contract_multiplier"] for item in executions
    )
    assert all(item["slippage"] is not None for item in executions)
    assert all(item["position_side"] == "LONG" for item in executions)
    assert all(item["market_product_id"] and item["market_product_version"] for item in executions)
