import json
import time

import pytest
from onlyalpha_plugin_binance.common.http import OnlyBinancePublicHttpClient
from onlyalpha_plugin_binance.spot.data_source.config import OnlyBinanceSpotDataSourceConfig
from onlyalpha_plugin_binance.spot.data_source.factory import factory
from onlyalpha_plugin_binance.spot.data_source.historical import OnlyBinanceSpotHistoricalClient
from onlyalpha_plugin_binance.spot.reference.client import OnlyBinanceSpotReferenceClient

from onlyalpha.plugin.integration import OnlyIntegrationProbeCheck
from onlyalpha.plugin.integration_probe import (
    OnlyIntegrationProbePolicy,
    OnlyIntegrationProbeRequest,
    OnlyIntegrationProbeStatus,
)


@pytest.mark.external
@pytest.mark.requires_network
@pytest.mark.requires_binance_public
@pytest.mark.parametrize(
    "configuration",
    [
        {"environment": "GLOBAL", "endpoint_profile": "PUBLIC_MARKET_DATA"},
        {"environment": "US", "endpoint_profile": "DEFAULT"},
        {"environment": "SPOT_TESTNET", "endpoint_profile": "DEFAULT"},
    ],
)
def test_current_binance_public_reference_contract(configuration: dict[str, object]) -> None:
    config = OnlyBinanceSpotDataSourceConfig.parse(configuration)
    http = OnlyBinancePublicHttpClient(config.endpoints.rest_base_url)
    client = OnlyBinanceSpotReferenceClient(http)
    assert client.ping().strip() == b"{}"
    server_time = json.loads(client.server_time())["serverTime"]
    assert json.loads(client.exchange_info(("BTCUSDT",)))["symbols"][0]["symbol"] == "BTCUSDT"
    end_ms = int(server_time) - int(server_time) % 60_000
    assert OnlyBinanceSpotHistoricalClient(http).klines("BTCUSDT", end_ms - 120_000, end_ms, 2)


@pytest.mark.external
@pytest.mark.requires_network
@pytest.mark.requires_binance_public
def test_current_binance_public_probe_contract() -> None:
    request = OnlyIntegrationProbeRequest(
        probe_attempt_id="11111111-1111-4111-8111-111111111111",
        integration_id="22222222-2222-4222-8222-222222222222",
        revision_fingerprint="a" * 64,
        type_id="binance.spot.market_data",
        type_descriptor_fingerprint="b" * 64,
        public_configuration={"environment": "LIVE", "timeout_seconds": 5.0},
        probe_configuration={"instrument": "BTCUSDT"},
        required_checks=(
            OnlyIntegrationProbeCheck.CONNECTIVITY,
            OnlyIntegrationProbeCheck.REFERENCE_DATA,
            OnlyIntegrationProbeCheck.HISTORICAL_DATA,
            OnlyIntegrationProbeCheck.REALTIME_DATA,
        ),
        probe_instrument="BTCUSDT",
        policy=OnlyIntegrationProbePolicy(total_timeout_seconds=20, per_check_timeout_seconds=5),
        deadline_monotonic=time.monotonic() + 20,
        resolved_secrets={},
    )

    assert factory.probe(request).overall_status is OnlyIntegrationProbeStatus.READY
