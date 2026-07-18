"""Plugin descriptor and API compatibility validation."""

from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginType
from onlyalpha.plugin.errors import OnlyPluginApiVersionError, OnlyPluginDescriptorError
from onlyalpha.plugin.version import ONLYALPHA_PLUGIN_API_VERSION


def only_validate_plugin_compatibility(
    descriptor: OnlyPluginDescriptor | None,
    expected_type: OnlyPluginType,
) -> OnlyPluginDescriptor:
    if descriptor is None:
        raise OnlyPluginDescriptorError("PLUGIN_API_VERSION_MISSING", "plugin descriptor is missing")
    if descriptor.plugin_type is not expected_type:
        raise OnlyPluginDescriptorError(
            "PLUGIN_TYPE_MISMATCH",
            f"expected {expected_type.value}, got {descriptor.plugin_type.value}",
            plugin_id=descriptor.plugin_id,
        )
    required = descriptor.api_version
    current = ONLYALPHA_PLUGIN_API_VERSION
    if required.major != current.major or required.minor > current.minor:
        raise OnlyPluginApiVersionError(
            "PLUGIN_API_VERSION_INCOMPATIBLE",
            f"plugin requires {required}; core provides {current}",
            plugin_id=descriptor.plugin_id,
        )
    return descriptor
