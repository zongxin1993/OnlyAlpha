from pathlib import Path

from onlyalpha_test_plugin.broker import OnlyExternalTestBrokerGateway
from onlyalpha_test_plugin.data_source import OnlyExternalTestDataSourceFactory, OnlyExternalTestHistoricalDataSource

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.plugin import OnlyPluginLifecycleState


def test_plugin_create_failure_is_structured_and_releases_engine_resources(tmp_path: Path, monkeypatch: object) -> None:
    def fail_create(self: OnlyExternalTestDataSourceFactory, request: object) -> object:
        del self, request
        raise RuntimeError("expected data create failure")

    monkeypatch.setattr(OnlyExternalTestDataSourceFactory, "create", fail_create)  # type: ignore[attr-defined]
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("plugin-create-rollback"), tmp_path))
    engine.add_cluster_from_file("tests/fixtures/legacy_macd/cluster_external_plugins.yaml")
    result = engine.run()
    assert result.status == "FAILED"
    assert "PLUGIN_CREATE_FAILED" in result.failures[0]
    assert "test-external-data" in result.failures[0]
    assert engine.snapshot().resource_reference_counts == ()


def test_plugin_connect_failure_closes_previously_initialized_resources(tmp_path: Path, monkeypatch: object) -> None:
    trace: list[str] = []
    source_close = OnlyExternalTestHistoricalDataSource.close

    def fail_connect(self: OnlyExternalTestBrokerGateway) -> object:
        del self
        raise RuntimeError("expected broker connect failure")

    def close_source(self: OnlyExternalTestHistoricalDataSource) -> None:
        trace.append("source.close")
        source_close(self)

    monkeypatch.setattr(OnlyExternalTestBrokerGateway, "connect", fail_connect)  # type: ignore[attr-defined]
    monkeypatch.setattr(OnlyExternalTestHistoricalDataSource, "close", close_source)  # type: ignore[attr-defined]
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("plugin-connect-rollback"), tmp_path))
    engine.add_cluster_from_file("tests/fixtures/legacy_macd/cluster_external_plugins.yaml")
    result = engine.run()
    assert result.status == "FAILED"
    assert "PLUGIN_INITIALIZATION_FAILED" in result.failures[0]
    assert "test-external-broker" in result.failures[0]
    assert trace and set(trace) == {"source.close"}


def test_plugin_start_failure_rolls_back_initialized_resources(tmp_path: Path, monkeypatch: object) -> None:
    def fail_start(self: OnlyExternalTestBrokerGateway) -> None:
        del self
        raise RuntimeError("expected broker start failure")

    monkeypatch.setattr(OnlyExternalTestBrokerGateway, "start", fail_start)  # type: ignore[attr-defined]
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("plugin-rollback"), tmp_path))
    engine.add_cluster_from_file("tests/fixtures/legacy_macd/cluster_external_plugins.yaml")
    result = engine.run()
    assert result.status == "FAILED"
    assert "test-external-broker" in result.failures[0]
    resources = engine.runtime_sessions[0].runtime.plugin_resource_snapshots
    assert all(item.state is OnlyPluginLifecycleState.STOPPED for item in resources)


def test_plugin_stop_failure_is_structured_and_does_not_skip_cleanup(tmp_path: Path, monkeypatch: object) -> None:
    trace: list[str] = []
    data_stop = OnlyExternalTestHistoricalDataSource.stop
    data_close = OnlyExternalTestHistoricalDataSource.close

    def fail_broker_stop(self: OnlyExternalTestBrokerGateway) -> None:
        del self
        trace.append("broker.stop")
        raise RuntimeError("expected broker stop failure")

    def close_broker(self: OnlyExternalTestBrokerGateway) -> None:
        del self
        trace.append("broker.close")

    def stop_data(self: OnlyExternalTestHistoricalDataSource) -> None:
        trace.append("data.stop")
        data_stop(self)

    def close_data(self: OnlyExternalTestHistoricalDataSource) -> None:
        trace.append("data.close")
        data_close(self)

    monkeypatch.setattr(OnlyExternalTestBrokerGateway, "stop", fail_broker_stop)  # type: ignore[attr-defined]
    monkeypatch.setattr(OnlyExternalTestBrokerGateway, "close", close_broker)  # type: ignore[attr-defined]
    monkeypatch.setattr(OnlyExternalTestHistoricalDataSource, "stop", stop_data)  # type: ignore[attr-defined]
    monkeypatch.setattr(OnlyExternalTestHistoricalDataSource, "close", close_data)  # type: ignore[attr-defined]
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("plugin-stop-rollback"), tmp_path))
    engine.add_cluster_from_file("tests/fixtures/legacy_macd/cluster_external_plugins.yaml")
    result = engine.run()
    assert result.status == "FAILED"
    assert "PLUGIN_STOP_FAILED" in result.failures[0]
    assert "test-external-broker" in result.failures[0]
    assert "external-test-broker" in result.failures[0]
    assert {"broker.stop", "data.stop", "broker.close", "data.close"} <= set(trace)
