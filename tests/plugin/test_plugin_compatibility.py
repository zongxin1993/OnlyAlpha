import pytest

from onlyalpha.plugin import OnlyPluginApiVersion, OnlyPluginDescriptor, OnlyPluginType
from onlyalpha.plugin.compatibility import only_validate_plugin_compatibility
from onlyalpha.plugin.errors import OnlyPluginApiVersionError, OnlyPluginDescriptorError

from .conftest import only_test_descriptor


def _version(major: int, minor: int) -> OnlyPluginDescriptor:
    value = only_test_descriptor()
    return OnlyPluginDescriptor(
        value.plugin_id,
        value.plugin_type,
        value.plugin_version,
        OnlyPluginApiVersion(major, minor),
        value.display_name,
        value.provider,
        value.capabilities,
    )


def test_compatible_and_incompatible_plugin_api_versions() -> None:
    assert only_validate_plugin_compatibility(_version(1, 0), OnlyPluginType.DATA_SOURCE)
    for required in ((2, 0), (1, 1)):
        with pytest.raises(OnlyPluginApiVersionError, match="PLUGIN_API_VERSION_INCOMPATIBLE"):
            only_validate_plugin_compatibility(_version(*required), OnlyPluginType.DATA_SOURCE)
    with pytest.raises(OnlyPluginDescriptorError, match="PLUGIN_API_VERSION_MISSING"):
        only_validate_plugin_compatibility(None, OnlyPluginType.DATA_SOURCE)
