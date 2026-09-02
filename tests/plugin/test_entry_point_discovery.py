from importlib import metadata

from onlyalpha.plugin.api import OnlyMarketProductPluginId
from onlyalpha.runtime.defaults import only_default_engine_services


def test_installed_distribution_is_discovered_through_real_entry_points() -> None:
    assert {item.name for item in metadata.entry_points().select(group="onlyalpha.calculations")} >= {
        "standard-indicators",
        "official-factors",
        "official-targets",
    }
    assert {item.name for item in metadata.entry_points().select(group="onlyalpha.data_sources")} >= {
        "test-external-data"
    }
    assert {item.name for item in metadata.entry_points().select(group="onlyalpha.brokers")} >= {"test-external-broker"}
    assert {item.name for item in metadata.entry_points().select(group="onlyalpha.broker_fee_contracts")} >= {
        "test-external-broker-simulation-zero",
        "virtual-simulation-zero",
    }
    assert {item.name for item in metadata.entry_points().select(group="onlyalpha.market_products")} >= {
        "generic-t0-cash"
    }
    services = only_default_engine_services()
    assert (
        services.assembler.components.data_sources.resolve("test-external-data").descriptor.plugin_id
        == "test-external-data"
    )
    assert (
        services.assembler.components.brokers.resolve("test-external-broker").descriptor.plugin_id
        == "test-external-broker"
    )
    assert (
        str(
            services.assembler.components.market_products.require(
                OnlyMarketProductPluginId("onlyalpha-plugin-generic-t0-cash")
            ).plugin_id
        )
        == "onlyalpha-plugin-generic-t0-cash"
    )
    assert (
        services.assembler.components.broker_fee_contracts.require(
            "TEST_EXTERNAL_BROKER_SIMULATION_ZERO_BROKER_FEES", "1"
        ).broker_id
        == "test-external-broker"
    )
