"""Single stable import surface for external OnlyAlpha plugins."""

# ruff: noqa: F401

from onlyalpha.plugin.broker import (
    OnlyBacktestBrokerGateway,
    OnlyBrokerCreateRequest,
    OnlyBrokerGatewayFactory,
    OnlyBrokerInboundQueue,
)
from onlyalpha.plugin.capabilities import (
    OnlyBrokerPluginCapabilities,
    OnlyDataSourceCapabilities,
    OnlyPluginValidationIssue,
)
from onlyalpha.plugin.data_source import OnlyDataSource, OnlyDataSourceCreateRequest, OnlyDataSourceFactory
from onlyalpha.plugin.descriptor import (
    OnlyPluginDescriptor,
    OnlyPluginOrigin,
    OnlyPluginOriginType,
    OnlyPluginType,
)
from onlyalpha.plugin.errors import (
    OnlyPluginApiVersionError,
    OnlyPluginCapabilityError,
    OnlyPluginDescriptorError,
    OnlyPluginDiscoveryError,
    OnlyPluginError,
    OnlyPluginLifecycleError,
    OnlyPluginRegistryError,
)
from onlyalpha.plugin.lifecycle import (
    OnlyPluginHealth,
    OnlyPluginHealthStatus,
    OnlyPluginLifecycleState,
    OnlyPluginResource,
    OnlyPluginResourceSnapshot,
)
from onlyalpha.plugin.version import ONLYALPHA_PLUGIN_API_VERSION, OnlyPluginApiVersion

__all__ = [name for name in globals() if name.startswith("Only") or name == "ONLYALPHA_PLUGIN_API_VERSION"]
