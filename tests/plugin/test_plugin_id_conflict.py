import pytest

from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.plugin import OnlyPluginOrigin, OnlyPluginOriginType
from onlyalpha.plugin.errors import OnlyPluginRegistryError
from tests.plugin.conftest import OnlyTestFactory, only_test_descriptor


def test_same_factory_is_idempotent_but_different_implementation_conflicts() -> None:
    registry = OnlyDataSourceFactoryRegistry()
    origin = OnlyPluginOrigin(OnlyPluginOriginType.TEST, "unit")
    factory = OnlyTestFactory(only_test_descriptor())
    registry.register(factory, origin=origin)  # type: ignore[arg-type]
    registry.register(factory, origin=origin)  # type: ignore[arg-type]
    with pytest.raises(OnlyPluginRegistryError, match="PLUGIN_ID_CONFLICT"):
        registry.register(OnlyTestFactory(only_test_descriptor()), origin=origin)  # type: ignore[arg-type]
