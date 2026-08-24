from pathlib import Path

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from tests.runtime_runner import only_migrate_cluster_to_strategy


def test_installed_virtual_plugin_is_created_through_entry_point_registry(tmp_path: Path) -> None:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("builtin-broker"), tmp_path))
    engine.add_cluster(
        only_migrate_cluster_to_strategy(OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json"), tmp_path)
    )
    result = engine.run()
    assert result.status == "COMPLETED"
    assert engine.runtime_sessions[0].runtime.plugin_resource_snapshots[1].plugin_id == "virtual"
