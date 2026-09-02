from __future__ import annotations

from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest
from onlyalpha_plugin_binance.common.private_http import (
    OnlyBinanceCredentials,
    OnlyBinanceDispatchKnowledge,
    OnlyBinanceHttpResponse,
    OnlyBinancePrivateHttpClient,
    OnlyBinancePrivateRequestError,
    only_binance_hmac_sha256,
)
from onlyalpha_plugin_binance.spot.broker.codec import only_binance_client_order_id
from onlyalpha_plugin_binance.spot.broker.normalize import (
    only_normalize_binance_spot_balances,
    only_normalize_binance_spot_order,
)
from onlyalpha_plugin_binance.spot.broker.rest import OnlyBinanceSpotPrivateRestClient

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerRequestId
from onlyalpha.broker.models import OnlyBrokerCancelRequest, OnlyBrokerOrderRequest
from onlyalpha.domain.enums import (
    OnlyCurrencyType,
    OnlyOffset,
    OnlyOrderSide,
    OnlyOrderStatus,
    OnlyOrderType,
    OnlyTimeInForce,
)
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClientOrderId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyVenueOrderId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyPrice, OnlyQuantity


class _Transport:
    def __init__(self, response: OnlyBinanceHttpResponse | None = None) -> None:
        self.response = response or OnlyBinanceHttpResponse(200, {"Content-Type": "application/json"}, b"{}")
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def __call__(self, method, url, headers, _timeout_seconds, _max_response_bytes):
        self.calls.append((method, url, dict(headers)))
        return self.response


def _order(symbol: str, *, market: bool = False) -> OnlyBrokerOrderRequest:
    return OnlyBrokerOrderRequest(
        OnlyBrokerRequestId(f"submit-{symbol}"),
        OnlyOrderId(f"order-{symbol}"),
        OnlyClientOrderId(f"client-{symbol}"),
        OnlyAccountId("spot-testnet"),
        OnlyInstrumentId.parse(f"{symbol}.BINANCE"),
        OnlyOrderSide.BUY,
        OnlyOffset.OPEN,
        OnlyOrderType.MARKET if market else OnlyOrderType.LIMIT,
        OnlyTimeInForce.GTC,
        OnlyQuantity(Decimal("0.01000000"), 8),
        None if market else OnlyPrice(Decimal("25000.10"), 2),
        OnlyTimestamp.from_unix_nanos(1_000_000_000),
    )


def _client(transport: _Transport, observed=None) -> OnlyBinancePrivateHttpClient:
    return OnlyBinancePrivateHttpClient(
        "https://testnet.binance.vision",
        OnlyBinanceCredentials("api-key-value", "secret-value"),
        lambda: 1000,
        transport=transport,
        response_observer=observed,
    )


def test_signature_and_private_request_are_deterministic_and_secret_safe() -> None:
    assert (
        only_binance_hmac_sha256("secret-value", "recvWindow=5000&symbol=BTCUSDT&timestamp=1000")
        == "3669540deb37f37c237d516b9124b86e2220f007228afb67198cf7b629c4766c"
    )
    transport = _Transport()
    observed: list[tuple[str, str, int, bytes]] = []
    client = _client(transport, lambda method, path, status, payload: observed.append((method, path, status, payload)))
    client.request_json("GET", "/api/v3/order", {"symbol": "BTCUSDT"})
    method, url, headers = transport.calls[0]
    assert method == "GET" and headers["X-MBX-APIKEY"] == "api-key-value"
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert query["recvWindow"] == ["5000"] and query["timestamp"] == ["1000"]
    assert query["signature"] == ["3669540deb37f37c237d516b9124b86e2220f007228afb67198cf7b629c4766c"]
    assert observed == [("GET", "/api/v3/order", 200, b"{}")]
    assert "api-key-value" not in repr(OnlyBinanceCredentials("api-key-value", "secret-value"))
    assert "secret-value" not in repr(OnlyBinanceCredentials("api-key-value", "secret-value"))


def test_private_rest_endpoint_mapping_supports_btc_eth_market_limit_query_and_cancel() -> None:
    transport = _Transport()
    rest = OnlyBinanceSpotPrivateRestClient(_client(transport))
    rest.authenticate_account()
    rest.submit_order(_order("BTCUSDT"))
    rest.submit_order(_order("ETHUSDT", market=True))
    rest.query_order(symbol="BTCUSDT", client_order_id=OnlyClientOrderId("client-BTCUSDT"))
    rest.open_orders(symbol="ETHUSDT")
    rest.trades(symbol="BTCUSDT", venue_order_id=OnlyVenueOrderId("123"))
    rest.cancel_order(
        OnlyBrokerCancelRequest(
            OnlyBrokerRequestId("cancel-1"),
            OnlyAccountId("spot-testnet"),
            OnlyOrderId("order-BTCUSDT"),
            None,
            OnlyTimestamp.from_unix_nanos(2_000_000_000),
            OnlyClientOrderId("client-BTCUSDT"),
        ),
        symbol="BTCUSDT",
    )
    calls = [(method, urlparse(url).path, parse_qs(urlparse(url).query)) for method, url, _headers in transport.calls]
    assert [item[:2] for item in calls] == [
        ("GET", "/api/v3/account"),
        ("POST", "/api/v3/order"),
        ("POST", "/api/v3/order"),
        ("GET", "/api/v3/order"),
        ("GET", "/api/v3/openOrders"),
        ("GET", "/api/v3/myTrades"),
        ("DELETE", "/api/v3/order"),
    ]
    assert calls[1][2]["symbol"] == ["BTCUSDT"] and calls[1][2]["price"] == ["25000.10"]
    assert calls[2][2]["symbol"] == ["ETHUSDT"] and "price" not in calls[2][2]
    assert calls[-1][2]["origClientOrderId"] == ["client-BTCUSDT"]


