from importlib import metadata

from onlyalpha.runtime.defaults import only_default_engine_services


def test_installed_distribution_is_discovered_through_real_entry_points() -> None:
    assert {item.name for item in metadata.entry_points().select(group="onlyalpha.data_sources")} >= {
        "test-external-data"
    }
    assert {item.name for item in metadata.entry_points().select(group="onlyalpha.brokers")} >= {"test-external-broker"}
    services = only_default_engine_services()
    assert services.data_sources.resolve("test-external-data").descriptor.plugin_id == "test-external-data"
    assert services.brokers.resolve("test-external-broker").descriptor.plugin_id == "test-external-broker"
