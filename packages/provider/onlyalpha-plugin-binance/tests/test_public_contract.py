from datetime import UTC, datetime

import pytest
from onlyalpha_plugin_binance.common.environment import OnlyBinanceEnvironment
from onlyalpha_plugin_binance.common.http import OnlyBinancePublicHttpClient
from onlyalpha_plugin_binance.spot.reference.capture import OnlyBinanceSpotReferenceCapture
from onlyalpha_plugin_binance.spot.reference.client import OnlyBinanceSpotReferenceClient


@pytest.mark.external
@pytest.mark.requires_network
@pytest.mark.requires_binance_public
def test_current_binance_public_reference_contract() -> None:
    client = OnlyBinanceSpotReferenceClient(OnlyBinancePublicHttpClient(OnlyBinanceEnvironment.LIVE.rest_base_url))
    assert client.ping().strip() == b"{}"
    assert b"serverTime" in client.server_time()
    capture = OnlyBinanceSpotReferenceCapture.create(
        client.exchange_info(("BTCUSDT", "ETHUSDT")), client.execution_rules(("BTCUSDT", "ETHUSDT")), datetime.now(UTC)
    )
    assert {item.raw_symbol for item in capture.authority.references} == {"BTCUSDT", "ETHUSDT"}
