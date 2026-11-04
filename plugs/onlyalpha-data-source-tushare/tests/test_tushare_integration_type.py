import pytest
from onlyalpha_plugin_tushare.data_source.factory import OnlyTushareDataSourceFactory
from onlyalpha_plugin_tushare.errors import OnlyTushareError

from onlyalpha.plugin.integration import OnlyIntegrationCategory


def test_tushare_declares_non_binance_market_data_and_semantic_token_requirement() -> None:
    factory = OnlyTushareDataSourceFactory()
    descriptor = factory.integration_type
    fields = {field.field_id: field for field in descriptor.configuration_contract.fields}

    assert descriptor.type_id.value == "tushare.daily.market_data"
    assert descriptor.category is OnlyIntegrationCategory.DATA_SOURCE
    assert fields["token"].secret is True and fields["token"].default is None
    assert "token_env" not in fields
    assert not ({"symbols", "universe", "subscription_list"} & set(fields))
    with pytest.raises(OnlyTushareError, match="unknown fields"):
        factory.parse_config({"future_product_field": True})
