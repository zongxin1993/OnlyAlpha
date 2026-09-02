from __future__ import annotations

import json
import queue
import threading
from decimal import Decimal

from onlyalpha_plugin_binance.common.private_http import (
    OnlyBinanceCredentials,
    only_binance_hmac_sha256,
)
from onlyalpha_plugin_binance.spot.broker.stream import (
    OnlyBinanceResolvedOrderIdentity,
    OnlyBinanceSpotUserStream,
    OnlyBinanceSpotUserStreamNormalizer,
    OnlyBinanceThreadedUserStreamTransport,
    OnlyBinanceUserStreamTrust,
)

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.inbound import OnlyBoundedBrokerInboundQueue
from onlyalpha.broker.updates import (
    OnlyBrokerBalancesUpdate,
    OnlyBrokerOrderAcceptedUpdate,
    OnlyBrokerOrderCancelledUpdate,
    OnlyBrokerTradeUpdate,
)
from onlyalpha.domain.enums import OnlyCurrencyType
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClientOrderId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyVenueOrderId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency


class _WebSocket:
    def __init__(self) -> None:
        self.url = ""
        self.on_message = None
        self.on_disconnect = None
        self.closed = False
        self.sent: list[bytes] = []

    def connect(self, url, on_message, on_disconnect) -> None:
        self.url = url
        self.on_message = on_message
        self.on_disconnect = on_disconnect

    def close(self) -> None:
        self.closed = True

    def send(self, payload: bytes) -> None:
        self.sent.append(payload)

    def emit(self, payload: bytes) -> None:
        assert self.on_message is not None
        self.on_message(payload)

    def lose(self) -> None:
        assert self.on_disconnect is not None
        self.on_disconnect("controlled disconnect")


class _Connection:
    def __init__(self) -> None:
        self.received: queue.Queue[str | bytes] = queue.Queue()
        self.sent: list[str] = []
        self.closed = threading.Event()

    def recv(self) -> str | bytes:
        value = self.received.get()
        if value == b"<closed>":
            raise OSError("closed")
        return value

    def send(self, payload: str) -> object:
        self.sent.append(payload)
        return len(payload)

    def close(self) -> None:
        self.closed.set()
        self.received.put(b"<closed>")


def _normalizer() -> OnlyBinanceSpotUserStreamNormalizer:
    identity = OnlyBinanceResolvedOrderIdentity(OnlyOrderId("order-1"), OnlyClientOrderId("client-BTCUSDT"))
    return OnlyBinanceSpotUserStreamNormalizer(
        runtime_id=OnlyRuntimeId("runtime"),
        gateway_id=OnlyBrokerGatewayId("binance-spot-testnet"),
        account_id=OnlyAccountId("spot-testnet"),
        identities=lambda wire, venue: (
            identity
            if (wire, venue) == ("client-BTCUSDT", "12345")
            else (_ for _ in ()).throw(KeyError("identity conflict"))
        ),
        currencies={
            "BTC": OnlyCurrency("BTC", 8, OnlyCurrencyType.CRYPTO),
            "USDT": OnlyCurrency("USDT", 8, OnlyCurrencyType.CRYPTO),
        },
        received_at=lambda: OnlyTimestamp.from_unix_nanos(1_700_000_001_000_000_000),
    )


def test_execution_report_and_balance_events_normalize_to_canonical_inbound_updates() -> None:
    normalizer = _normalizer()
    accepted_payload = (
        b'{"e":"executionReport","E":1700000000000,"s":"BTCUSDT","c":"client-BTCUSDT",'
        b'"C":"","S":"BUY","o":"LIMIT","f":"GTC","q":"0.01000000","p":"25000.10",'
        b'"x":"NEW","X":"NEW","r":"NONE","i":12345,"l":"0.00000000","z":"0.00000000",'
        b'"L":"0.00000000","T":1700000000000,"t":-1,"m":false}'
    )
    first = normalizer.normalize(accepted_payload, 1)
    duplicate = normalizer.normalize(accepted_payload, 2)
    assert isinstance(first, OnlyBrokerOrderAcceptedUpdate)
    assert first.update_id == duplicate.update_id and first.source_sequence != duplicate.source_sequence

    trade = normalizer.normalize(
        b'{"e":"executionReport","E":1700000000100,"s":"BTCUSDT","c":"client-BTCUSDT",'
        b'"C":"","x":"TRADE","X":"PARTIALLY_FILLED","i":12345,"l":"0.00400000",'
        b'"L":"25010.00","T":1700000000090,"t":777,"m":true}',
        3,
    )
    assert isinstance(trade, OnlyBrokerTradeUpdate)
    assert trade.fill.quantity.value == Decimal("0.00400000") and str(trade.fill.venue_trade_id) == "777"

    balances = normalizer.normalize(
        b'{"e":"outboundAccountPosition","E":1700000000200,"u":1700000000190,'
        b'"B":[{"a":"USDT","f":"100.00000000","l":"2.00000000"},'
        b'{"a":"BTC","f":"0.01000000","l":"0.00000000"}]}',
        4,
    )
    assert isinstance(balances, OnlyBrokerBalancesUpdate)
    assert [item.currency.code for item in balances.snapshots] == ["BTC", "USDT"]


