from pathlib import Path

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from tests.runtime_runner import only_migrate_cluster_to_strategy


def test_builtin_synthetic_is_created_through_plugin_registry(tmp_path: Path) -> None:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("builtin-data"), tmp_path))
    engine.add_cluster(
        only_migrate_cluster_to_strategy(OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json"), tmp_path)
    )
    result = engine.run()
    assert result.status == "COMPLETED"
    assert engine.runtime_sessions[0].runtime.plugin_resource_snapshots[0].plugin_id == "synthetic"
