import pytest

from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.plugin.errors import OnlyPluginRegistryError

from .conftest import OnlyTestFactory, only_test_descriptor


def test_data_source_registry_resolves_and_reports_descriptors() -> None:
    registry = OnlyDataSourceFactoryRegistry()
    factory = OnlyTestFactory(only_test_descriptor())
    registry.register(factory)  # type: ignore[arg-type]
    assert registry.resolve("unit-data") is factory
    assert registry.descriptors() == (factory.descriptor,)
    with pytest.raises(OnlyPluginRegistryError, match="PLUGIN_NOT_FOUND"):
        registry.resolve("missing")
