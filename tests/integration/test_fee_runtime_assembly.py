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


def test_missing_fee_pack_is_rejected_by_config_schema() -> None:
    payload = _payload()
    payload["market"]["fees"] = {}  # type: ignore[index]

    with pytest.raises(OnlyClusterConfigError, match=r"\$\.market\.fees\.pack_id"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)


def test_unknown_fee_policy_pack_fails_runtime_build(tmp_path) -> None:
    payload = _payload()
    payload["market"]["fees"] = {"pack_id": "UNKNOWN", "pack_version": "1"}  # type: ignore[index]
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=SOURCE_PATH)
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("fee-unknown"), tmp_path))
    engine.add_cluster(config)

    result = engine.run()

    assert result.status == "FAILED"
    assert any("FEE_PACK_NOT_INSTALLED" in failure for failure in result.failures)
