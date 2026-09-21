"""DataSource runtime configuration selection across explicit L4 modes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import cast

from onlyalpha.application.integration_runtime import (
    OnlyIntegrationRuntimeBindingV1,
    OnlyIntegrationRuntimeError,
    OnlyIntegrationRuntimeResolver,
)
from onlyalpha.config.models import OnlyDataSourceRuntimeConfig, OnlyJsonMapping, OnlyRuntimeConfigurationMode
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.plugin.capabilities import OnlyDataSourceCapabilities
from onlyalpha.plugin.data_source import (
    OnlyDataSourceFactory,
    OnlyDataSourceIntegrationRuntimeAdapter,
)
from onlyalpha.plugin.integration import (
    OnlyIntegrationCategory,
    OnlyIntegrationTypeDescriptorV1,
    only_integration_capability_ids,
)


def only_admit_data_source_runtime_configuration(
    source: OnlyDataSourceRuntimeConfig,
    resolver: OnlyIntegrationRuntimeResolver | None,
    required_capabilities: OnlyDataSourceCapabilities,
    *,
    recovery: bool = False,
) -> OnlyDataSourceRuntimeConfig:
    if source.configuration_mode is OnlyRuntimeConfigurationMode.LEGACY:
        return source
    if resolver is None or source.integration_binding is None:
        raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_RESOLVER_UNAVAILABLE")
    raw = dict(source.integration_binding)
    if "schema_version" in raw:
        if not recovery:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_RECOVERY_BINDING_FORBIDDEN")
        binding = OnlyIntegrationRuntimeBindingV1.from_dict(raw)
        resolver.resolve(
            binding,
            expected_category=OnlyIntegrationCategory.DATA_SOURCE,
            required_capabilities=only_integration_capability_ids(required_capabilities),
        )
    else:
        if recovery:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_RECOVERY_BINDING_REQUIRED")
        binding = _admit_reference(raw, resolver, required_capabilities)
    _reject_unhosted_generation(binding)
    return replace(source, integration_binding=cast(OnlyJsonMapping, binding.to_dict()))


def only_resolve_data_source_runtime_configuration(
    source: OnlyDataSourceRuntimeConfig,
    registry: OnlyDataSourceFactoryRegistry,
    resolver: OnlyIntegrationRuntimeResolver | None,
    required_capabilities: OnlyDataSourceCapabilities,
) -> tuple[OnlyDataSourceFactory, object]:
    if source.configuration_mode is OnlyRuntimeConfigurationMode.LEGACY:
        factory = registry.resolve(source.plugin_id)
        return factory, factory.parse_config(source.extensions)
    if resolver is None or source.integration_binding is None:
        raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_RESOLVER_UNAVAILABLE")

    binding = OnlyIntegrationRuntimeBindingV1.from_dict(dict(source.integration_binding))
    resolved = resolver.resolve(
        binding,
        expected_category=OnlyIntegrationCategory.DATA_SOURCE,
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
    if not isinstance(factory, OnlyDataSourceIntegrationRuntimeAdapter):
        raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_IMPLEMENTATION_UNAVAILABLE")
    return factory, factory.parse_runtime_integration_config(
        resolved.public_configuration,
        resolved.secrets.as_mapping(),
    )


def _admit_reference(
    raw: Mapping[str, object],
    resolver: OnlyIntegrationRuntimeResolver,
    required_capabilities: OnlyDataSourceCapabilities,
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
        expected_category=OnlyIntegrationCategory.DATA_SOURCE,
        required_capabilities=only_integration_capability_ids(required_capabilities),
        runtime_generation_fingerprint=generation,
    ).binding


def _reject_unhosted_generation(binding: OnlyIntegrationRuntimeBindingV1) -> None:
    if binding.runtime_generation_fingerprint is not None:
        raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_IMPLEMENTATION_UNAVAILABLE")
