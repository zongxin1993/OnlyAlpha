from pathlib import Path

from onlyalpha_test_plugin.broker import OnlyExternalTestBrokerGateway
from onlyalpha_test_plugin.data_source import OnlyExternalTestHistoricalDataSource

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig


def test_plugin_shutdown_order_is_broker_then_data_source(tmp_path: Path, monkeypatch: object) -> None:
    trace: list[str] = []
    broker_stop = OnlyExternalTestBrokerGateway.stop
    broker_close = OnlyExternalTestBrokerGateway.close
    data_stop = OnlyExternalTestHistoricalDataSource.stop
    data_close = OnlyExternalTestHistoricalDataSource.close

    def stop_broker(self: OnlyExternalTestBrokerGateway) -> None:
        trace.append("broker.stop")
        broker_stop(self)

    def close_broker(self: OnlyExternalTestBrokerGateway) -> None:
        trace.append("broker.close")
        broker_close(self)

    def stop_data(self: OnlyExternalTestHistoricalDataSource) -> None:
        trace.append("data.stop")
        data_stop(self)

    def close_data(self: OnlyExternalTestHistoricalDataSource) -> None:
        trace.append("data.close")
        data_close(self)

    monkeypatch.setattr(OnlyExternalTestBrokerGateway, "stop", stop_broker)  # type: ignore[attr-defined]
    monkeypatch.setattr(OnlyExternalTestBrokerGateway, "close", close_broker)  # type: ignore[attr-defined]
    monkeypatch.setattr(OnlyExternalTestHistoricalDataSource, "stop", stop_data)  # type: ignore[attr-defined]
    monkeypatch.setattr(OnlyExternalTestHistoricalDataSource, "close", close_data)  # type: ignore[attr-defined]
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("shutdown-order"), tmp_path))
    engine.add_cluster_from_file("tests/fixtures/legacy_macd/cluster_external_plugins.yaml")
    assert engine.run().status == "COMPLETED"
    assert trace.index("broker.stop") < trace.index("data.stop")
    assert trace.index("broker.close") < trace.index("data.close")
