"""Virtual Broker plugin metadata."""

from importlib.metadata import version

from onlyalpha.plugin.capabilities import OnlyBrokerPluginCapabilities
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginType
from onlyalpha.plugin.version import ONLYALPHA_PLUGIN_API_VERSION

ONLY_VIRTUAL_PLUGIN_DESCRIPTOR = OnlyPluginDescriptor(
    "virtual",
    OnlyPluginType.BROKER,
    version("onlyalpha-plugin-broker-virtual"),
    ONLYALPHA_PLUGIN_API_VERSION,
    "OnlyAlpha Virtual Broker",
    "OnlyAlpha",
    OnlyBrokerPluginCapabilities(
        submit_order=True,
        cancel_order=True,
        query_orders=True,
        query_trades=True,
        query_account=True,
        query_positions=True,
        simulated_execution=True,
    ),
)

__all__ = ["ONLY_VIRTUAL_PLUGIN_DESCRIPTOR"]
