from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig


def test_builtin_synthetic_is_created_through_plugin_registry(tmp_path: Path) -> None:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("builtin-data"), tmp_path))
    engine.add_cluster_from_file("tests/fixtures/legacy_macd/cluster.json")
    result = engine.run()
    assert result.status == "COMPLETED"
    assert engine.runtime_sessions[0].runtime.plugin_resource_snapshots[0].plugin_id == "synthetic"
