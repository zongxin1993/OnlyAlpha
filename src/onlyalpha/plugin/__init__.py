"""Plugin metadata primitives; external factories import ``onlyalpha.plugin.api``."""

from onlyalpha.plugin.capabilities import (
    OnlyBrokerPluginCapabilities,
    OnlyCheckpointCapability,
    OnlyDataSourceCapabilities,
    OnlyPluginValidationIssue,
)
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginOrigin, OnlyPluginOriginType, OnlyPluginType
from onlyalpha.plugin.errors import OnlyPluginError
from onlyalpha.plugin.integration_probe import (
    OnlyIntegrationProbeCheckResult,
    OnlyIntegrationProbeCheckStatus,
    OnlyIntegrationProbeFailureKind,
    OnlyIntegrationProbePolicy,
    OnlyIntegrationProbeProvider,
    OnlyIntegrationProbeRequest,
    OnlyIntegrationProbeResult,
    OnlyIntegrationProbeStatus,
)
from onlyalpha.plugin.lifecycle import OnlyPluginHealth, OnlyPluginHealthStatus, OnlyPluginLifecycleState
from onlyalpha.plugin.version import ONLYALPHA_PLUGIN_API_VERSION, OnlyPluginApiVersion

__all__ = [
    "ONLYALPHA_PLUGIN_API_VERSION",
    "OnlyBrokerPluginCapabilities",
    "OnlyCheckpointCapability",
    "OnlyDataSourceCapabilities",
    "OnlyIntegrationProbeCheckResult",
    "OnlyIntegrationProbeCheckStatus",
    "OnlyIntegrationProbeFailureKind",
    "OnlyIntegrationProbePolicy",
    "OnlyIntegrationProbeProvider",
    "OnlyIntegrationProbeRequest",
    "OnlyIntegrationProbeResult",
    "OnlyIntegrationProbeStatus",
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
