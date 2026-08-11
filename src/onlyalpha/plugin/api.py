"""Single stable import surface for external OnlyAlpha plugins."""

# ruff: noqa: F401

from onlyalpha.fee.broker_contract import (
    OnlyBrokerFeeContract as OnlyBrokerFeeContract,
)
from onlyalpha.fee.broker_contract import (
    only_simulation_zero_broker_fee_contract as only_simulation_zero_broker_fee_contract,
)
from onlyalpha.market.product import (
    OnlyCanonicalMarketProductConfig,
    OnlyCompiledMarketPolicy,
    OnlyCompiledMarketPolicyIdentity,
    OnlyDuplicateMarketProductPluginError,
    OnlyInvalidMarketProductConfigurationError,
    OnlyMarketPolicyCompilationRequest,
    OnlyMarketPolicyCompiler,
    OnlyMarketPolicyReference,
    OnlyMarketProductAuthorityConflictError,
    OnlyMarketProductAuthorityIdentity,
    OnlyMarketProductCompositionIdentity,
    OnlyMarketProductConfig,
    OnlyMarketProductError,
    OnlyMarketProductFactory,
    OnlyMarketProductFactoryRegistry,
    OnlyMarketProductId,
    OnlyMarketProductIdentity,
    OnlyMarketProductPluginId,
    OnlyMarketProductResolutionContext,
    OnlyMarketProductResolutionError,
    OnlyMarketProductResourceResolver,
    OnlyMarketProductVersion,
    OnlyMarketReferenceAuthority,
    OnlyResolvedMarketProductBinding,
    OnlyUnknownMarketProductPluginError,
    OnlyUnsupportedMarketProductError,
    OnlyUnsupportedMarketProductVersionError,
)
from onlyalpha.plugin.broker import (
    OnlyBrokerComponent,
    OnlyBrokerCreateRequest,
    OnlyBrokerGatewayFactory,
    OnlyBrokerInboundQueue,
    OnlyDeterministicBrokerDriver,
)
from onlyalpha.plugin.capabilities import (
    OnlyBrokerPluginCapabilities,
    OnlyCheckpointCapability,
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
from onlyalpha.reference import OnlyAshareInstrumentReference as OnlyAshareInstrumentReference

__all__ = [
    name
    for name in globals()
    if name.startswith("Only") or name in {"ONLYALPHA_PLUGIN_API_VERSION", "only_simulation_zero_broker_fee_contract"}
]
