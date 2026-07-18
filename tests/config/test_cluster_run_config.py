import json

import pytest

from onlyalpha.config import OnlyClusterRunConfig, OnlyRunConfigError

CONFIG = "tests/fixtures/legacy_macd/cluster.json"


def test_single_cluster_document_parses_to_typed_config() -> None:
    config = OnlyClusterRunConfig.load(CONFIG)
    assert str(config.cluster_id) == "macd-demo"
    assert config.runtime_type == "BACKTEST"
    assert config.cluster.strategy == config.strategy
    assert not hasattr(config, "run_config")


def test_single_cluster_document_rejects_legacy_clusters_array() -> None:
    with pytest.raises(OnlyRunConfigError, match="must use 'cluster'"):
        OnlyClusterRunConfig.from_mapping({"clusters": []})


def test_mapping_round_trip_preserves_config_facts() -> None:
    original = OnlyClusterRunConfig.load(CONFIG)
    payload = json.loads(json.dumps(dict(original.normalized_payload)))
    restored = OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)
    assert restored.cluster_id == original.cluster_id
    assert restored.runtime_id == original.runtime_id


def test_deprecated_type_normalizes_to_plugin_id_and_conflicts_with_plugin() -> None:
    original = OnlyClusterRunConfig.load(CONFIG)
    payload = json.loads(json.dumps(dict(original.normalized_payload)))
    payload["data_sources"][0]["type"] = payload["data_sources"][0].pop("plugin")
    payload["brokers"][0]["type"] = payload["brokers"][0].pop("plugin")
    with pytest.warns(DeprecationWarning, match="type is deprecated"):
        parsed = OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)
    assert parsed.data_sources[0].plugin_id == "synthetic"
    assert parsed.brokers[0].plugin_id == "virtual"
    payload["data_sources"][0]["plugin"] = "synthetic"
    with pytest.raises(OnlyRunConfigError, match="cannot define both plugin"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)
