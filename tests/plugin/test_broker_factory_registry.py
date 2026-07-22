import pytest

from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.plugin import OnlyPluginType
from onlyalpha.plugin.errors import OnlyPluginDescriptorError, OnlyPluginRegistryError

from .conftest import OnlyTestFactory, only_test_descriptor


def test_broker_registry_enforces_plugin_type_and_unknown_id() -> None:
    registry = OnlyBrokerFactoryRegistry()
    factory = OnlyTestFactory(only_test_descriptor("unit-broker", OnlyPluginType.BROKER))
    registry.register(factory)  # type: ignore[arg-type]
    assert registry.resolve("unit-broker") is factory
    with pytest.raises(OnlyPluginDescriptorError, match="PLUGIN_TYPE_MISMATCH"):
        registry.register(OnlyTestFactory(only_test_descriptor()))  # type: ignore[arg-type]
    with pytest.raises(OnlyPluginRegistryError, match="BROKER_PLUGIN_NOT_FOUND"):
        registry.resolve("missing")
