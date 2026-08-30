from dataclasses import dataclass

from onlyalpha.plugin.capabilities import OnlyCheckpointCapability, OnlyDataSourceCapabilities
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginType
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
    )


def only_plugin_descriptor() -> OnlyBinancePluginDescriptor:
    return OnlyBinancePluginDescriptor()
