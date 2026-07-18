import pytest

from onlyalpha.plugin import OnlyPluginDescriptor
from onlyalpha.plugin.errors import OnlyPluginDescriptorError

from .conftest import only_test_descriptor


def test_plugin_descriptor_requires_stable_lowercase_id() -> None:
    assert only_test_descriptor().plugin_id == "unit-data"
    values = only_test_descriptor().__dict__ if hasattr(only_test_descriptor(), "__dict__") else None
    del values
    with pytest.raises(OnlyPluginDescriptorError, match="PLUGIN_DESCRIPTOR_INVALID"):
        OnlyPluginDescriptor(
            "Invalid ID",
            only_test_descriptor().plugin_type,
            "1.0.0",
            only_test_descriptor().api_version,
            "Invalid",
            None,
            object(),
        )
