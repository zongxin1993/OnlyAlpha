from onlyalpha.plugin.capabilities import (
    OnlyBrokerPluginCapabilities,
    OnlyCheckpointCapability,
    OnlyDataSourceCapabilities,
)
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginType
from onlyalpha.plugin.integration import (
    OnlyIntegrationCategory,
    OnlyIntegrationConfigurationContractV1,
    OnlyIntegrationConfigurationFieldV1,
    OnlyIntegrationTypeDescriptorV1,
    OnlyIntegrationTypeId,
    OnlyIntegrationValueKind,
    only_integration_capability_ids,
)
from onlyalpha.plugin.version import OnlyPluginApiVersion

from .config import OnlyMiniQmtConfig

PLUGIN_ID = "miniqmt"
VERSION = "0.1.0"
_DEFAULT_DATA_CONFIG = OnlyMiniQmtConfig()

DATA_CAPABILITIES = OnlyDataSourceCapabilities(
    historical_bars=True,
    live_bars=True,
    live_ticks=True,
    live_reconnect=True,
    instruments=True,
    calendars=True,
    supports_runtime_checkpoint=OnlyCheckpointCapability.STATELESS,
)
BROKER_CAPABILITIES = OnlyBrokerPluginCapabilities(
    submit_order=True,
    cancel_order=True,
    query_orders=True,
    query_trades=True,
    query_account=True,
    query_positions=True,
    live_execution=True,
)

DATA_DESCRIPTOR = OnlyPluginDescriptor(
    PLUGIN_ID,
    OnlyPluginType.DATA_SOURCE,
    VERSION,
    OnlyPluginApiVersion(1, 1),
    "MiniQMT",
    "OnlyAlpha",
    DATA_CAPABILITIES,
)
DATA_INTEGRATION_TYPE = OnlyIntegrationTypeDescriptorV1(
    type_id=OnlyIntegrationTypeId("miniqmt.market_data"),
    category=OnlyIntegrationCategory.DATA_SOURCE,
    display_name="MiniQMT Market Data",
    description="Local historical and realtime market data provided by the MiniQMT terminal.",
    provider_id="miniqmt",
    implementation_id=DATA_DESCRIPTOR.plugin_id,
    implementation_version=DATA_DESCRIPTOR.plugin_version,
    public_api_version=str(DATA_DESCRIPTOR.api_version),
    capabilities=only_integration_capability_ids(DATA_DESCRIPTOR.capabilities),
    configuration_contract=OnlyIntegrationConfigurationContractV1(
        fields=(
            OnlyIntegrationConfigurationFieldV1(
                "userdata_mini_path",
                OnlyIntegrationValueKind.PATH,
                False,
                default=str(_DEFAULT_DATA_CONFIG.userdata_mini_path),
                display_name="MiniQMT user data path",
            ),
            OnlyIntegrationConfigurationFieldV1(
                "account_id",
                OnlyIntegrationValueKind.STRING,
                False,
                default=_DEFAULT_DATA_CONFIG.account_id,
                display_name="Account ID",
            ),
            OnlyIntegrationConfigurationFieldV1(
                "reconnect_max_attempts",
                OnlyIntegrationValueKind.INTEGER,
                False,
                default=_DEFAULT_DATA_CONFIG.reconnect_max_attempts,
                advanced=True,
                display_name="Maximum reconnect attempts",
                minimum=0,
            ),
            OnlyIntegrationConfigurationFieldV1(
                "reconnect_initial_delay",
                OnlyIntegrationValueKind.DURATION,
                False,
                default=_DEFAULT_DATA_CONFIG.reconnect_initial_delay,
                advanced=True,
                display_name="Initial reconnect delay",
                minimum=0.0,
            ),
            OnlyIntegrationConfigurationFieldV1(
                "queue_capacity",
                OnlyIntegrationValueKind.INTEGER,
                False,
                default=_DEFAULT_DATA_CONFIG.queue_capacity,
                advanced=True,
                display_name="Queue capacity",
                minimum=1,
            ),
            OnlyIntegrationConfigurationFieldV1(
                "cache_policy",
                OnlyIntegrationValueKind.ENUM,
                False,
                default=_DEFAULT_DATA_CONFIG.cache_policy.value,
                advanced=True,
                display_name="Historical cache policy",
                enum_values=("cache_only", "prefer_cache", "force_refresh"),
            ),
        )
    ),
)
BROKER_DESCRIPTOR = OnlyPluginDescriptor(
    PLUGIN_ID,
    OnlyPluginType.BROKER,
    VERSION,
    OnlyPluginApiVersion(1, 1),
    "MiniQMT",
    "OnlyAlpha",
    BROKER_CAPABILITIES,
)
