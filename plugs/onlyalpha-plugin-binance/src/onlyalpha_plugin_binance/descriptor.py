from dataclasses import dataclass

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
    historical_ticks=True,
    live_bars=True,
    live_ticks=True,
    live_reconnect=True,
    instruments=True,
    calendars=True,
    supports_runtime_checkpoint=OnlyCheckpointCapability.STATELESS,
)
DATA_DESCRIPTOR = OnlyPluginDescriptor(
    "binance",
    OnlyPluginType.DATA_SOURCE,
    "0.9.2",
    OnlyPluginApiVersion(1, 1),
    "Binance Spot Public Data",
    "OnlyAlpha",
    DATA_CAPABILITIES,
)
USDM_DATA_CAPABILITIES = OnlyDataSourceCapabilities(
    historical_bars=True,
    historical_reference_prices=True,
    historical_funding_rates=True,
    instruments=True,
    calendars=True,
    supports_runtime_checkpoint=OnlyCheckpointCapability.STATELESS,
)
USDM_DATA_DESCRIPTOR = OnlyPluginDescriptor(
    "binance-usdm",
    OnlyPluginType.DATA_SOURCE,
    "0.9.8",
    OnlyPluginApiVersion(1, 1),
    "Binance USD-M Public Historical Data",
    "Binance",
    USDM_DATA_CAPABILITIES,
)
BROKER_DESCRIPTOR = OnlyPluginDescriptor(
    "binance-spot",
    OnlyPluginType.BROKER,
    "0.9.8",
    OnlyPluginApiVersion(1, 1),
    "Binance Spot Broker",
    "Binance",
    OnlyBrokerPluginCapabilities(
        submit_order=True,
        cancel_order=True,
        query_orders=True,
        query_trades=True,
        query_positions=True,
        query_fee_evidence=True,
        live_execution=True,
        supports_runtime_checkpoint=OnlyCheckpointCapability.STATELESS,
    ),
)

