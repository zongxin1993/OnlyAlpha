from dataclasses import dataclass, replace

import pytest
from onlyalpha_agent_orchestrator.provider_integration import OnlyOpenAICompatibleAgentProviderProbe
from onlyalpha_plugin_binance.spot.data_source.factory import OnlyBinanceSpotDataSourceFactory
from onlyalpha_plugin_binance.usdm.data_source import OnlyBinanceUsdmDataSourceFactory
from onlyalpha_plugin_miniqmt.data_source.factory import OnlyMiniQmtDataSourceFactory
from onlyalpha_plugin_tushare.data_source.factory import OnlyTushareDataSourceFactory

from onlyalpha.application.integration_type_catalog import (
    OnlyIntegrationProbeCatalog,
    OnlyIntegrationTypeCatalog,
    OnlyIntegrationTypeCatalogError,
)
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.plugin import (
    ONLYALPHA_PLUGIN_API_VERSION,
    OnlyBrokerPluginCapabilities,
    OnlyDataSourceCapabilities,
    OnlyPluginDescriptor,
    OnlyPluginType,
)
from onlyalpha.plugin.agent_provider import OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE
from onlyalpha.plugin.integration import (
    OnlyIntegrationCategory,
    OnlyIntegrationConfigurationContractV1,
    OnlyIntegrationTypeDescriptorV1,
    OnlyIntegrationTypeId,
)


@dataclass
class Factory:
    descriptor: OnlyPluginDescriptor
    integration_type: OnlyIntegrationTypeDescriptorV1

    def parse_config(self, extensions: object) -> object:
        return extensions

    def validate_request(self, request: object) -> tuple[()]:
        del request
        return ()

    def create(self, request: object) -> object:
        return request


@dataclass
class LegacyFactory:
    descriptor: OnlyPluginDescriptor

    def parse_config(self, extensions: object) -> object:
        return extensions

    def validate_request(self, request: object) -> tuple[()]:
        del request
        return ()

    def create(self, request: object) -> object:
        return request


def _plugin(plugin_id: str, plugin_type: OnlyPluginType) -> OnlyPluginDescriptor:
    return OnlyPluginDescriptor(
        plugin_id,
        plugin_type,
        "1.2.3",
        ONLYALPHA_PLUGIN_API_VERSION,
        plugin_id,
        "Test",
        OnlyDataSourceCapabilities(historical_bars=True)
        if plugin_type is OnlyPluginType.DATA_SOURCE
        else OnlyBrokerPluginCapabilities(query_orders=True),
    )


def _integration(
    plugin: OnlyPluginDescriptor, type_id: str, category: OnlyIntegrationCategory
) -> OnlyIntegrationTypeDescriptorV1:
    return OnlyIntegrationTypeDescriptorV1(
        type_id=OnlyIntegrationTypeId(type_id),
        category=category,
        display_name=type_id,
        description=f"{type_id} integration",
        provider_id="test",
        implementation_id=plugin.plugin_id,
        implementation_version=plugin.plugin_version,
        public_api_version=str(plugin.api_version),
        capabilities=("HISTORICAL_BARS",) if plugin.plugin_type is OnlyPluginType.DATA_SOURCE else ("QUERY_ORDERS",),
        configuration_contract=OnlyIntegrationConfigurationContractV1(fields=()),
    )


def test_catalog_projects_declared_types_from_existing_registry_records_only(monkeypatch: pytest.MonkeyPatch) -> None:
    data_sources = OnlyDataSourceFactoryRegistry()
    brokers = OnlyBrokerFactoryRegistry()
    plugin = _plugin("declared-data", OnlyPluginType.DATA_SOURCE)
    declared = _integration(plugin, "test.market_data", OnlyIntegrationCategory.DATA_SOURCE)
    data_sources.register(Factory(plugin, declared))  # type: ignore[arg-type]
    undeclared_plugin = _plugin("internal-data", OnlyPluginType.DATA_SOURCE)
    data_sources.register(LegacyFactory(undeclared_plugin))  # type: ignore[arg-type]

    def forbidden_discovery() -> object:
        raise AssertionError("catalog must not perform plugin discovery")

    monkeypatch.setattr("importlib.metadata.entry_points", forbidden_discovery)
    catalog = OnlyIntegrationTypeCatalog(data_sources, brokers)

    assert catalog.list() == (declared,)
    assert catalog.list(OnlyIntegrationCategory.BROKER) == ()
    assert catalog.require("test.market_data") is declared


