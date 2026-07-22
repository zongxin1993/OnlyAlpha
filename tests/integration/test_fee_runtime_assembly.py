import json
from decimal import Decimal
from pathlib import Path

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig


def _payload() -> dict[str, object]:
    config = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    return json.loads(json.dumps(dict(config.normalized_payload)))


SOURCE_PATH = Path("tests/fixtures/legacy_macd/cluster.json")


def test_market_fee_none_reaches_runtime_resolver(tmp_path) -> None:
    payload = _payload()
    payload["market"]["fees"] = {"mode": "NONE"}  # type: ignore[index]
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("fee-none"), tmp_path))
    engine.add_cluster(config)

    result = engine.run()

    assert result.status == "COMPLETED"
    performance = result.cluster_results[0]["runtime_performance"]
    assert Decimal(performance["fees"]["amount"]) == Decimal("0.00")
    assert Decimal(performance["final_equity"]["amount"]) == Decimal("1001910.00")


def test_unknown_broker_fee_schedule_fails_runtime_build(tmp_path) -> None:
    payload = _payload()
    payload["brokers"][0]["fees"] = {"mode": "MODEL", "schedule": "UNKNOWN"}  # type: ignore[index]
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("fee-unknown"), tmp_path))
    engine.add_cluster(config)

    result = engine.run()

    assert result.status == "FAILED"
    assert any("effective fee schedule for 'UNKNOWN'" in failure for failure in result.failures)
