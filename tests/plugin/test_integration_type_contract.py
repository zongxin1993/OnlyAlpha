from dataclasses import replace

import pytest

from onlyalpha.plugin.integration import (
    OnlyIntegrationCategory,
    OnlyIntegrationConfigurationContractV1,
    OnlyIntegrationConfigurationFieldV1,
    OnlyIntegrationProbeCheck,
    OnlyIntegrationProbeContractV1,
    OnlyIntegrationProbeMode,
    OnlyIntegrationTypeDescriptorV1,
    OnlyIntegrationTypeId,
    OnlyIntegrationTypeProvider,
    OnlyIntegrationValueKind,
)


def _configuration() -> OnlyIntegrationConfigurationContractV1:
    return OnlyIntegrationConfigurationContractV1(
        fields=(
            OnlyIntegrationConfigurationFieldV1(
                "timeout_seconds",
                OnlyIntegrationValueKind.DURATION,
                required=False,
                default=10.0,
                display_name="Timeout",
                minimum=0.1,
                maximum=30.0,
            ),
            OnlyIntegrationConfigurationFieldV1(
                "environment",
                OnlyIntegrationValueKind.ENUM,
                required=True,
                default="LIVE",
                display_name="Environment",
                enum_values=("SPOT_TESTNET", "LIVE"),
            ),
            OnlyIntegrationConfigurationFieldV1(
                "api_key",
                OnlyIntegrationValueKind.STRING,
                required=True,
                secret=True,
                display_name="API key",
            ),
        )
    )


def _descriptor(configuration: OnlyIntegrationConfigurationContractV1) -> OnlyIntegrationTypeDescriptorV1:
    return OnlyIntegrationTypeDescriptorV1(
        type_id=OnlyIntegrationTypeId("binance.spot.market_data"),
        category=OnlyIntegrationCategory.DATA_SOURCE,
        display_name="Binance Spot Market Data",
        description="Binance Spot market-data access.",
        provider_id="binance",
        implementation_id="binance",
        implementation_version="1.0.0",
        public_api_version="1.1",
        capabilities=("LIVE_TICKS", "HISTORICAL_BARS"),
        configuration_contract=configuration,
        probe_contract=OnlyIntegrationProbeContractV1(
            probe_mode=OnlyIntegrationProbeMode.DEFAULT_INSTRUMENT,
            default_probe_instrument="BTCUSDT",
            user_selectable_probe_instrument=True,
            probe_checks=(
                OnlyIntegrationProbeCheck.REALTIME_DATA,
                OnlyIntegrationProbeCheck.REFERENCE_DATA,
            ),
        ),
    )


def test_contract_canonicalizes_fields_enums_capabilities_and_probe_checks() -> None:
    descriptor = _descriptor(_configuration())

    assert tuple(field.field_id for field in descriptor.configuration_contract.fields) == (
        "api_key",
        "environment",
        "timeout_seconds",
    )
    assert descriptor.configuration_contract.fields[1].enum_values == ("LIVE", "SPOT_TESTNET")
    assert descriptor.capabilities == ("HISTORICAL_BARS", "LIVE_TICKS")
    assert descriptor.probe_contract is not None
    assert descriptor.probe_contract.probe_checks == (
        OnlyIntegrationProbeCheck.REALTIME_DATA,
        OnlyIntegrationProbeCheck.REFERENCE_DATA,
    )


def test_contract_fingerprints_are_stable_and_change_with_semantics() -> None:
    first = _descriptor(_configuration())
    second = _descriptor(_configuration())
    changed_configuration = OnlyIntegrationConfigurationContractV1(
        fields=tuple(
            replace(field, maximum=60.0) if field.field_id == "timeout_seconds" else field
            for field in _configuration().fields
        )
    )
    changed = _descriptor(changed_configuration)

    assert first.configuration_contract.fingerprint == second.configuration_contract.fingerprint
    assert first.probe_contract is not None and second.probe_contract is not None
    assert first.probe_contract.fingerprint == second.probe_contract.fingerprint
    assert first.fingerprint == second.fingerprint
    assert changed.configuration_contract.fingerprint != first.configuration_contract.fingerprint
    assert changed.fingerprint != first.fingerprint


def test_configuration_contract_rejects_duplicate_fields_and_invalid_defaults() -> None:
    field = OnlyIntegrationConfigurationFieldV1(
        "enabled",
        OnlyIntegrationValueKind.BOOLEAN,
        required=False,
        default=True,
        display_name="Enabled",
    )
    with pytest.raises(ValueError, match="INTEGRATION_CONFIGURATION_CONTRACT_INVALID"):
        OnlyIntegrationConfigurationContractV1(fields=(field, field))
    with pytest.raises(ValueError, match="INTEGRATION_CONFIGURATION_CONTRACT_INVALID"):
        replace(field, default="true")
    with pytest.raises(ValueError, match="INTEGRATION_CONFIGURATION_CONTRACT_INVALID"):
        OnlyIntegrationConfigurationFieldV1(
            "token",
            OnlyIntegrationValueKind.STRING,
            required=True,
            default="plaintext",
            secret=True,
            display_name="Token",
        )


@pytest.mark.parametrize(
    "value",
    ("Binance.spot", "binance/latest", "binance-latest", "binance_latest", "latest", "binance..spot", ""),
)
def test_integration_type_id_rejects_noncanonical_or_latest_identifiers(value: str) -> None:
    with pytest.raises(ValueError, match="INTEGRATION_TYPE_CONTRACT_INVALID"):
        OnlyIntegrationTypeId(value)


def test_probe_contract_rejects_runtime_ambiguous_metadata() -> None:
    with pytest.raises(ValueError, match="INTEGRATION_PROBE_CONTRACT_INVALID"):
        OnlyIntegrationProbeContractV1(
            probe_mode=OnlyIntegrationProbeMode.DEFAULT_INSTRUMENT,
            default_probe_instrument=None,
            user_selectable_probe_instrument=False,
            probe_checks=(OnlyIntegrationProbeCheck.REFERENCE_DATA,),
        )


def test_integration_type_provider_is_an_explicit_optional_spi() -> None:
    class Declared:
        integration_type = _descriptor(_configuration())

    class Legacy:
        pass

    assert isinstance(Declared(), OnlyIntegrationTypeProvider)
    assert not isinstance(Legacy(), OnlyIntegrationTypeProvider)


def test_configuration_contract_rejects_invalid_map_defaults_and_exclusive_bounds() -> None:
    with pytest.raises(ValueError, match="INTEGRATION_CONFIGURATION_CONTRACT_INVALID"):
        OnlyIntegrationConfigurationFieldV1(
            "currencies",
            OnlyIntegrationValueKind.STRING_INTEGER_MAP,
            required=False,
            default=1,
            display_name="Currencies",
        )
    with pytest.raises(ValueError, match="INTEGRATION_CONFIGURATION_CONTRACT_INVALID"):
        OnlyIntegrationConfigurationFieldV1(
            "timeout_seconds",
            OnlyIntegrationValueKind.DURATION,
            required=False,
            default=0.0,
            display_name="Timeout",
            minimum=0.0,
            exclusive_minimum=True,
        )
