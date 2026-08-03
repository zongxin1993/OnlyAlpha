import json
from pathlib import Path

import pyarrow.parquet as pq

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.engine.models import OnlyEngineRunResult


def _run(target: Path) -> tuple[OnlyEngineRunResult, Path, dict[str, object]]:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("artifact-engine"), target))
    engine.add_cluster_from_file("tests/fixtures/legacy_macd/cluster.json")
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
    assert manifest["schema_version"] == 3
    expected_rows = {
        "orders.parquet": 2,
        "executions.parquet": 2,
        "trades.parquet": 1,
        "positions.parquet": 0,
        "accounts.parquet": 1,
        "equity.parquet": 731,
        "cluster_equity.parquet": 732,
        "signals.parquet": 0,
    }
    for relative_path, row_count in expected_rows.items():
        table = pq.read_table(root / relative_path)
        assert table.num_rows == row_count
        assert table.num_columns > 0
    executions = pq.read_table(root / "executions.parquet").to_pylist()
    assert all(item["fees"] > 0 for item in executions)
    assert all(
        item["turnover"] == item["price"] * item["quantity"] * item["contract_multiplier"] for item in executions
    )
    assert all(item["slippage"] is not None for item in executions)
    assert all(item["position_side"] == "LONG" for item in executions)
    assert [item["position_effect"] for item in executions] == ["OPEN", "CLOSE"]
    assert all(item["market_profile_id"] and item["market_profile_version"] for item in executions)
