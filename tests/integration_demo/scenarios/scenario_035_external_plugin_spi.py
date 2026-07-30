from pathlib import Path
from tempfile import TemporaryDirectory

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig

from ..environment import OnlyIntegrationEnvironment, OnlyScenarioReport


def run(env: OnlyIntegrationEnvironment) -> OnlyScenarioReport:
    with TemporaryDirectory(prefix="onlyalpha-plugin-spi-") as directory:
        engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("plugin-spi"), Path(directory)))
        engine.add_cluster_from_file("tests/fixtures/legacy_macd/cluster_external_plugins.yaml")
        result = engine.run()
    assert result.status == "COMPLETED"
    assert result.cluster_results[0]["execution"] == {
        "order_count": 2,
        "rejected_order_count": 0,
        "trade_count": 2,
    }
    resources = engine.runtime_sessions[0].runtime.plugin_resource_snapshots
    assert [item.plugin_id for item in resources] == ["test-external-data", "test-external-broker"]
    return env.report_builder.scenario(
        "035",
        "外部 DataSource/Broker Plugin SPI",
        "Entry Point -> Registry -> Capability -> Lifecycle -> Queue -> ExecutionProcessor -> user_data",
    )
