from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig


def test_external_broker_updates_flow_through_execution_processor(tmp_path: Path) -> None:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("external-pipeline"), tmp_path))
    engine.add_cluster_from_file("tests/fixtures/legacy_macd/cluster_external_plugins.yaml")
    result = engine.run()
    assert result.status == "COMPLETED"
    projection = result.cluster_results[0]
    assert projection["execution"] == {"order_count": 2, "rejected_order_count": 0, "trade_count": 2}
    runtime = engine.runtime_sessions[0].runtime
    assert runtime.execution_audit_store.records()
    assert runtime.broker_results
