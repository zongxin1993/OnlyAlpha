"""Plugin metadata primitives; external factories import ``onlyalpha.plugin.api``."""

from onlyalpha.plugin.capabilities import (
    OnlyBrokerPluginCapabilities,
    OnlyDataSourceCapabilities,
    OnlyPluginValidationIssue,
)
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginOrigin, OnlyPluginOriginType, OnlyPluginType
from onlyalpha.plugin.errors import OnlyPluginError
from onlyalpha.plugin.lifecycle import OnlyPluginHealth, OnlyPluginHealthStatus, OnlyPluginLifecycleState
from onlyalpha.plugin.version import ONLYALPHA_PLUGIN_API_VERSION, OnlyPluginApiVersion

__all__ = [
    "ONLYALPHA_PLUGIN_API_VERSION",
    "OnlyBrokerPluginCapabilities",
    "OnlyDataSourceCapabilities",
    "OnlyPluginApiVersion",
    "OnlyPluginDescriptor",
    "OnlyPluginError",
    "OnlyPluginHealth",
    "OnlyPluginHealthStatus",
    "OnlyPluginLifecycleState",
    "OnlyPluginOrigin",
    "OnlyPluginOriginType",
    "OnlyPluginType",
    "OnlyPluginValidationIssue",
]
