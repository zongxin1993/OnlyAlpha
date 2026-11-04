from onlyalpha.plugin.capabilities import (
    OnlyBrokerPluginCapabilities,
    OnlyCheckpointCapability,
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