SPOT_DATA_INTEGRATION_TYPE = OnlyIntegrationTypeDescriptorV1(
    type_id=OnlyIntegrationTypeId("binance.spot.market_data"),
    category=OnlyIntegrationCategory.DATA_SOURCE,
    display_name="Binance Spot Market Data",
    description="Public historical, realtime, reference, and calendar data for Binance Spot.",
    provider_id="binance",
    implementation_id=DATA_DESCRIPTOR.plugin_id,
    implementation_version=DATA_DESCRIPTOR.plugin_version,
    public_api_version=str(DATA_DESCRIPTOR.api_version),
    capabilities=only_integration_capability_ids(DATA_DESCRIPTOR.capabilities),
    configuration_contract=OnlyIntegrationConfigurationContractV1(
        fields=(
            OnlyIntegrationConfigurationFieldV1(
                "environment",
                OnlyIntegrationValueKind.ENUM,
                False,
                default="LIVE",
                display_name="Environment",
                enum_values=("LIVE", "SPOT_TESTNET"),
            ),
            OnlyIntegrationConfigurationFieldV1(
                "timeout_seconds",
                OnlyIntegrationValueKind.DURATION,
                False,
                default=10.0,
                advanced=True,
                display_name="Request timeout",
                minimum=0.0,
                maximum=30.0,
                exclusive_minimum=True,
            ),
            OnlyIntegrationConfigurationFieldV1(
                "max_response_bytes",
                OnlyIntegrationValueKind.INTEGER,
                False,
                default=8 * 1024 * 1024,
                advanced=True,
                display_name="Maximum response bytes",
                minimum=1,
            ),
            OnlyIntegrationConfigurationFieldV1(
                "max_ws_message_bytes",
                OnlyIntegrationValueKind.INTEGER,
                False,
                default=1024 * 1024,
                advanced=True,
                display_name="Maximum WebSocket message bytes",
                minimum=1,
            ),
            OnlyIntegrationConfigurationFieldV1(
                "reconnect_initial_seconds",
                OnlyIntegrationValueKind.DURATION,
                False,
                default=0.5,
                advanced=True,
                display_name="Initial reconnect delay",
                minimum=0.0,
                maximum=300.0,
                exclusive_minimum=True,
            ),
            OnlyIntegrationConfigurationFieldV1(
                "reconnect_max_seconds",
                OnlyIntegrationValueKind.DURATION,
                False,
                default=30.0,
                advanced=True,
                display_name="Maximum reconnect delay",
                minimum=0.0,
                maximum=300.0,
                exclusive_minimum=True,
            ),
            OnlyIntegrationConfigurationFieldV1(
                "recovery_buffer_max_events",
                OnlyIntegrationValueKind.INTEGER,
                False,
                default=100_000,
                advanced=True,
                display_name="Recovery buffer events",
                minimum=1,
            ),
            OnlyIntegrationConfigurationFieldV1(
                "rest_page_size",
                OnlyIntegrationValueKind.INTEGER,
                False,
                default=1000,
                advanced=True,
                display_name="REST page size",
                minimum=1,
                maximum=1000,
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
        )
    ),
    probe_contract=OnlyIntegrationProbeContractV1(
        probe_mode=OnlyIntegrationProbeMode.DEFAULT_INSTRUMENT,
        default_probe_instrument="BTCUSDT",
        user_selectable_probe_instrument=True,
        probe_checks=(
            OnlyIntegrationProbeCheck.CONNECTIVITY,
            OnlyIntegrationProbeCheck.REFERENCE_DATA,
            OnlyIntegrationProbeCheck.HISTORICAL_DATA,
            OnlyIntegrationProbeCheck.REALTIME_DATA,
        ),
    ),
)

USDM_DATA_INTEGRATION_TYPE = OnlyIntegrationTypeDescriptorV1(
    type_id=OnlyIntegrationTypeId("binance.usdm.market_data"),
    category=OnlyIntegrationCategory.DATA_SOURCE,
    display_name="Binance USD-M Market Data",
    description="Public historical market and reference data for Binance USD-M Futures.",
    provider_id="binance",
    implementation_id=USDM_DATA_DESCRIPTOR.plugin_id,
    implementation_version=USDM_DATA_DESCRIPTOR.plugin_version,
    public_api_version=str(USDM_DATA_DESCRIPTOR.api_version),
    capabilities=only_integration_capability_ids(USDM_DATA_DESCRIPTOR.capabilities),
    configuration_contract=OnlyIntegrationConfigurationContractV1(
        fields=(
            OnlyIntegrationConfigurationFieldV1(
                "rest_base_url",
                OnlyIntegrationValueKind.STRING,
                False,
                default="https://fapi.binance.com",
                advanced=True,
                display_name="REST base URL",
            ),
            OnlyIntegrationConfigurationFieldV1(
                "timeout_seconds",
                OnlyIntegrationValueKind.DURATION,
                False,
                default=10.0,
                advanced=True,
                display_name="Request timeout",
                minimum=0.0,
                maximum=30.0,
                exclusive_minimum=True,
            ),
            OnlyIntegrationConfigurationFieldV1(
                "max_response_bytes",
                OnlyIntegrationValueKind.INTEGER,
                False,
                default=8 * 1024 * 1024,
                advanced=True,
                display_name="Maximum response bytes",
                minimum=1,
            ),
            OnlyIntegrationConfigurationFieldV1(
                "rest_page_size",
                OnlyIntegrationValueKind.INTEGER,
                False,
                default=1000,
                advanced=True,
                display_name="REST page size",
                minimum=1,
                maximum=1500,
            ),
        )
    ),
)

SPOT_BROKER_INTEGRATION_TYPE = OnlyIntegrationTypeDescriptorV1(
    type_id=OnlyIntegrationTypeId("binance.spot.broker"),
    category=OnlyIntegrationCategory.BROKER,
    display_name="Binance Spot Broker",
    description="Authenticated order execution and account observation for Binance Spot.",
    provider_id="binance",
    implementation_id=BROKER_DESCRIPTOR.plugin_id,
    implementation_version=BROKER_DESCRIPTOR.plugin_version,
    public_api_version=str(BROKER_DESCRIPTOR.api_version),
    capabilities=only_integration_capability_ids(BROKER_DESCRIPTOR.capabilities),
    configuration_contract=OnlyIntegrationConfigurationContractV1(
        fields=(
            OnlyIntegrationConfigurationFieldV1(
                "environment",
                OnlyIntegrationValueKind.ENUM,
                False,
                default="SPOT_TESTNET",
                display_name="Environment",
                enum_values=("LIVE", "SPOT_TESTNET"),
            ),
            OnlyIntegrationConfigurationFieldV1(
                "api_key", OnlyIntegrationValueKind.STRING, True, secret=True, display_name="API key"
            ),
            OnlyIntegrationConfigurationFieldV1(
                "api_secret", OnlyIntegrationValueKind.STRING, True, secret=True, display_name="API secret"
            ),
            OnlyIntegrationConfigurationFieldV1(
                "currencies",
                OnlyIntegrationValueKind.STRING_INTEGER_MAP,
                True,
                advanced=True,
                display_name="Currency precisions",
                description="Currency code to decimal precision mapping required by the runtime parser.",
            ),
            OnlyIntegrationConfigurationFieldV1(
                "rest_base_url",
                OnlyIntegrationValueKind.STRING,
                False,
                advanced=True,
                display_name="REST base URL",
            ),
            OnlyIntegrationConfigurationFieldV1(
                "websocket_api_base_url",
                OnlyIntegrationValueKind.STRING,
                False,
                advanced=True,
                display_name="WebSocket API base URL",
            ),
            OnlyIntegrationConfigurationFieldV1(
                "recv_window_ms",
                OnlyIntegrationValueKind.INTEGER,
                False,
                default=5_000,
                advanced=True,
                display_name="Receive window milliseconds",
                minimum=1,
                maximum=60_000,
            ),
            OnlyIntegrationConfigurationFieldV1(
                "timeout_seconds",
                OnlyIntegrationValueKind.DURATION,
                False,
                default=10.0,
                advanced=True,
                display_name="Request timeout",
                minimum=0.0,
                maximum=30.0,
                exclusive_minimum=True,
            ),
            OnlyIntegrationConfigurationFieldV1(
                "max_response_bytes",
                OnlyIntegrationValueKind.INTEGER,
                False,
                default=8 * 1024 * 1024,
                advanced=True,
                display_name="Maximum response bytes",
                minimum=1,
            ),
        )
    ),
    probe_contract=OnlyIntegrationProbeContractV1(
        probe_mode=OnlyIntegrationProbeMode.DEFAULT_INSTRUMENT,
        default_probe_instrument="BTCUSDT",
        user_selectable_probe_instrument=False,
        probe_checks=(
            OnlyIntegrationProbeCheck.CONNECTIVITY,
            OnlyIntegrationProbeCheck.AUTHENTICATION,
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class OnlyBinancePluginDescriptor:
    plugin_id: str = "onlyalpha-plugin-binance"
    provider: str = "BINANCE"
    capabilities: tuple[str, ...] = (
        "SPOT_PUBLIC_REFERENCE",
        "SPOT_HISTORICAL_BAR",
        "SPOT_HISTORICAL_TRADE",
        "SPOT_REALTIME_BAR",
        "SPOT_REALTIME_TRADE",
        "SPOT_REALTIME_REFERENCE",
        "SPOT_PRIVATE_REST",
        "SPOT_USER_DATA_STREAM",
        "USDM_HISTORICAL_REFERENCE_PRICE",
        "USDM_HISTORICAL_FUNDING_RATE",
        "USDM_CANONICAL_ORDER_TRANSLATION",
    )


def only_plugin_descriptor() -> OnlyBinancePluginDescriptor:
    return OnlyBinancePluginDescriptor()
