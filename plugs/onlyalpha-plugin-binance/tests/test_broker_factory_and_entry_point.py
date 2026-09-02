from __future__ import annotations

import importlib.metadata
import logging
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from onlyalpha_plugin_binance.common.private_http import OnlyBinanceHttpResponse
from onlyalpha_plugin_binance.spot.broker_factory import (
    OnlyBinanceSpotBrokerFactory,
    OnlyBinanceSpotBrokerResource,
)

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.inbound import OnlyBoundedBrokerInboundQueue
from onlyalpha.broker.reconciliation import OnlyDurableBrokerCommandEvidenceStore
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.plugin.broker import OnlyBrokerCreateRequest
from onlyalpha.plugin.capabilities import OnlyBrokerPluginCapabilities
from onlyalpha.plugin.lifecycle import OnlyPluginLifecycleState


class _UserStreamTransport:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.closed = False

    def connect(self, _url, _on_message, _on_disconnect) -> None:
        return None

    def send(self, payload: bytes) -> None:
        self.sent.append(payload)

    def close(self) -> None:
        self.closed = True


def _private_transport(method, _url, _headers, _timeout, _maximum):
    assert method == "GET"
    return OnlyBinanceHttpResponse(200, {}, b'{"balances":[],"canTrade":true}')


def test_binance_spot_broker_entry_point_discovers_real_factory() -> None:
    matches = {item.name: item for item in importlib.metadata.entry_points(group="onlyalpha.brokers")}
    assert "binance-spot" in matches
    loaded = matches["binance-spot"].load()
    factory = loaded()
    assert isinstance(factory, OnlyBinanceSpotBrokerFactory)
    assert factory.descriptor.plugin_id == "binance-spot"


def test_factory_parse_validate_create_and_lifecycle(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ONLYALPHA_BINANCE_TESTNET_API_KEY", "testnet-key")
    monkeypatch.setenv("ONLYALPHA_BINANCE_TESTNET_API_SECRET", "testnet-secret")
    stream_transport = _UserStreamTransport()
    factory = OnlyBinanceSpotBrokerFactory(
        private_transport=_private_transport,
        user_stream_transport=lambda: stream_transport,
    )
    config = factory.parse_config(
        {
            "environment": "SPOT_TESTNET",
            "currencies": {"BTC": 8, "ETH": 8, "USDT": 8},
        }
    )
    request = OnlyBrokerCreateRequest(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        plugin_config=config,
        runtime_type="LIVE",
        requested_capabilities=OnlyBrokerPluginCapabilities(
            submit_order=True,
            cancel_order=True,
            query_orders=True,
            query_trades=True,
            live_execution=True,
        ),
        clock=OnlyBacktestClock(datetime(2026, 8, 31, tzinfo=UTC)),
        event_bus=OnlyEventBus(),
        broker_inbound_queue=OnlyBoundedBrokerInboundQueue(16),
        runtime_id=OnlyRuntimeId("runtime"),
        account_id=OnlyAccountId("spot-testnet"),
        initial_cash=OnlyMoney(Decimal("1000"), OnlyCurrency("USDT", 8)),
        logger=logging.getLogger("test-binance-factory"),
        command_evidence_store=OnlyDurableBrokerCommandEvidenceStore((tmp_path / "broker-commands.jsonl").resolve()),
    )
    assert factory.validate_request(request) == ()
    component = factory.create(request)
    assert isinstance(component.resource, OnlyBinanceSpotBrokerResource)
    component.resource.initialize()
    component.resource.connect()
    component.resource.start()
    assert component.resource.state is OnlyPluginLifecycleState.RUNNING
    assert stream_transport.sent
    component.resource.close()
    assert component.resource.state is OnlyPluginLifecycleState.STOPPED
    assert stream_transport.closed


def test_factory_requires_runtime_owned_durable_command_port(monkeypatch) -> None:
    monkeypatch.setenv("ONLYALPHA_BINANCE_TESTNET_API_KEY", "testnet-key")
    monkeypatch.setenv("ONLYALPHA_BINANCE_TESTNET_API_SECRET", "testnet-secret")
    factory = OnlyBinanceSpotBrokerFactory()
    config = factory.parse_config({"environment": "SPOT_TESTNET", "currencies": {"USDT": 8}})
    request = OnlyBrokerCreateRequest(
        OnlyBrokerGatewayId("binance-testnet"),
        config,
        "LIVE",
        OnlyBrokerPluginCapabilities(live_execution=True),
        OnlyBacktestClock(datetime(2026, 8, 31, tzinfo=UTC)),
        OnlyEventBus(),
        OnlyBoundedBrokerInboundQueue(4),
        OnlyRuntimeId("runtime"),
        OnlyAccountId("spot-testnet"),
        OnlyMoney(Decimal("1"), OnlyCurrency("USDT", 8)),
        logging.getLogger("test-binance-factory"),
    )
    assert {item.code for item in factory.validate_request(request)} == {"BROKER_COMMAND_DURABILITY_REQUIRED"}


@pytest.mark.parametrize(
    ("rest_url", "websocket_url"),
    (
        ("https://api.binance.com", "wss://ws-api.testnet.binance.vision/ws-api/v3"),
        ("https://testnet.binance.vision", "wss://ws-api.binance.com/ws-api/v3"),
    ),
)
def test_testnet_factory_hard_fails_mainnet_hosts(rest_url: str, websocket_url: str) -> None:
    with pytest.raises(ValueError, match="MAINNET_ENDPOINT_FORBIDDEN"):
        OnlyBinanceSpotBrokerFactory().parse_config(
            {
                "environment": "SPOT_TESTNET",
                "rest_base_url": rest_url,
                "websocket_api_base_url": websocket_url,
                "currencies": {"USDT": 8},
            }
        )


def test_testnet_factory_rejects_non_testnet_credential_names() -> None:
    with pytest.raises(ValueError, match="DEDICATED_CREDENTIAL_ENV_REQUIRED"):
        OnlyBinanceSpotBrokerFactory().parse_config(
            {
                "environment": "SPOT_TESTNET",
                "api_key_env": "ONLYALPHA_BINANCE_API_KEY",
                "api_secret_env": "ONLYALPHA_BINANCE_API_SECRET",
                "currencies": {"USDT": 8},
            }
        )
