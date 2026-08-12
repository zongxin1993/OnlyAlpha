from onlyalpha.plugin.capabilities import (
    OnlyBrokerPluginCapabilities,
    OnlyCheckpointCapability,
    OnlyDataSourceCapabilities,
)
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginType
from onlyalpha.plugin.version import OnlyPluginApiVersion

PLUGIN_ID = "miniqmt"
VERSION = "0.1.0"

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
BROKER_DESCRIPTOR = OnlyPluginDescriptor(
    PLUGIN_ID,
    OnlyPluginType.BROKER,
    VERSION,
    OnlyPluginApiVersion(1, 1),
    "MiniQMT",
    "OnlyAlpha",
    BROKER_CAPABILITIES,
)
