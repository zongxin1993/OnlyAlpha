import pytest

from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.plugin.discovery import only_discover_plugins

from .test_plugin_discovery_fail_fast import _OnlyEntries


def test_plugin_discovery_non_fail_fast_records_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("onlyalpha.plugin.discovery.metadata.entry_points", lambda: _OnlyEntries())
    report = only_discover_plugins(OnlyDataSourceFactoryRegistry(), OnlyBrokerFactoryRegistry(), fail_fast=False)
    assert report.discovered == ()
    assert report.failures[0].code == "PLUGIN_LOAD_FAILED"
