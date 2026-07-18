"""Shared Factory registration validation and deterministic records."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.plugin.compatibility import only_validate_plugin_compatibility
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginOrigin, OnlyPluginType
from onlyalpha.plugin.errors import OnlyPluginRegistryError


@dataclass(frozen=True, slots=True)
class OnlyPluginFactoryRecord:
    descriptor: OnlyPluginDescriptor
    origin: OnlyPluginOrigin
    factory: object


def only_register_plugin_factory(
    records: dict[str, OnlyPluginFactoryRecord],
    factory: object,
    origin: OnlyPluginOrigin,
    expected_type: OnlyPluginType,
) -> None:
    descriptor = getattr(factory, "descriptor", None)
    if not isinstance(descriptor, OnlyPluginDescriptor):
        raise OnlyPluginRegistryError(
            "PLUGIN_FACTORY_INVALID",
            "factory must expose an OnlyPluginDescriptor",
            origin=str(origin),
        )
    only_validate_plugin_compatibility(descriptor, expected_type)
    required_methods = ("parse_config", "validate_request", "create")
    if any(not callable(getattr(factory, name, None)) for name in required_methods):
        raise OnlyPluginRegistryError(
            "PLUGIN_FACTORY_INVALID",
            f"factory must implement {required_methods}",
            plugin_id=descriptor.plugin_id,
            origin=str(origin),
        )
    existing = records.get(descriptor.plugin_id)
    if existing is not None:
        if existing.factory is factory and existing.descriptor == descriptor:
            return
        raise OnlyPluginRegistryError(
            "PLUGIN_ID_CONFLICT",
            f"plugin is already registered from {existing.origin}",
            plugin_id=descriptor.plugin_id,
            origin=str(origin),
        )
    records[descriptor.plugin_id] = OnlyPluginFactoryRecord(descriptor, origin, factory)