def test_catalog_lookup_is_exact() -> None:
    catalog = OnlyIntegrationTypeCatalog(OnlyDataSourceFactoryRegistry(), OnlyBrokerFactoryRegistry())

    for value in ("missing", "latest", "TEST.MARKET_DATA", "test"):
        with pytest.raises(OnlyIntegrationTypeCatalogError) as raised:
            catalog.require(value)
        assert raised.value.code == "INTEGRATION_TYPE_NOT_FOUND"


def test_catalog_fails_closed_on_duplicate_type_or_implementation_mismatch() -> None:
    data_sources = OnlyDataSourceFactoryRegistry()
    brokers = OnlyBrokerFactoryRegistry()
    data_plugin = _plugin("data-a", OnlyPluginType.DATA_SOURCE)
    broker_plugin = _plugin("broker-a", OnlyPluginType.BROKER)
    declared = _integration(data_plugin, "test.shared", OnlyIntegrationCategory.DATA_SOURCE)
    data_sources.register(Factory(data_plugin, declared))  # type: ignore[arg-type]
    brokers.register(
        Factory(
            broker_plugin,
            replace(
                declared,
                category=OnlyIntegrationCategory.BROKER,
                implementation_id=broker_plugin.plugin_id,
            ),
        )  # type: ignore[arg-type]
    )

    with pytest.raises(OnlyIntegrationTypeCatalogError) as duplicate:
        OnlyIntegrationTypeCatalog(data_sources, brokers)
    assert duplicate.value.code == "INTEGRATION_TYPE_CONTRACT_INVALID"

    mismatched_sources = OnlyDataSourceFactoryRegistry()
    mismatched_sources.register(
        Factory(data_plugin, replace(declared, implementation_version="9.9.9"))  # type: ignore[arg-type]
    )
    with pytest.raises(OnlyIntegrationTypeCatalogError) as mismatch:
        OnlyIntegrationTypeCatalog(mismatched_sources, OnlyBrokerFactoryRegistry())
    assert mismatch.value.code == "INTEGRATION_TYPE_CONTRACT_INVALID"


def test_all_first_party_product_data_sources_declare_unique_types_without_provider_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factories = (
        OnlyBinanceSpotDataSourceFactory(),
        OnlyBinanceUsdmDataSourceFactory(),
        OnlyMiniQmtDataSourceFactory(),
        OnlyTushareDataSourceFactory(),
    )
    data_sources = OnlyDataSourceFactoryRegistry()
    for factory in factories:
        monkeypatch.setattr(factory, "create", lambda request: pytest.fail("provider I/O path was invoked"))
        data_sources.register(factory)

    descriptors = OnlyIntegrationTypeCatalog(data_sources, OnlyBrokerFactoryRegistry()).list(
        OnlyIntegrationCategory.DATA_SOURCE
    )

    assert {descriptor.type_id.value for descriptor in descriptors} == {
        "binance.spot.market_data",
        "binance.usdm.market_data",
        "miniqmt.market_data",
        "tushare.daily.market_data",
    }
    assert len({descriptor.type_id.value for descriptor in descriptors}) == len(descriptors)
    assert all(descriptor.category is OnlyIntegrationCategory.DATA_SOURCE for descriptor in descriptors)


def test_component_agent_provider_type_is_available_without_becoming_a_plugin() -> None:
    catalog = OnlyIntegrationTypeCatalog(
        OnlyDataSourceFactoryRegistry(),
        OnlyBrokerFactoryRegistry(),
        (OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE,),
    )

    assert catalog.require("openai.compatible.agent_provider").category is OnlyIntegrationCategory.AGENT_PROVIDER

    probe = OnlyOpenAICompatibleAgentProviderProbe(lambda *_args: (200, b'{"data":[]}'))
    probe_catalog = OnlyIntegrationProbeCatalog(
        OnlyDataSourceFactoryRegistry(),
        OnlyBrokerFactoryRegistry(),
        ((OPENAI_COMPATIBLE_AGENT_PROVIDER_INTEGRATION_TYPE, probe),),
    )
    assert probe_catalog.require("openai.compatible.agent_provider") is probe
