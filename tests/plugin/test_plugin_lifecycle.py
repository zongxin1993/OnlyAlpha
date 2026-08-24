from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.plugin import OnlyPluginHealthStatus, OnlyPluginLifecycleState
from onlyalpha.runtime.defaults import only_default_engine_services
from tests.runtime_runner import only_write_migrated_cluster_config


def test_plugin_lifecycle_stops_and_closes_idempotently(tmp_path: Path) -> None:
    services = only_default_engine_services()
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("plugin-lifecycle"), tmp_path), services=services)
    engine.add_cluster_from_file(
        only_write_migrated_cluster_config(
            "tests/fixtures/legacy_macd/cluster_external_plugins.yaml",
            tmp_path,
        )
    )
    result = engine.run()
    assert result.status == "COMPLETED"
    resources = engine.runtime_sessions[0].runtime.plugin_resource_snapshots
    assert {item.plugin_id for item in resources} == {"test-external-data", "test-external-broker"}
    assert all(item.state is OnlyPluginLifecycleState.STOPPED for item in resources)
    assert all(item.health.status is OnlyPluginHealthStatus.STOPPED for item in resources)
    engine.stop()
