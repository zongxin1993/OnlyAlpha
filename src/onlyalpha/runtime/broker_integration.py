"""Broker runtime configuration selection across explicit L4 modes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import cast

from onlyalpha.application.integration_runtime import (
    OnlyIntegrationRuntimeBindingV1,
    OnlyIntegrationRuntimeError,
    OnlyIntegrationRuntimeResolver,
    OnlyResolvedIntegrationRuntimeConfiguration,
)
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.config.models import OnlyBrokerRuntimeConfig, OnlyJsonMapping, OnlyRuntimeConfigurationMode
from onlyalpha.plugin.broker import OnlyBrokerGatewayFactory, OnlyBrokerIntegrationRuntimeAdapter
from onlyalpha.plugin.capabilities import OnlyBrokerPluginCapabilities
from onlyalpha.plugin.integration import (
    OnlyIntegrationCategory,
    OnlyIntegrationTypeDescriptorV1,
    only_integration_capability_ids,
)


def only_admit_broker_runtime_configuration(
    broker: OnlyBrokerRuntimeConfig,
    resolver: OnlyIntegrationRuntimeResolver | None,
    required_capabilities: OnlyBrokerPluginCapabilities,
    *,
    recovery: bool = False,
    require_current_revision: bool = False,
    require_ready_probe: bool = False,
) -> OnlyBrokerRuntimeConfig:
    if broker.configuration_mode is OnlyRuntimeConfigurationMode.LEGACY:
        return broker
    if resolver is None or broker.integration_binding is None:
        raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_RESOLVER_UNAVAILABLE")
    raw = dict(broker.integration_binding)
    if "schema_version" in raw:
        if not recovery:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_RECOVERY_BINDING_FORBIDDEN")
        binding = OnlyIntegrationRuntimeBindingV1.from_dict(raw)
        resolver.resolve(
            binding,
            expected_category=OnlyIntegrationCategory.BROKER,
            required_capabilities=only_integration_capability_ids(required_capabilities),
        )
    else:
        if recovery:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_RECOVERY_BINDING_REQUIRED")
        binding = _admit_reference(
            raw,
            resolver,
            required_capabilities,
            require_current_revision=require_current_revision,
            require_ready_probe=require_ready_probe,
        )
    _reject_unhosted_generation(binding)
    return replace(broker, integration_binding=cast(OnlyJsonMapping, binding.to_dict()))


def only_resolve_broker_runtime_configuration(
    broker: OnlyBrokerRuntimeConfig,
    registry: OnlyBrokerFactoryRegistry,
    resolver: OnlyIntegrationRuntimeResolver | None,
    required_capabilities: OnlyBrokerPluginCapabilities,
) -> tuple[OnlyBrokerGatewayFactory, object]:
    factory, resolved = _resolve_factory(broker, registry, resolver, required_capabilities)
    if resolved is None:
        return factory, factory.parse_config(broker.extensions)
    assert isinstance(factory, OnlyBrokerIntegrationRuntimeAdapter)
    return factory, factory.parse_runtime_integration_config(
        resolved.public_configuration,
        resolved.secrets.as_mapping(),
    )


def only_resolve_broker_runtime_factory(
    broker: OnlyBrokerRuntimeConfig,
    registry: OnlyBrokerFactoryRegistry,
    resolver: OnlyIntegrationRuntimeResolver | None,
    required_capabilities: OnlyBrokerPluginCapabilities,
) -> OnlyBrokerGatewayFactory:
    return _resolve_factory(broker, registry, resolver, required_capabilities)[0]


def _resolve_factory(
    broker: OnlyBrokerRuntimeConfig,
    registry: OnlyBrokerFactoryRegistry,
    resolver: OnlyIntegrationRuntimeResolver | None,
    required_capabilities: OnlyBrokerPluginCapabilities,
) -> tuple[OnlyBrokerGatewayFactory, OnlyResolvedIntegrationRuntimeConfiguration | None]:
    if broker.configuration_mode is OnlyRuntimeConfigurationMode.LEGACY:
        return registry.resolve(broker.plugin_id), None
    if resolver is None or broker.integration_binding is None:
        raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_RESOLVER_UNAVAILABLE")
    resolved = resolver.resolve(
        OnlyIntegrationRuntimeBindingV1.from_dict(dict(broker.integration_binding)),
        expected_category=OnlyIntegrationCategory.BROKER,
        required_capabilities=only_integration_capability_ids(required_capabilities),
    )
    _reject_unhosted_generation(resolved.binding)
    try:
        factory = registry.resolve(resolved.type_descriptor.implementation_id)
    except Exception:
        raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_IMPLEMENTATION_UNAVAILABLE") from None
    declared = getattr(factory, "integration_type", None)
    if not isinstance(declared, OnlyIntegrationTypeDescriptorV1) or declared != resolved.type_descriptor:
        raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_IMPLEMENTATION_MISMATCH")
    if not isinstance(factory, OnlyBrokerIntegrationRuntimeAdapter):
        raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_IMPLEMENTATION_UNAVAILABLE")
    return factory, resolved


def _admit_reference(
    raw: Mapping[str, object],
    resolver: OnlyIntegrationRuntimeResolver,
    required_capabilities: OnlyBrokerPluginCapabilities,
    *,
    require_current_revision: bool,
    require_ready_probe: bool,
) -> OnlyIntegrationRuntimeBindingV1:
    if set(raw) - {"integration_id", "revision_fingerprint", "runtime_generation_fingerprint"} or not {
        "integration_id",
        "revision_fingerprint",
    }.issubset(raw):
        raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_BINDING_INVALID")
    generation = raw.get("runtime_generation_fingerprint")
    if (
        not isinstance(raw["integration_id"], str)
        or not isinstance(raw["revision_fingerprint"], str)
        or (generation is not None and not isinstance(generation, str))
    ):
        raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_BINDING_INVALID")
    return resolver.admit_new_reference(
        raw["integration_id"],
        raw["revision_fingerprint"],
        expected_category=OnlyIntegrationCategory.BROKER,
        required_capabilities=only_integration_capability_ids(required_capabilities),
        require_current_revision=require_current_revision,
        require_ready_probe=require_ready_probe,
        runtime_generation_fingerprint=generation,
    ).binding


def _reject_unhosted_generation(binding: OnlyIntegrationRuntimeBindingV1) -> None:
    if binding.runtime_generation_fingerprint is not None:
        raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_IMPLEMENTATION_UNAVAILABLE")
