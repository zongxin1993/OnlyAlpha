import pytest
from onlyalpha_plugin_factors.registration import registrations as factor_registrations
from onlyalpha_plugin_indicators.registration import registrations as indicator_registrations

from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.indicator.registry import OnlyIndicatorFactoryRegistry
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry
from onlyalpha.plugin.discovery import only_discover_plugins
from onlyalpha.plugin.errors import OnlyPluginDiscoveryError


class _Entry:
    group = "onlyalpha.calculations"

    def __init__(self, name: str, value: str, provider: object) -> None:
        self.name = name
        self.value = value
        self.provider = provider

    def load(self) -> object:
        if isinstance(self.provider, Exception):
            raise self.provider
        return self.provider


class _Entries:
    def __init__(self, entries: tuple[_Entry, ...]) -> None:
        self.entries = entries

    def select(self, *, group: str) -> tuple[_Entry, ...]:
        return self.entries if group == "onlyalpha.calculations" else ()


def _discover(monkeypatch, entries, *, fail_fast=True):
    monkeypatch.setattr("onlyalpha.plugin.discovery.metadata.entry_points", lambda: _Entries(entries))
    indicators = OnlyIndicatorFactoryRegistry()
    report = only_discover_plugins(
        OnlyDataSourceFactoryRegistry(),
        OnlyBrokerFactoryRegistry(),
        OnlyBrokerFeeContractRegistry(),
        OnlyMarketProductFactoryRegistry(),
        indicators,
        fail_fast=fail_fast,
    )
    return indicators, report


def test_calculation_discovery_is_stable_and_registers_research_only_factors(monkeypatch) -> None:
    entries = (
        _Entry("z-factors", "factor:registrations", factor_registrations),
        _Entry("a-indicators", "indicator:registrations", indicator_registrations),
    )
    registry, report = _discover(monkeypatch, entries)
    assert tuple(item.name for item in report.discovered) == ("a-indicators", "z-factors")
    assert len(registry._factories) == 9  # noqa: SLF001 - discovery contract inspection
    assert {item.type_id for item in registry._calculations.type_definitions()} >= {  # noqa: SLF001
        "onlyalpha.factor.momentum",
        "onlyalpha.factor.cross_section_percentile",
    }


@pytest.mark.parametrize("provider", (object(), lambda: (object(),), ImportError("boom")))
def test_calculation_discovery_rejects_malformed_or_raising_provider(monkeypatch, provider) -> None:
    with pytest.raises(OnlyPluginDiscoveryError):
        _discover(monkeypatch, (_Entry("broken", "broken:provider", provider),))


def test_calculation_discovery_rejects_cross_plugin_collision(monkeypatch) -> None:
    entries = (
        _Entry("one", "one:registrations", indicator_registrations),
        _Entry("two", "two:registrations", indicator_registrations),
    )
    with pytest.raises(OnlyPluginDiscoveryError, match="duplicate"):
        _discover(monkeypatch, entries)
