import json
from copy import deepcopy

import pytest

from onlyalpha.config import OnlyClusterConfigError, OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.runtime.planning import OnlyRuntimePlanner

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


def _capital_config(cluster_id: str, capital: dict[str, object] | None) -> OnlyClusterRunConfig:
    payload = deepcopy(dict(OnlyClusterRunConfig.load(CONFIG).normalized_payload))
    payload["cluster"]["cluster_id"] = cluster_id
    if capital is None:
        payload["cluster"].pop("capital", None)
    else:
        payload["cluster"]["capital"] = capital
    return OnlyClusterRunConfig.from_mapping(payload, source_path=f"{cluster_id}.json")


def _plan(*configs: OnlyClusterRunConfig) -> None:
    OnlyRuntimePlanner().plan(OnlyEngineId("capital-test"), configs)


def test_single_cluster_capital_defaults_to_account_and_explicit_must_match() -> None:
    _plan(_capital_config("single-default", None))
    _plan(
        _capital_config(
            "single-explicit",
            {"mode": "FIXED_CAPITAL", "amount": "1000000.00", "currency": "CNY"},
        )
    )
    with pytest.raises(OnlyClusterConfigError, match="single-Cluster capital"):
        _plan(
            _capital_config(
                "single-invalid",
                {"mode": "FIXED_CAPITAL", "amount": "999999.99", "currency": "CNY"},
            )
        )


def test_multi_cluster_capital_requires_exact_explicit_fixed_allocation() -> None:
    first = _capital_config(
        "capital-a",
        {"mode": "FIXED_CAPITAL", "amount": "400000.00", "currency": "CNY"},
    )
    second = _capital_config(
        "capital-b",
        {"mode": "FIXED_CAPITAL", "amount": "600000.00", "currency": "CNY"},
    )
    _plan(first, second)
    with pytest.raises(OnlyClusterConfigError, match="requires explicit"):
        _plan(first, _capital_config("capital-b", None))
    for amount in ("599999.99", "600000.01"):
        with pytest.raises(OnlyClusterConfigError, match="total must equal"):
            _plan(
                first,
                _capital_config(
                    "capital-b",
                    {"mode": "FIXED_CAPITAL", "amount": amount, "currency": "CNY"},
                ),
            )
    with pytest.raises(OnlyClusterConfigError, match="currency"):
        _plan(
            first,
            _capital_config(
                "capital-b",
                {"mode": "FIXED_CAPITAL", "amount": "600000.00", "currency": "USD"},
            ),
        )


def test_cluster_capital_rejects_legacy_non_fixed_and_negative_but_allows_zero() -> None:
    with pytest.raises(OnlyClusterConfigError, match="only FIXED_CAPITAL"):
        _capital_config(
            "invalid-mode",
            {"mode": "SHARED_POOL", "amount": "1000000.00", "currency": "CNY"},
        )
    with pytest.raises(OnlyClusterConfigError, match=">= 0"):
        _capital_config(
            "negative",
            {"mode": "FIXED_CAPITAL", "amount": "-1.00", "currency": "CNY"},
        )
    _plan(
        _capital_config(
            "zero",
            {"mode": "FIXED_CAPITAL", "amount": "0.00", "currency": "CNY"},
        ),
        _capital_config(
            "all-capital",
            {"mode": "FIXED_CAPITAL", "amount": "1000000.00", "currency": "CNY"},
        ),
    )


def test_legacy_strategy_initial_capital_is_rejected() -> None:
    payload = deepcopy(dict(OnlyClusterRunConfig.load(CONFIG).normalized_payload))
    payload["cluster"]["strategy_initial_capital"] = "1000000.00"
    with pytest.raises(OnlyClusterConfigError, match="UNKNOWN_FIELD: strategy_initial_capital"):
        OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)
