import pytest

from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.plugin.discovery import only_discover_plugins
from onlyalpha.plugin.errors import OnlyPluginDiscoveryError


class _OnlyBrokenEntry:
    group = "onlyalpha.data_sources"
    name = "broken"
    value = "broken:factory"

    def load(self) -> object:
        raise ImportError("expected discovery failure")


class _OnlyEntries:
    def select(self, *, group: str) -> tuple[object, ...]:
        return (_OnlyBrokenEntry(),) if group == "onlyalpha.data_sources" else ()


def test_plugin_discovery_fail_fast_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("onlyalpha.plugin.discovery.metadata.entry_points", lambda: _OnlyEntries())
    with pytest.raises(OnlyPluginDiscoveryError, match="PLUGIN_LOAD_FAILED"):
        only_discover_plugins(OnlyDataSourceFactoryRegistry(), OnlyBrokerFactoryRegistry(), fail_fast=True)
