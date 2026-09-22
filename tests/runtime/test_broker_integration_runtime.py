from types import MappingProxyType

import pytest

from onlyalpha.application.integration_configuration import OnlyIntegrationId
from onlyalpha.application.integration_runtime import (
    OnlyIntegrationRuntimeBindingV1,
    OnlyIntegrationRuntimeError,
    OnlyResolvedIntegrationRuntimeConfiguration,
    OnlyResolvedIntegrationSecrets,
)
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.config.models import OnlyBrokerRuntimeConfig, OnlyRuntimeConfigurationMode
from onlyalpha.plugin.capabilities import OnlyBrokerPluginCapabilities
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginType
from onlyalpha.plugin.integration import (
    OnlyIntegrationCategory,
    OnlyIntegrationConfigurationContractV1,
    OnlyIntegrationTypeDescriptorV1,
    OnlyIntegrationTypeId,
)
from onlyalpha.plugin.version import ONLYALPHA_PLUGIN_API_VERSION
from onlyalpha.runtime.broker_integration import (
    only_admit_broker_runtime_configuration,
    only_resolve_broker_runtime_configuration,
)


class _Factory:
    descriptor = OnlyPluginDescriptor(
        "exact-broker",
        OnlyPluginType.BROKER,
        "1.0.0",
        ONLYALPHA_PLUGIN_API_VERSION,
        "Exact broker",
        "Tests",
        OnlyBrokerPluginCapabilities(live_execution=True),
    )
    integration_type = OnlyIntegrationTypeDescriptorV1(
        OnlyIntegrationTypeId("test.exact_broker"),
        OnlyIntegrationCategory.BROKER,
        "Exact broker",
        "Exact broker for tests.",
        "tests",
        descriptor.plugin_id,
        descriptor.plugin_version,
        str(descriptor.api_version),
        ("LIVE_EXECUTION",),
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
        self.admission: dict[str, object] | None = None

    def resolve(self, binding: object, **_kwargs: object) -> object:
        return self.resolved

    def admit_new_reference(self, *_args: object, **kwargs: object) -> object:
        self.admission = kwargs
        return self.resolved


def _fixture() -> tuple[_Factory, OnlyIntegrationRuntimeBindingV1, _Resolver]:
    factory = _Factory()
    binding = OnlyIntegrationRuntimeBindingV1(
        OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac"),
        "a" * 64,
        factory.integration_type.type_id.value,
        OnlyIntegrationCategory.BROKER,
        factory.integration_type.fingerprint,
        "b" * 64,
    )
    resolver = _Resolver(
        OnlyResolvedIntegrationRuntimeConfiguration(
            binding,
            factory.integration_type,
            MappingProxyType({"environment": "LIVE"}),
            OnlyResolvedIntegrationSecrets({"api_key": "exact"}),
        )
    )
    return factory, binding, resolver


def test_exact_broker_binding_selects_adapter_and_resolved_secrets() -> None:
    factory, binding, resolver = _fixture()
    registry = OnlyBrokerFactoryRegistry()
    registry.register(factory)
    broker = OnlyBrokerRuntimeConfig(
        OnlyBrokerGatewayId("broker"),
        "",
        True,
        configuration_mode=OnlyRuntimeConfigurationMode.INTEGRATION_REVISION,
        integration_binding=MappingProxyType(binding.to_dict()),
    )

    selected, config = only_resolve_broker_runtime_configuration(
        broker,
        registry,
        resolver,  # type: ignore[arg-type]
        OnlyBrokerPluginCapabilities(live_execution=True),
    )

    assert selected is factory
    assert config == ({"environment": "LIVE"}, {"api_key": "exact"})


def test_new_live_admission_requires_current_exact_ready_revision() -> None:
    _factory, binding, resolver = _fixture()
    broker = OnlyBrokerRuntimeConfig(
        OnlyBrokerGatewayId("broker"),
        "",
        True,
        configuration_mode=OnlyRuntimeConfigurationMode.INTEGRATION_REVISION,
        integration_binding=MappingProxyType(
            {
                "integration_id": binding.integration_id.value,
                "revision_fingerprint": binding.revision_fingerprint,
            }
        ),
    )

    admitted = only_admit_broker_runtime_configuration(
        broker,
        resolver,  # type: ignore[arg-type]
        OnlyBrokerPluginCapabilities(live_execution=True),
        require_current_revision=True,
        require_ready_probe=True,
    )

    assert admitted.integration_binding is not None
    assert admitted.integration_binding["binding_fingerprint"] == binding.binding_fingerprint
    assert resolver.admission is not None
    assert resolver.admission["require_current_revision"] is True
    assert resolver.admission["require_ready_probe"] is True


def test_new_work_rejects_full_recovery_binding() -> None:
    _factory, binding, resolver = _fixture()
    broker = OnlyBrokerRuntimeConfig(
        OnlyBrokerGatewayId("broker"),
        "",
        True,
        configuration_mode=OnlyRuntimeConfigurationMode.INTEGRATION_REVISION,
        integration_binding=MappingProxyType(binding.to_dict()),
    )

    with pytest.raises(OnlyIntegrationRuntimeError, match="RECOVERY_BINDING_FORBIDDEN"):
        only_admit_broker_runtime_configuration(
            broker,
            resolver,  # type: ignore[arg-type]
            OnlyBrokerPluginCapabilities(),
        )