def test_provider_clock_ahead_is_explicit_and_preserves_causal_timestamp_invariant() -> None:
    identity = OnlyBinanceResolvedOrderIdentity(OnlyOrderId("order-1"), OnlyClientOrderId("client-BTCUSDT"))
    normalizer = OnlyBinanceSpotUserStreamNormalizer(
        runtime_id=OnlyRuntimeId("runtime"),
        gateway_id=OnlyBrokerGatewayId("binance-spot-testnet"),
        account_id=OnlyAccountId("spot-testnet"),
        identities=lambda _wire, _venue: identity,
        currencies={},
        received_at=lambda: OnlyTimestamp.from_unix_nanos(1_699_999_999_000_000_000),
    )

    update = normalizer.normalize(
        b'{"e":"executionReport","E":1700000000000,"s":"BTCUSDT","c":"client-BTCUSDT","x":"NEW","X":"NEW","i":12345}',
        1,
    )

    assert update.ts_init == update.ts_event
    assert update.quality_flags == ("PROVIDER_SEQUENCE_UNAVAILABLE", "PROVIDER_CLOCK_AHEAD")


def test_disconnect_and_reconnect_never_restore_trust_without_reconciliation() -> None:
    websocket = _WebSocket()
    inbound = OnlyBoundedBrokerInboundQueue(8)
    acknowledged = threading.Event()
    stream = OnlyBinanceSpotUserStream(
        websocket_base_url="wss://ws-api.testnet.binance.vision/ws-api/v3",
        transport=websocket,
        normalizer=_normalizer(),
        inbound=inbound,
        credentials=OnlyBinanceCredentials("api-key", "secret-key"),
        timestamp_ms=lambda: 1_700_000_000_000,
        on_subscription_acknowledged=acknowledged.set,
    )
    stream.connect("subscribe-one")
    assert stream.trust is OnlyBinanceUserStreamTrust.CONNECTED_UNTRUSTED
    assert websocket.url == "wss://ws-api.testnet.binance.vision/ws-api/v3"
    subscription = json.loads(websocket.sent[-1])
    assert subscription["method"] == "userDataStream.subscribe.signature"
    params = subscription["params"]
    assert params["signature"] == only_binance_hmac_sha256(
        "secret-key",
        "apiKey=api-key&recvWindow=5000&timestamp=1700000000000",
    )
    websocket.emit(b'{"id":"subscribe-one","status":200,"result":{"subscriptionId":7}}')
    assert acknowledged.is_set()
    stream.mark_reconciled()
    assert stream.trust is OnlyBinanceUserStreamTrust.TRUSTED
    websocket.lose()
    assert stream.trust is OnlyBinanceUserStreamTrust.RECONCILIATION_REQUIRED
    stream.connect("subscribe-two")
    assert stream.trust is OnlyBinanceUserStreamTrust.CONNECTED_UNTRUSTED
    websocket.emit(b'{"id":"subscribe-two","status":200,"result":{"subscriptionId":8}}')
    websocket.emit(
        b'{"subscriptionId":8,"event":{"e":"executionReport","E":1700000000000,'
        b'"s":"BTCUSDT","c":"client-BTCUSDT","x":"NEW","X":"NEW","i":12345}}'
    )
    assert len(inbound) == 1
    assert stream.trust is OnlyBinanceUserStreamTrust.CONNECTED_UNTRUSTED


def test_threaded_transport_has_bounded_receive_send_and_controlled_close() -> None:
    connection = _Connection()
    reconnected = _Connection()
    connections = iter((connection, reconnected))
    received: list[bytes] = []
    delivered = threading.Event()
    disconnected = threading.Event()
    transport = OnlyBinanceThreadedUserStreamTransport(
        timeout_seconds=1,
        max_message_bytes=4,
        connection_factory=lambda url, timeout: next(connections),
    )
    transport.connect(
        "wss://ws-api.testnet.binance.vision/ws-api/v3",
        lambda payload: (received.append(payload), delivered.set()),
        lambda reason: disconnected.set(),
    )
    transport.send(b"ping")
    connection.received.put("data")
    assert delivered.wait(1)
    assert received == [b"data"] and connection.sent == ["ping"]

    connection.received.put(b"oversized")
    assert disconnected.wait(1)
    transport.connect(
        "wss://ws-api.testnet.binance.vision/ws-api/v3",
        lambda payload: None,
        lambda reason: None,
    )
    transport.close()
    assert connection.closed.is_set() and reconnected.closed.is_set()


def test_cancel_and_fill_race_remain_separate_authoritative_venue_facts() -> None:
    normalizer = _normalizer()
    cancelled = normalizer.normalize(
        b'{"e":"executionReport","E":1700000000200,"s":"BTCUSDT",'
        b'"c":"client-BTCUSDT","C":"","x":"CANCELED","X":"CANCELED","i":12345}',
        1,
    )
    filled = normalizer.normalize(
        b'{"e":"executionReport","E":1700000000300,"s":"BTCUSDT",'
        b'"c":"client-BTCUSDT","C":"","x":"TRADE","X":"FILLED","i":12345,'
        b'"l":"0.00600000","L":"25020.00","T":1700000000290,"t":778,"m":false}',
        2,
    )
    assert isinstance(cancelled, OnlyBrokerOrderCancelledUpdate)
    assert isinstance(filled, OnlyBrokerTradeUpdate)
    assert cancelled.update_id != filled.update_id
    assert filled.fill.venue_order_id == OnlyVenueOrderId("12345")


def test_cancel_event_correlates_with_original_client_order_identity() -> None:
    normalizer = _normalizer()

    cancelled = normalizer.normalize(
        b'{"e":"executionReport","E":1700000000200,"s":"BTCUSDT",'
        b'"c":"venue-generated-cancel-id","C":"client-BTCUSDT",'
        b'"x":"CANCELED","X":"CANCELED","i":12345}',
        1,
    )

    assert isinstance(cancelled, OnlyBrokerOrderCancelledUpdate)
    assert cancelled.order_id == OnlyOrderId("order-1")
