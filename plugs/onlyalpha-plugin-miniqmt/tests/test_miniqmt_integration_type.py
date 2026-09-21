from onlyalpha_plugin_miniqmt.config import OnlyMiniQmtConfig
from onlyalpha_plugin_miniqmt.data_source.factory import OnlyMiniQmtDataSourceFactory

from onlyalpha.plugin.integration import OnlyIntegrationCategory


def test_miniqmt_data_source_contract_maps_existing_runtime_configuration() -> None:
    factory = OnlyMiniQmtDataSourceFactory()
    descriptor = factory.integration_type
    fields = {field.field_id: field for field in descriptor.configuration_contract.fields}

    assert descriptor.type_id.value == "miniqmt.market_data"
    assert descriptor.category is OnlyIntegrationCategory.DATA_SOURCE
    assert set(fields) == {
        "userdata_mini_path",
        "account_id",
        "reconnect_max_attempts",
        "reconnect_initial_delay",
        "queue_capacity",
        "cache_policy",
    }
    defaults = OnlyMiniQmtConfig()
    assert fields["userdata_mini_path"].default == str(defaults.userdata_mini_path)
    assert fields["account_id"].default == defaults.account_id
    assert fields["reconnect_max_attempts"].default == defaults.reconnect_max_attempts
    assert fields["reconnect_initial_delay"].default == defaults.reconnect_initial_delay
    assert fields["queue_capacity"].default == defaults.queue_capacity
    assert fields["cache_policy"].default == defaults.cache_policy.value
    assert factory.parse_config({}) == defaults
