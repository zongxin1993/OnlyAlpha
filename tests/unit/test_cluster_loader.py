import pytest

from onlyalpha.cluster.demo import OnlyDemoCluster
from onlyalpha.cluster.loader import OnlyClusterLoader
from onlyalpha.cluster.registry import OnlyClusterRegistry
from onlyalpha.core.errors import OnlyDuplicateIdError


def test_static_registry_and_dynamic_loader() -> None:
    registry = OnlyClusterRegistry()
    registry.register("demo", OnlyDemoCluster)
    assert registry.resolve("demo") is OnlyDemoCluster
    assert OnlyClusterLoader().load("onlyalpha.cluster.demo", "OnlyDemoCluster") is OnlyDemoCluster
    with pytest.raises(OnlyDuplicateIdError):
        registry.register("demo", OnlyDemoCluster)
