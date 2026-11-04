"""Shared declared Integration inputs for persistence and native conformance."""

from __future__ import annotations

from onlyalpha.plugin.integration import (
    OnlyIntegrationCategory,
    OnlyIntegrationConfigurationContractV1,
    OnlyIntegrationConfigurationFieldV1,
    OnlyIntegrationProbeCheck,
    OnlyIntegrationProbeContractV1,
    OnlyIntegrationProbeMode,
    OnlyIntegrationTypeDescriptorV1,
    OnlyIntegrationTypeId,
    OnlyIntegrationValueKind,
)


def integration_descriptor(*, version: str = "1.0.0") -> OnlyIntegrationTypeDescriptorV1:
    return OnlyIntegrationTypeDescriptorV1(
        type_id=OnlyIntegrationTypeId("binance.spot.market_data"),
        category=OnlyIntegrationCategory.DATA_SOURCE,
        display_name="Binance Spot",
        description="Binance Spot market data",
        provider_id="binance",
        implementation_id="binance",
        implementation_version=version,
        public_api_version="1.1",
        capabilities=("HISTORICAL_BARS",),
        configuration_contract=OnlyIntegrationConfigurationContractV1(
            fields=(
                OnlyIntegrationConfigurationFieldV1(
                    "api_key",
                    OnlyIntegrationValueKind.STRING,
                    required=True,
                    secret=True,
                    display_name="API key",
                ),
                OnlyIntegrationConfigurationFieldV1(
                    "name",
                    OnlyIntegrationValueKind.STRING,
                    required=True,
                    display_name="Name",
                ),
                OnlyIntegrationConfigurationFieldV1(
                    "timeout_seconds",
                    OnlyIntegrationValueKind.DURATION,
                    required=False,
                    default=10.0,
                    minimum=0.1,
                    display_name="Timeout",
                ),
            )
        ),
        probe_contract=OnlyIntegrationProbeContractV1(
            OnlyIntegrationProbeMode.DEFAULT_INSTRUMENT,
            "BTCUSDT",
            True,
            (OnlyIntegrationProbeCheck.REFERENCE_DATA,),
        ),
    )
