from dataclasses import dataclass

from onlyalpha.plugin.capabilities import (
    OnlyBrokerPluginCapabilities,
    OnlyCheckpointCapability,
    OnlyDataSourceCapabilities,
)
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
