import json

import pytest

from onlyalpha.config import OnlyClusterConfigError, OnlyClusterRunConfig

CONFIG = "tests/fixtures/legacy_macd/cluster.json"


def test_single_cluster_document_parses_to_typed_config() -> None:
    config = OnlyClusterRunConfig.load(CONFIG)
    assert str(config.cluster_id) == "macd-demo"
    assert config.runtime_type == "BACKTEST"
    assert config.cluster.strategy == config.strategy
    assert not hasattr(config, "run_config")


def test_single_cluster_document_rejects_legacy_clusters_array() -> None:
    with pytest.raises(OnlyClusterConfigError, match="must use 'cluster'"):
        OnlyClusterRunConfig.from_mapping({"clusters": []})


def test_mapping_round_trip_preserves_config_facts() -> None:
    original = OnlyClusterRunConfig.load(CONFIG)
    payload = json.loads(json.dumps(dict(original.normalized_payload)))
    restored = OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)
    assert restored.cluster_id == original.cluster_id
    assert restored.runtime_id == original.runtime_id


def test_data_source_and_broker_type_aliases_are_rejected() -> None:
    original = OnlyClusterRunConfig.load(CONFIG)
    payload = json.loads(json.dumps(dict(original.normalized_payload)))
    payload["data_sources"][0]["type"] = payload["data_sources"][0].pop("plugin")
    payload["brokers"][0]["type"] = payload["brokers"][0].pop("plugin")
    with pytest.raises(OnlyClusterConfigError, match="UNKNOWN_FIELD: type"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)


@pytest.mark.parametrize("section", ["data_sources", "brokers"])
def test_plugin_and_legacy_type_conflict_fails_clearly(section: str) -> None:
    original = OnlyClusterRunConfig.load(CONFIG)
    payload = json.loads(json.dumps(dict(original.normalized_payload)))
    payload[section][0]["type"] = payload[section][0]["plugin"]
    with pytest.raises(OnlyClusterConfigError, match=rf"\$\.{section}\[0\] UNKNOWN_FIELD: type"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)


def test_plugin_field_is_required() -> None:
    original = OnlyClusterRunConfig.load(CONFIG)
    payload = json.loads(json.dumps(dict(original.normalized_payload)))
    payload["data_sources"][0].pop("plugin")
    with pytest.raises(OnlyClusterConfigError, match="plugin is required"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)


def test_market_is_required_and_legacy_market_simulation_is_rejected() -> None:
    original = OnlyClusterRunConfig.load(CONFIG)
    payload = json.loads(json.dumps(dict(original.normalized_payload)))
    payload.pop("market")
    with pytest.raises(OnlyClusterConfigError, match=r"\$\.market"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)
    payload["market_simulation"] = {"profile": "GENERIC_T0_CASH"}
    with pytest.raises(OnlyClusterConfigError, match="market_simulation"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)


def test_market_override_decimal_values_must_be_quoted() -> None:
    original = OnlyClusterRunConfig.load(CONFIG)
    payload = json.loads(json.dumps(dict(original.normalized_payload)))
    payload["market"]["overrides"] = {"liquidity": {"maximum_participation_rate": 0.1}}
    with pytest.raises(ValueError, match="quoted Decimal string"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)
