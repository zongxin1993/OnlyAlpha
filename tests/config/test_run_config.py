import json

import pytest

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.config.document import OnlyClusterConfigError


def test_cluster_document_round_trip_preserves_typed_configuration() -> None:
    config = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    restored = OnlyClusterRunConfig.from_mapping(
        json.loads(json.dumps(dict(config.normalized_payload))),
        source_path="tests/fixtures/legacy_macd/cluster.json",
    )
    assert restored.runtime == config.runtime
    assert restored.reference_data == config.reference_data
    assert restored.cluster == config.cluster


def test_common_parser_accepts_every_runtime_type_without_reading_extensions() -> None:
    baseline = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    for runtime_type in ("RESEARCH", "BACKTEST", "SIM", "LIVE"):
        payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
        payload["runtime"]["type"] = runtime_type
        payload["cluster"]["runtime_type"] = runtime_type
        payload["runtime"]["start_time"] = None
        payload["runtime"]["end_time"] = None
        payload["runtime"]["extensions"] = {"unknown_future_extension": {"kept": True}}
        parsed = OnlyClusterRunConfig.from_mapping(payload)
        assert parsed.runtime.runtime_type == runtime_type
        assert parsed.runtime.extensions["unknown_future_extension"] == {"kept": True}


def test_sim_runtime_spelling_is_canonicalized_without_aliases() -> None:
    baseline = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["type"] = "sim"
    payload["cluster"]["runtime_type"] = "sim"

    parsed = OnlyClusterRunConfig.from_mapping(payload)

    assert parsed.runtime.runtime_type == "SIM"

    for alias in ("SIMULATION", "PAPER_SIM", "PAPER_TRADING", "VIRTUAL", "VIRTUAL_TRADING"):
        payload["runtime"]["type"] = alias
        payload["cluster"]["runtime_type"] = alias
        with pytest.raises(OnlyClusterConfigError, match="unsupported runtime.type"):
            OnlyClusterRunConfig.from_mapping(payload)


@pytest.mark.parametrize("legacy", ("PAPER", "SHADOW"))
def test_legacy_runtime_products_are_rejected_without_aliases(legacy: str) -> None:
    baseline = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["type"] = legacy
    payload["cluster"]["runtime_type"] = legacy

    with pytest.raises(OnlyClusterConfigError, match="unsupported runtime.type"):
        OnlyClusterRunConfig.from_mapping(payload)
