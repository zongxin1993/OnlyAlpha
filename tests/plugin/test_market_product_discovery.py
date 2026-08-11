from __future__ import annotations

from dataclasses import dataclass

import pytest

from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry, OnlyMarketProductPluginId
from onlyalpha.plugin.discovery import only_discover_plugins
from onlyalpha.plugin.errors import OnlyPluginDiscoveryError


@dataclass(frozen=True, slots=True)
class _Factory:
    plugin_id: OnlyMarketProductPluginId


@dataclass(frozen=True, slots=True)
class _Entry:
    name: str
    value: str
    factory: _Factory
    group: str = "onlyalpha.market_products"

    def load(self) -> _Factory:
        return self.factory


class _Entries:
    def __init__(self, entries: tuple[_Entry, ...]) -> None:
        self._entries = entries

    def select(self, *, group: str) -> tuple[_Entry, ...]:
        return tuple(entry for entry in self._entries if entry.group == group)


def _discover(monkeypatch: pytest.MonkeyPatch, entries: tuple[_Entry, ...]) -> tuple[str, ...]:
    monkeypatch.setattr(
        "onlyalpha.plugin.discovery.metadata.entry_points",
        lambda: _Entries(entries),
    )
    registry = OnlyMarketProductFactoryRegistry()
    report = only_discover_plugins(
        OnlyDataSourceFactoryRegistry(),
        OnlyBrokerFactoryRegistry(),
        OnlyBrokerFeeContractRegistry(),
        registry,
        fail_fast=True,
    )
    return tuple(item.name for item in report.discovered)


def test_market_product_discovery_order_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _Entry("z-provider", "z:factory", _Factory(OnlyMarketProductPluginId("z-provider")))
    second = _Entry("a-provider", "a:factory", _Factory(OnlyMarketProductPluginId("a-provider")))
    assert _discover(monkeypatch, (first, second)) == ("a-provider", "z-provider")
    assert _discover(monkeypatch, (second, first)) == ("a-provider", "z-provider")


def test_market_product_discovery_conflict_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_id = OnlyMarketProductPluginId("conflict")
    entries = (
        _Entry("first", "first:factory", _Factory(plugin_id)),
        _Entry("second", "second:factory", _Factory(plugin_id)),
    )
    with pytest.raises(OnlyPluginDiscoveryError, match="MARKET_PRODUCT_PLUGIN_CONFLICT"):
        _discover(monkeypatch, entries)
