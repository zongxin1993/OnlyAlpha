from onlyalpha.plugin.capabilities import OnlyCheckpointCapability, OnlyDataSourceCapabilities
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginType
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
    only_integration_capability_ids,
)
from onlyalpha.plugin.version import OnlyPluginApiVersion

DATA_CAPABILITIES = OnlyDataSourceCapabilities(
    historical_bars=True,
    instruments=True,
    calendars=True,
    supports_runtime_checkpoint=OnlyCheckpointCapability.STATELESS,
)
DATA_DESCRIPTOR = OnlyPluginDescriptor(
    "tushare",
    OnlyPluginType.DATA_SOURCE,
    "0.1.0",
    OnlyPluginApiVersion(1, 1),
    "Tushare",
    "OnlyAlpha",
    DATA_CAPABILITIES,
)

DATA_INTEGRATION_TYPE = OnlyIntegrationTypeDescriptorV1(
    type_id=OnlyIntegrationTypeId("tushare.daily.market_data"),
    category=OnlyIntegrationCategory.DATA_SOURCE,
    display_name="Tushare Daily Market Data",
    description="Authenticated daily historical market data from Tushare.",
    provider_id="tushare",
    implementation_id=DATA_DESCRIPTOR.plugin_id,
    implementation_version=DATA_DESCRIPTOR.plugin_version,
    public_api_version=str(DATA_DESCRIPTOR.api_version),
    capabilities=only_integration_capability_ids(DATA_DESCRIPTOR.capabilities),
    configuration_contract=OnlyIntegrationConfigurationContractV1(
        fields=(
            OnlyIntegrationConfigurationFieldV1(
                "token", OnlyIntegrationValueKind.STRING, True, secret=True, display_name="Token"
            ),
            OnlyIntegrationConfigurationFieldV1(
                "frequency",
                OnlyIntegrationValueKind.ENUM,
                False,
                default="1d",
                display_name="Frequency",
                enum_values=("1d",),
            ),
            OnlyIntegrationConfigurationFieldV1(
                "adjustment",
                OnlyIntegrationValueKind.ENUM,
                False,
                default="none",
                display_name="Price adjustment",
                enum_values=("none", "qfq", "hfq"),
            ),
            OnlyIntegrationConfigurationFieldV1(
                "cache_policy",
                OnlyIntegrationValueKind.ENUM,
                False,
                default="prefer_cache",
                advanced=True,
                display_name="Historical cache policy",
                enum_values=("cache_only", "prefer_cache", "force_refresh"),
            ),
            OnlyIntegrationConfigurationFieldV1(
                "strict_validation",
                OnlyIntegrationValueKind.BOOLEAN,
                False,
                default=True,
                advanced=True,
                display_name="Strict validation",
            ),
        )
    ),
    probe_contract=OnlyIntegrationProbeContractV1(
        probe_mode=OnlyIntegrationProbeMode.DEFAULT_INSTRUMENT,
        default_probe_instrument="000001.SZ",
        user_selectable_probe_instrument=True,
        probe_checks=(
            OnlyIntegrationProbeCheck.CONNECTIVITY,
            OnlyIntegrationProbeCheck.AUTHENTICATION,
            OnlyIntegrationProbeCheck.HISTORICAL_DATA,
        ),
    ),
)