def test_long_client_identity_has_stable_wire_representation() -> None:
    identity = OnlyClientOrderId("runtime-with-a-very-long-identity-CLIENT-000001")
    encoded = only_binance_client_order_id(identity)
    assert encoded == only_binance_client_order_id(identity)
    assert len(encoded) == 35 and encoded.startswith("oa_")
    assert encoded != only_binance_client_order_id(OnlyClientOrderId(identity.value + "x"))


def test_known_provider_error_is_sanitized_and_transport_uncertainty_is_explicit() -> None:
    known = _Transport(
        OnlyBinanceHttpResponse(
            400,
            {"Content-Type": "application/json"},
            b'{"code":-2010,"msg":"secret account detail"}',
        )
    )
    with pytest.raises(OnlyBinancePrivateRequestError) as caught:
        _client(known).request_json("POST", "/api/v3/order", {"symbol": "BTCUSDT"})
    assert caught.value.knowledge is OnlyBinanceDispatchKnowledge.KNOWN_RESULT
    assert str(caught.value) == "BINANCE_PRIVATE_KNOWN_ERROR: -2010"
    assert "secret account detail" not in str(caught.value)

    def lost(*_args, **_kwargs):
        raise TimeoutError("credentials must not leak")

    uncertain = OnlyBinancePrivateHttpClient(
        "https://testnet.binance.vision",
        OnlyBinanceCredentials("api-key-value", "secret-value"),
        lambda: 1000,
        transport=lost,
    )
    with pytest.raises(OnlyBinancePrivateRequestError) as unknown:
        uncertain.request_json("POST", "/api/v3/order", {"symbol": "BTCUSDT"})
    assert unknown.value.knowledge is OnlyBinanceDispatchKnowledge.UNKNOWN
    assert "credentials" not in str(unknown.value) and "secret-value" not in str(unknown.value)


@pytest.mark.parametrize(
    ("status", "payload"),
    (
        (500, b'{"code":-1000,"msg":"internal"}'),
        (503, b'{"code":-1000,"msg":"unavailable"}'),
        (400, b'{"code":-1007,"msg":"timeout"}'),
        (400, b'{"code":-1006,"msg":"unexpected"}'),
    ),
)
def test_side_effecting_ambiguous_responses_are_execution_unknown(status: int, payload: bytes) -> None:
    with pytest.raises(OnlyBinancePrivateRequestError) as caught:
        _client(_Transport(OnlyBinanceHttpResponse(status, {}, payload))).request_json(
            "POST",
            "/api/v3/order",
            {"symbol": "BTCUSDT"},
            side_effecting=True,
        )
    assert caught.value.knowledge is OnlyBinanceDispatchKnowledge.UNKNOWN


def test_side_effecting_definitive_request_rejection_is_known() -> None:
    with pytest.raises(OnlyBinancePrivateRequestError) as caught:
        _client(
            _Transport(OnlyBinanceHttpResponse(400, {}, b'{"code":-1102,"msg":"mandatory parameter missing"}'))
        ).request_json(
            "POST",
            "/api/v3/order",
            {"symbol": "BTCUSDT"},
            side_effecting=True,
        )
    assert caught.value.knowledge is OnlyBinanceDispatchKnowledge.KNOWN_RESULT


def test_recorded_private_payloads_normalize_at_plugin_boundary() -> None:
    currencies = {
        "BTC": OnlyCurrency("BTC", 8, OnlyCurrencyType.CRYPTO),
        "USDT": OnlyCurrency("USDT", 8, OnlyCurrencyType.CRYPTO),
    }
    balances = only_normalize_binance_spot_balances(
        b'{"makerCommission":10,"canTrade":true,"balances":['
        b'{"asset":"USDT","free":"100.00000000","locked":"2.00000000"},'
        b'{"asset":"BTC","free":"0.01000000","locked":"0.00000000"}]}',
        currencies,
    )
    assert [item.currency.code for item in balances] == ["BTC", "USDT"]
    assert balances[1].ledger_cash.amount == Decimal("102.00000000")
    request = _order("BTCUSDT")
    order = only_normalize_binance_spot_order(
        b'{"symbol":"BTCUSDT","orderId":12345,"clientOrderId":"client-BTCUSDT",'
        b'"price":"25000.10","origQty":"0.01000000","executedQty":"0.00400000",'
        b'"status":"PARTIALLY_FILLED","timeInForce":"GTC","type":"LIMIT","side":"BUY",'
        b'"updateTime":1700000000123}',
        request,
        gateway_id=OnlyBrokerGatewayId("binance-spot-testnet"),
        source_sequence=7,
    )
    assert order.status is OnlyOrderStatus.PARTIALLY_FILLED
    assert str(order.venue_order_id) == "12345" and order.source_sequence == 7
