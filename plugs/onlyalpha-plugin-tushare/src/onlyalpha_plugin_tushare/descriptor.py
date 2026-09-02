from onlyalpha.plugin.capabilities import OnlyCheckpointCapability, OnlyDataSourceCapabilities
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginType
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
