import pytest

from onlyalpha.plugin import ONLYALPHA_PLUGIN_API_VERSION, OnlyPluginApiVersion


def test_plugin_api_version_is_ordered_and_stable() -> None:
    assert str(ONLYALPHA_PLUGIN_API_VERSION) == "1.0"
    assert OnlyPluginApiVersion(1, 0) < OnlyPluginApiVersion(1, 1)
    with pytest.raises(ValueError):
        OnlyPluginApiVersion(-1, 0)
