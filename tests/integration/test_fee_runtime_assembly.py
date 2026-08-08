import json
from pathlib import Path

import pytest

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.config.document import OnlyClusterConfigError
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig


def _payload() -> dict[str, object]:
    config = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    return json.loads(json.dumps(dict(config.normalized_payload)))


SOURCE_PATH = Path("tests/fixtures/legacy_macd/cluster.json")


def test_old_combined_fee_schema_is_rejected() -> None:
    payload = _payload()
    payload["market"]["fees"] = {}  # type: ignore[index]

    with pytest.raises(OnlyClusterConfigError, match=r"UNKNOWN_FIELD: \$\.market\.fees"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)


def test_unknown_market_fee_pack_fails_runtime_build(tmp_path) -> None:
    payload = _payload()
    payload["market"]["fee_pack"] = {"pack_id": "UNKNOWN", "pack_version": "1"}  # type: ignore[index]
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("fee-unknown"), tmp_path))
    engine.add_cluster(config)

    result = engine.run()

    assert result.status == "FAILED"
    assert any("MARKET_FEE_PACK_NOT_INSTALLED" in failure for failure in result.failures)


def test_missing_broker_fee_contract_is_rejected_by_config_schema() -> None:
    payload = _payload()
    del payload["accounts"][0]["broker_fee_contract"]  # type: ignore[index]
    with pytest.raises(OnlyClusterConfigError, match=r"\$\.accounts\[0\]\.broker_fee_contract"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)


def test_unknown_broker_fee_contract_fails_runtime_build(tmp_path) -> None:
    payload = _payload()
    payload["accounts"][0]["broker_fee_contract"] = {  # type: ignore[index]
        "contract_id": "UNKNOWN",
        "contract_version": "1",
    }
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("broker-fee-unknown"), tmp_path))
    engine.add_cluster(config)
    result = engine.run()
    assert result.status == "FAILED"
    assert any("BROKER_FEE_CONTRACT_NOT_INSTALLED" in failure for failure in result.failures)


def test_broker_fee_contract_must_match_actual_broker_authority(tmp_path) -> None:
    payload = _payload()
    payload["accounts"][0]["broker_fee_contract"] = {  # type: ignore[index]
        "contract_id": "MINIQMT_SIMULATION_ZERO_BROKER_FEES",
        "contract_version": "1",
    }
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("broker-fee-incompatible"), tmp_path))
    engine.add_cluster(config)
    result = engine.run()
    assert result.status == "FAILED"
    assert any("BROKER_FEE_CONTRACT_BROKER_INCOMPATIBLE" in failure for failure in result.failures)
