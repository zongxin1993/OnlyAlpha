import json

import pytest

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.config.document import OnlyClusterConfigError


def test_cluster_document_round_trip_preserves_typed_configuration() -> None:
    config = OnlyClusterRunConfig.load("test-data/legacy_macd/cluster.json")
    restored = OnlyClusterRunConfig.from_mapping(
        json.loads(json.dumps(dict(config.normalized_payload))),
        source_path="test-data/legacy_macd/cluster.json",
    )
    assert restored.runtime == config.runtime
    assert restored.reference_data == config.reference_data
    assert restored.cluster == config.cluster
    assert restored.strategy.fingerprint == "a" * 64


@pytest.mark.parametrize("legacy_field", ("class_path", "config_path", "extensions"))
def test_legacy_strategy_configuration_is_rejected(legacy_field: str) -> None:
    baseline = OnlyClusterRunConfig.load("test-data/legacy_macd/cluster.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["strategy"][legacy_field] = "legacy"

    with pytest.raises(OnlyClusterConfigError, match="LEGACY_STRATEGY_CONFIGURATION_UNSUPPORTED"):
        OnlyClusterRunConfig.from_mapping(payload)


def test_common_parser_accepts_every_runtime_type_without_reading_extensions() -> None:
    baseline = OnlyClusterRunConfig.load("test-data/legacy_macd/cluster.json")
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
    baseline = OnlyClusterRunConfig.load("test-data/legacy_macd/cluster.json")
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
    baseline = OnlyClusterRunConfig.load("test-data/legacy_macd/cluster.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["type"] = legacy
    payload["cluster"]["runtime_type"] = legacy

    with pytest.raises(OnlyClusterConfigError, match="unsupported runtime.type"):
        OnlyClusterRunConfig.from_mapping(payload)


def test_data_source_integration_revision_mode_preserves_consumer_selection() -> None:
    baseline = OnlyClusterRunConfig.load("test-data/legacy_macd/cluster.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    source = payload["data_sources"][0]
    expected_coverage = source["coverage"]
    source.pop("plugin")
    source.pop("extensions", None)
    source["configuration_mode"] = "INTEGRATION_REVISION"
    source["integration"] = {
        "schema_version": 1,
        "integration_id": "b52eb762-34cf-47d4-8cca-56ef93f0d2ac",
        "revision_fingerprint": "a" * 64,
        "type_id": "test.market_data",
        "category": "DATA_SOURCE",
        "type_descriptor_fingerprint": "b" * 64,
        "runtime_configuration_fingerprint": "c" * 64,
        "runtime_generation_fingerprint": None,
        "identity_domain": "ONLYALPHA_INTEGRATION_RUNTIME_BINDING_V1",
        "binding_fingerprint": "d" * 64,
    }

    parsed = OnlyClusterRunConfig.from_mapping(payload)
    configured = parsed.data_sources[0]

    assert configured.plugin_id == ""
    assert configured.configuration_mode.value == "INTEGRATION_REVISION"
    assert dict(configured.integration_binding or {}) == source["integration"]
    assert configured.coverage.universe_ids == tuple(expected_coverage["universe_ids"])


@pytest.mark.parametrize(
    "conflict",
    (
        {"plugin": "synthetic"},
        {"extensions": {"token": "legacy"}},
    ),
)
def test_data_source_configuration_modes_never_merge(conflict: dict[str, object]) -> None:
    baseline = OnlyClusterRunConfig.load("test-data/legacy_macd/cluster.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    source = payload["data_sources"][0]
    source.pop("plugin")
    source["configuration_mode"] = "INTEGRATION_REVISION"
    source["integration"] = {"binding": "placeholder"}
    source.update(conflict)

    with pytest.raises(OnlyClusterConfigError, match="RUNTIME_CONFIGURATION_MODE_CONFLICT"):
        OnlyClusterRunConfig.from_mapping(payload)


@pytest.mark.parametrize("nested", (False, True))
def test_data_source_integration_mode_rejects_provider_fields_outside_binding(nested: bool) -> None:
    baseline = OnlyClusterRunConfig.load("test-data/legacy_macd/cluster.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    source = payload["data_sources"][0]
    source.pop("plugin")
    source.pop("extensions", None)
    source["configuration_mode"] = "INTEGRATION_REVISION"
    source["integration"] = {
        "integration_id": "b52eb762-34cf-47d4-8cca-56ef93f0d2ac",
        "revision_fingerprint": "a" * 64,
    }
    target = source["integration"] if nested else source
    target["token"] = "PLAINTEXT-SENTINEL"

    with pytest.raises(OnlyClusterConfigError, match="UNKNOWN_FIELD: token|INTEGRATION_RUNTIME_BINDING_INVALID"):
        OnlyClusterRunConfig.from_mapping(payload)


def test_broker_integration_revision_mode_is_exact_and_never_merges_legacy_fields() -> None:
    baseline = OnlyClusterRunConfig.load("test-data/legacy_macd/cluster.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    broker = payload["brokers"][0]
    broker.pop("plugin")
    broker.pop("extensions", None)
    broker["configuration_mode"] = "INTEGRATION_REVISION"
    broker["integration"] = {
        "integration_id": "b52eb762-34cf-47d4-8cca-56ef93f0d2ac",
        "revision_fingerprint": "a" * 64,
    }

    configured = OnlyClusterRunConfig.from_mapping(payload).brokers[0]

    assert configured.plugin_id == ""
    assert configured.configuration_mode.value == "INTEGRATION_REVISION"
    assert dict(configured.integration_binding or {}) == broker["integration"]

    broker["extensions"] = {"api_key_env": "LEGACY"}
    with pytest.raises(OnlyClusterConfigError, match="RUNTIME_CONFIGURATION_MODE_CONFLICT"):
        OnlyClusterRunConfig.from_mapping(payload)


@pytest.mark.parametrize("nested", (False, True))
def test_broker_integration_mode_rejects_plaintext_credentials(nested: bool) -> None:
    baseline = OnlyClusterRunConfig.load("test-data/legacy_macd/cluster.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    broker = payload["brokers"][0]
    broker.pop("plugin")
    broker.pop("extensions", None)
    broker["configuration_mode"] = "INTEGRATION_REVISION"
    broker["integration"] = {
        "integration_id": "b52eb762-34cf-47d4-8cca-56ef93f0d2ac",
        "revision_fingerprint": "a" * 64,
    }
    target = broker["integration"] if nested else broker
    target["api_secret"] = "PLAINTEXT-SENTINEL"

    with pytest.raises(OnlyClusterConfigError, match="UNKNOWN_FIELD: api_secret|INTEGRATION_RUNTIME_BINDING_INVALID"):
        OnlyClusterRunConfig.from_mapping(payload)
