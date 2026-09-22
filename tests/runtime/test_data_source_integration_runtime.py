from types import MappingProxyType

import pytest

from onlyalpha.application.integration_configuration import OnlyIntegrationId
from onlyalpha.application.integration_runtime import (
    OnlyIntegrationRuntimeBindingV1,
    OnlyIntegrationRuntimeError,
    OnlyResolvedIntegrationRuntimeConfiguration,
    OnlyResolvedIntegrationSecrets,
)
from onlyalpha.config.models import (
    OnlyDataSourceCoverageConfig,
    OnlyDataSourceRuntimeConfig,
    OnlyRuntimeConfigurationMode,
)
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.plugin.capabilities import OnlyDataSourceCapabilities
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginType
from onlyalpha.plugin.integration import (
    OnlyIntegrationCategory,
    OnlyIntegrationConfigurationContractV1,
    OnlyIntegrationTypeDescriptorV1,
    OnlyIntegrationTypeId,
)
from onlyalpha.plugin.version import ONLYALPHA_PLUGIN_API_VERSION
from onlyalpha.runtime.data_source_integration import only_resolve_data_source_runtime_configuration


class _Factory:
    descriptor = OnlyPluginDescriptor(
        "exact-source",
        OnlyPluginType.DATA_SOURCE,
        "1.0.0",
        ONLYALPHA_PLUGIN_API_VERSION,
        "Exact source",
        "Tests",
        OnlyDataSourceCapabilities(historical_bars=True),
    )
    integration_type = OnlyIntegrationTypeDescriptorV1(
        OnlyIntegrationTypeId("test.exact_source"),
        OnlyIntegrationCategory.DATA_SOURCE,
        "Exact source",
        "Exact source for tests.",
        "tests",
        descriptor.plugin_id,
        descriptor.plugin_version,
        str(descriptor.api_version),
        ("HISTORICAL_BARS",),
        OnlyIntegrationConfigurationContractV1(()),
    )

    @staticmethod
    def parse_config(extensions: object) -> object:
        return extensions

    @staticmethod
    def parse_runtime_integration_config(public: object, secrets: object) -> object:
        return public, secrets

    @staticmethod
    def validate_request(request: object) -> tuple[object, ...]:
        return ()

    @staticmethod
    def create(request: object) -> object:
        return request


class _Resolver:
    def __init__(self, resolved: OnlyResolvedIntegrationRuntimeConfiguration) -> None:
        self.resolved = resolved
        self.calls: list[tuple[object, object, object]] = []

    def resolve(self, binding: object, *, expected_category: object, required_capabilities: object) -> object:
        self.calls.append((binding, expected_category, required_capabilities))
        return self.resolved


def test_exact_integration_binding_selects_factory_without_provider_extensions() -> None:
    factory = _Factory()
    registry = OnlyDataSourceFactoryRegistry()
    registry.register(factory)
    binding = OnlyIntegrationRuntimeBindingV1(
        OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac"),
        "a" * 64,
        factory.integration_type.type_id.value,
        OnlyIntegrationCategory.DATA_SOURCE,
        factory.integration_type.fingerprint,
        "b" * 64,
    )
    resolved = OnlyResolvedIntegrationRuntimeConfiguration(
        binding,
        factory.integration_type,
        MappingProxyType({"endpoint": "https://example.test"}),
        OnlyResolvedIntegrationSecrets({"token": "exact"}),
    )
    resolver = _Resolver(resolved)
    source = OnlyDataSourceRuntimeConfig(
        OnlyMarketDataSourceId("exact-source"),
        "",
        True,
        OnlyDataVersion("v1"),
        OnlyDataSourceCoverageConfig(instrument_ids=(OnlyInstrumentId.parse("BTCUSDT.BINANCE"),)),
        configuration_mode=OnlyRuntimeConfigurationMode.INTEGRATION_REVISION,
        integration_binding=MappingProxyType(binding.to_dict()),
    )

    selected, plugin_config = only_resolve_data_source_runtime_configuration(
        source,
        registry,
        resolver,  # type: ignore[arg-type]
        OnlyDataSourceCapabilities(historical_bars=True),
    )

    assert selected is factory
    assert plugin_config[0] == {"endpoint": "https://example.test"}
    assert plugin_config[1]["token"] == "exact"
    assert resolver.calls[0][1:] == (OnlyIntegrationCategory.DATA_SOURCE, ("HISTORICAL_BARS",))


def test_generation_bound_data_source_never_falls_back_to_ambient_factory() -> None:
    factory = _Factory()
    registry = OnlyDataSourceFactoryRegistry()
    registry.register(factory)
    binding = OnlyIntegrationRuntimeBindingV1(
        OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac"),
        "a" * 64,
        factory.integration_type.type_id.value,
        OnlyIntegrationCategory.DATA_SOURCE,
        factory.integration_type.fingerprint,
        "b" * 64,
        "c" * 64,
    )
    resolver = _Resolver(
        OnlyResolvedIntegrationRuntimeConfiguration(
            binding,
            factory.integration_type,
            MappingProxyType({}),
            OnlyResolvedIntegrationSecrets({}),
        )
    )
    source = OnlyDataSourceRuntimeConfig(
        OnlyMarketDataSourceId("exact-source"),
        "",
        True,
        OnlyDataVersion("v1"),
        OnlyDataSourceCoverageConfig(instrument_ids=(OnlyInstrumentId.parse("BTCUSDT.BINANCE"),)),
        configuration_mode=OnlyRuntimeConfigurationMode.INTEGRATION_REVISION,
        integration_binding=MappingProxyType(binding.to_dict()),
    )

    with pytest.raises(OnlyIntegrationRuntimeError) as raised:
        only_resolve_data_source_runtime_configuration(
            source,
            registry,
            resolver,  # type: ignore[arg-type]
            OnlyDataSourceCapabilities(historical_bars=True),
        )

    assert raised.value.code == "INTEGRATION_RUNTIME_IMPLEMENTATION_UNAVAILABLE"
