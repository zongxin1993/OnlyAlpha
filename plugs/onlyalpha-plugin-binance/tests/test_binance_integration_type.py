import pytest
from onlyalpha_plugin_binance.spot.broker_factory import OnlyBinanceSpotBrokerFactory
from onlyalpha_plugin_binance.spot.data_source.factory import OnlyBinanceSpotDataSourceFactory

from onlyalpha.plugin.integration import OnlyIntegrationCategory, OnlyIntegrationValueKind


def test_spot_data_source_declares_configuration_without_runtime_instruments() -> None:
    descriptor = OnlyBinanceSpotDataSourceFactory().integration_type
    fields = {field.field_id: field for field in descriptor.configuration_contract.fields}

    assert descriptor.type_id.value == "binance.spot.market_data"
    assert descriptor.category is OnlyIntegrationCategory.DATA_SOURCE
    assert set(fields) == {
        "cache_policy",
        "environment",
        "max_response_bytes",
        "max_ws_message_bytes",
        "reconnect_initial_seconds",
        "reconnect_max_seconds",
        "recovery_buffer_max_events",
        "rest_page_size",
        "timeout_seconds",
    }
    assert not ({"symbols", "universe", "subscription_list", "instrument_allowlist"} & set(fields))
    assert descriptor.probe_contract is not None
    assert descriptor.probe_contract.default_probe_instrument == "BTCUSDT"
    assert "BTCUSDT" not in {str(field.default) for field in fields.values()}
    positive_fields = {
        fields[name] for name in ("timeout_seconds", "reconnect_initial_seconds", "reconnect_max_seconds")
    }
    assert all(field.minimum == 0.0 and field.exclusive_minimum for field in positive_fields)


def test_spot_broker_declares_semantic_secrets_while_runtime_parser_keeps_env_migration_path() -> None:
    factory = OnlyBinanceSpotBrokerFactory()
    fields = {field.field_id: field for field in factory.integration_type.configuration_contract.fields}

    assert factory.integration_type.type_id.value == "binance.spot.broker"
    assert fields["api_key"].secret is True and fields["api_key"].default is None
    assert fields["api_secret"].secret is True and fields["api_secret"].default is None
    assert fields["currencies"].required is True
    assert fields["currencies"].value_kind is OnlyIntegrationValueKind.STRING_INTEGER_MAP
    assert "api_key_env" not in fields and "api_secret_env" not in fields
    with pytest.raises(ValueError, match="unknown Binance Spot Broker extensions"):
        factory.parse_config({"api_key": "must-not-be-read", "api_secret": "must-not-be-read"})
