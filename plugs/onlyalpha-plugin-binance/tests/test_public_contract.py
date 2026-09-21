import time
from datetime import UTC, datetime

import pytest
from onlyalpha_plugin_binance.common.environment import OnlyBinanceEnvironment
from onlyalpha_plugin_binance.common.http import OnlyBinancePublicHttpClient
from onlyalpha_plugin_binance.spot.data_source.factory import factory
from onlyalpha_plugin_binance.spot.reference.capture import OnlyBinanceSpotReferenceCapture
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
def test_current_binance_public_reference_contract() -> None:
    client = OnlyBinanceSpotReferenceClient(OnlyBinancePublicHttpClient(OnlyBinanceEnvironment.LIVE.rest_base_url))
    assert client.ping().strip() == b"{}"
    assert b"serverTime" in client.server_time()
    capture = OnlyBinanceSpotReferenceCapture.create(
        client.exchange_info(("BTCUSDT", "ETHUSDT")), client.execution_rules(("BTCUSDT", "ETHUSDT")), datetime.now(UTC)
    )
    assert {item.raw_symbol for item in capture.authority.references} == {"BTCUSDT", "ETHUSDT"}


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
