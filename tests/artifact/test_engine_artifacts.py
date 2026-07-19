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


def test_engine_publishes_deterministic_standard_artifacts(tmp_path: Path) -> None:
    first_result, first_root, first = _run(tmp_path / "first")
    second_result, _, second = _run(tmp_path / "second")

    assert first_result.status == second_result.status == "COMPLETED"
    assert first["result_fingerprint"] == second["result_fingerprint"]
    assert first["analysis_fingerprint"] == second["analysis_fingerprint"]
    assert first["artifact_content_fingerprint"] == second["artifact_content_fingerprint"]
    assert first["artifacts"] == second["artifacts"]
    expected_rows = {
        "orders.parquet": 2,
        "executions.parquet": 2,
        "trades.parquet": 1,
        "positions.parquet": 0,
        "accounts.parquet": 1,
        "equity.parquet": 1,
        "signals.parquet": 0,
    }
    for relative_path, row_count in expected_rows.items():
        table = pq.read_table(first_root / relative_path)
        assert table.num_rows == row_count
        assert table.num_columns > 0
