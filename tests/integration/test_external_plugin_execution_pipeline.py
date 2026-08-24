from dataclasses import replace
from pathlib import Path

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from tests.runtime_runner import only_migrate_cluster_to_strategy


def test_external_broker_updates_flow_through_execution_processor(tmp_path: Path) -> None:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("external-pipeline"), tmp_path))
    config = only_migrate_cluster_to_strategy(
        OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster_external_plugins.yaml"), tmp_path
    )
    actions = (
        {
            "action_id": "BUY",
            "sequence": 10,
            "type": "SUBMIT_ORDER",
            "instrument_id": "TESTETF.XSHG",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": "100",
            "price": "10.00",
            "offset": "OPEN",
        },
        {
            "action_id": "SELL",
            "sequence": 20,
            "type": "SUBMIT_ORDER",
            "instrument_id": "TESTETF.XSHG",
            "side": "SELL",
            "order_type": "LIMIT",
            "quantity": "100",
            "price": "0.01",
            "offset": "CLOSE",
        },
    )
    engine.add_cluster(replace(config, cluster=replace(config.cluster, scenario_actions=actions)))  # type: ignore[arg-type]
    result = engine.run()
    assert result.status == "COMPLETED", "\n".join(result.failures)
    projection = result.cluster_results[0]
    assert projection["execution"] == {"order_count": 2, "rejected_order_count": 0, "trade_count": 2}
    runtime = engine.runtime_sessions[0].runtime
    assert runtime.execution_audit_store.records()
    assert runtime.broker_results
