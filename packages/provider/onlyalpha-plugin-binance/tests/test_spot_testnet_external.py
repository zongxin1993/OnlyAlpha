from __future__ import annotations

import json
import os
import re
import threading
import time
from decimal import ROUND_DOWN, ROUND_UP, Decimal

import pytest
from onlyalpha_plugin_binance.common.private_http import (
    OnlyBinanceCredentials,
    OnlyBinancePrivateHttpClient,
)
from onlyalpha_plugin_binance.spot.broker.codec import only_binance_client_order_id
from onlyalpha_plugin_binance.spot.broker.rest import OnlyBinanceSpotPrivateRestClient
from onlyalpha_plugin_binance.spot.broker.stream import (
    OnlyBinanceResolvedOrderIdentity,
    OnlyBinanceSpotUserStream,
    OnlyBinanceSpotUserStreamNormalizer,
    OnlyBinanceThreadedUserStreamTransport,
)

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerRequestId
from onlyalpha.broker.models import OnlyBrokerCancelRequest, OnlyBrokerOrderRequest
from onlyalpha.broker.updates import OnlyBrokerInboundUpdate, OnlyBrokerTradeUpdate
from onlyalpha.domain.enums import (
    OnlyCurrencyType,
    OnlyOffset,
    OnlyOrderSide,
    OnlyOrderType,
    OnlyTimeInForce,
)
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClientOrderId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyVenueOrderId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyPrice, OnlyQuantity

pytestmark = [
    pytest.mark.external,
    pytest.mark.requires_network,
]

_TESTNET_REST_HOST = "https://testnet.binance.vision"
_TESTNET_WS_HOST = "wss://ws-api.testnet.binance.vision/ws-api/v3"
_REQUIRED_SYMBOLS = ("BTCUSDT", "ETHUSDT")


class _SignalledInbound:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._updates: list[OnlyBrokerInboundUpdate] = []

    def put(self, update: OnlyBrokerInboundUpdate) -> None:
        with self._condition:
            self._updates.append(update)
            self._condition.notify_all()

    def wait_for_trade(self, order_id: OnlyOrderId, timeout_seconds: float = 15.0) -> OnlyBrokerTradeUpdate:
        with self._condition:
            found = self._find_trade(order_id)
            if found is None:
                self._condition.wait_for(lambda: self._find_trade(order_id) is not None, timeout_seconds)
                found = self._find_trade(order_id)
        if found is None:
            raise AssertionError("BINANCE_TESTNET_USER_STREAM_TRADE_NOT_OBSERVED")
        return found

    def _find_trade(self, order_id: OnlyOrderId) -> OnlyBrokerTradeUpdate | None:
        return next(
            (
                update
                for update in self._updates
                if isinstance(update, OnlyBrokerTradeUpdate) and update.order_id == order_id
            ),
            None,
        )


def _required_environment() -> tuple[str, str, str, str, str]:
    key = os.environ.get("ONLYALPHA_BINANCE_TESTNET_API_KEY", "")
    secret = os.environ.get("ONLYALPHA_BINANCE_TESTNET_API_SECRET", "")
    rest_url = os.environ.get("ONLYALPHA_BINANCE_TESTNET_REST_BASE_URL", _TESTNET_REST_HOST).rstrip("/")
    websocket_url = os.environ.get("ONLYALPHA_BINANCE_TESTNET_WS_BASE_URL", _TESTNET_WS_HOST).rstrip("/")
    run_id = os.environ.get("ONLYALPHA_BINANCE_TESTNET_RUN_ID", "")
    if rest_url != _TESTNET_REST_HOST or websocket_url != _TESTNET_WS_HOST:
        pytest.fail("BINANCE_TESTNET_MAINNET_ENDPOINT_FORBIDDEN", pytrace=False)
    if not key or not secret or not re.fullmatch(r"[A-Za-z0-9]{1,8}", run_id):
        pytest.fail("BINANCE_TESTNET_DEDICATED_CREDENTIALS_AND_RUN_ID_REQUIRED", pytrace=False)
    return key, secret, rest_url, websocket_url, run_id


def _json_object(payload: bytes) -> dict[str, object]:
    value = json.loads(payload)
    assert isinstance(value, dict)
    return value


def _filter(symbol: dict[str, object], filter_type: str) -> dict[str, object]:
    filters = symbol.get("filters")
    assert isinstance(filters, list)
    match = next(
        (item for item in filters if isinstance(item, dict) and item.get("filterType") == filter_type),
        None,
    )
    assert isinstance(match, dict), f"BINANCE_TESTNET_{filter_type}_FILTER_REQUIRED"
    return match


def _aligned(value: Decimal, step: Decimal, rounding: str) -> Decimal:
    return ((value / step).to_integral_value(rounding=rounding) * step).quantize(step)


def _precision(step: Decimal) -> int:
    exponent = step.as_tuple().exponent
    assert isinstance(exponent, int)
    return max(0, -exponent)


def _request(
    *,
    symbol: str,
    run_id: str,
    suffix: str,
    quantity: Decimal,
    quantity_precision: int,
    price: Decimal | None,
    price_precision: int,
    now: OnlyTimestamp,
) -> OnlyBrokerOrderRequest:
    identity = f"oa-p94a-{run_id}-{symbol[:3]}-{suffix}"
    order_type = OnlyOrderType.MARKET if price is None else OnlyOrderType.LIMIT
    return OnlyBrokerOrderRequest(
        OnlyBrokerRequestId(f"request-{identity}"),
        OnlyOrderId(f"order-{identity}"),
        OnlyClientOrderId(identity),
        OnlyAccountId("binance-spot-testnet"),
        OnlyInstrumentId.parse(f"{symbol}.BINANCE"),
        OnlyOrderSide.BUY,
        OnlyOffset.OPEN,
        order_type,
        OnlyTimeInForce.GTC,
        OnlyQuantity(quantity, quantity_precision),
        None if price is None else OnlyPrice(price, price_precision),
        now,
    )


def test_binance_spot_testnet_external_contract(tmp_path) -> None:
    del tmp_path
    key, secret, rest_url, websocket_url, run_id = _required_environment()
    server_http = OnlyBinancePrivateHttpClient(rest_url, OnlyBinanceCredentials(key, secret), lambda: 0)
    server_time = _json_object(server_http.request_json("GET", "/api/v3/time", signed=False)).get("serverTime")
    assert isinstance(server_time, int)
    local_at_sync = time.time_ns() // 1_000_000
    offset_ms = server_time - local_at_sync

    def timestamp_ms() -> int:
        return time.time_ns() // 1_000_000 + offset_ms

    http = OnlyBinancePrivateHttpClient(rest_url, OnlyBinanceCredentials(key, secret), timestamp_ms)
    rest = OnlyBinanceSpotPrivateRestClient(http)
    account = _json_object(rest.account())
    assert account.get("canTrade") is True
    balances = account.get("balances")
    assert isinstance(balances, list)
    currencies = {
        str(item["asset"]): OnlyCurrency(str(item["asset"]), 8, OnlyCurrencyType.CRYPTO)
        for item in balances
        if (
            isinstance(item, dict)
            and isinstance(item.get("asset"), str)
            and re.fullmatch(r"[A-Za-z0-9]{2,12}", str(item["asset"]))
        )
    }
    usdt = next(
        (Decimal(str(item["free"])) for item in balances if isinstance(item, dict) and item.get("asset") == "USDT"),
        Decimal(0),
    )

    exchange = _json_object(http.request_json("GET", "/api/v3/exchangeInfo", signed=False))
    symbols = exchange.get("symbols")
    assert isinstance(symbols, list)
    symbol_by_name = {
        str(item["symbol"]): item
        for item in symbols
        if isinstance(item, dict) and item.get("symbol") in _REQUIRED_SYMBOLS
    }
    assert set(symbol_by_name) == set(_REQUIRED_SYMBOLS)

    identities: dict[str, OnlyBinanceResolvedOrderIdentity] = {}

    def resolve(wire_client_order_id: str, _venue_order_id: str) -> OnlyBinanceResolvedOrderIdentity:
        return identities[wire_client_order_id]

    inbound = _SignalledInbound()
    subscribed = threading.Event()
    stream = OnlyBinanceSpotUserStream(
        websocket_base_url=websocket_url,
        transport=OnlyBinanceThreadedUserStreamTransport(),
        normalizer=OnlyBinanceSpotUserStreamNormalizer(
            runtime_id=OnlyRuntimeId("binance-spot-testnet-certification"),
            gateway_id=OnlyBrokerGatewayId("binance-spot-testnet"),
            account_id=OnlyAccountId("binance-spot-testnet"),
            identities=resolve,
            currencies=currencies,
            received_at=lambda: OnlyTimestamp.from_unix_nanos(timestamp_ms() * 1_000_000),
        ),
        inbound=inbound,
        credentials=OnlyBinanceCredentials(key, secret),
        timestamp_ms=timestamp_ms,
        on_subscription_acknowledged=subscribed.set,
    )
    outstanding: list[tuple[OnlyBrokerOrderRequest, OnlyVenueOrderId]] = []
    market_request: OnlyBrokerOrderRequest | None = None
    try:
        stream.connect(f"p94a-{run_id}")
        assert subscribed.wait(15), "BINANCE_TESTNET_USER_STREAM_SUBSCRIPTION_NOT_ACKNOWLEDGED"
        stream.mark_reconciled()

        for symbol in _REQUIRED_SYMBOLS:
            definition = symbol_by_name[symbol]
            assert isinstance(definition, dict) and definition.get("status") == "TRADING"
            ticker = _json_object(http.request_json("GET", "/api/v3/ticker/price", {"symbol": symbol}, signed=False))
            market_price = Decimal(str(ticker["price"]))
            price_filter = _filter(definition, "PRICE_FILTER")
            lot_filter = _filter(definition, "LOT_SIZE")
            notional_filter = next(
                (
                    _filter(definition, name)
                    for name in ("NOTIONAL", "MIN_NOTIONAL")
                    if any(
                        isinstance(item, dict) and item.get("filterType") == name
                        for item in definition.get("filters", [])
                    )
                ),
                None,
            )
            assert notional_filter is not None
            tick = Decimal(str(price_filter["tickSize"]))
            step = Decimal(str(lot_filter["stepSize"]))
            minimum_quantity = Decimal(str(lot_filter["minQty"]))
            minimum_notional = Decimal(str(notional_filter["minNotional"]))
            limit_price = _aligned(market_price * Decimal("0.98"), tick, ROUND_DOWN)
            quantity = _aligned(
                max(minimum_quantity, minimum_notional * Decimal("1.10") / limit_price),
                step,
                ROUND_UP,
            )
            assert usdt >= quantity * limit_price
            request = _request(
                symbol=symbol,
                run_id=run_id,
                suffix="limit",
                quantity=quantity,
                quantity_precision=_precision(step),
                price=limit_price,
                price_precision=_precision(tick),
                now=OnlyTimestamp.from_unix_nanos(timestamp_ms() * 1_000_000),
            )
            wire_id = only_binance_client_order_id(request.client_order_id)
            identities[wire_id] = OnlyBinanceResolvedOrderIdentity(request.order_id, request.client_order_id)
            submitted = _json_object(rest.submit_order(request))
            venue_order_id = OnlyVenueOrderId(str(submitted["orderId"]))
            assert submitted.get("clientOrderId") == wire_id
            outstanding.append((request, venue_order_id))
            queried = _json_object(rest.query_order(symbol=symbol, client_order_id=request.client_order_id))
            assert str(queried["orderId"]) == str(venue_order_id)
            assert queried["clientOrderId"] == wire_id
            rest.cancel_order(
                OnlyBrokerCancelRequest(
                    OnlyBrokerRequestId(f"cancel-{wire_id}"),
                    request.account_id,
                    request.order_id,
                    venue_order_id,
                    OnlyTimestamp.from_unix_nanos(timestamp_ms() * 1_000_000),
                    request.client_order_id,
                ),
                symbol=symbol,
            )
            outstanding.pop()
            terminal = _json_object(rest.query_order(symbol=symbol, venue_order_id=venue_order_id))
            assert terminal["status"] == "CANCELED"

        btc = symbol_by_name["BTCUSDT"]
        assert isinstance(btc, dict)
        ticker = _json_object(http.request_json("GET", "/api/v3/ticker/price", {"symbol": "BTCUSDT"}, signed=False))
        market_price = Decimal(str(ticker["price"]))
        lot = _filter(btc, "MARKET_LOT_SIZE")
        step = Decimal(str(lot["stepSize"]))
        if step == 0:
            lot = _filter(btc, "LOT_SIZE")
            step = Decimal(str(lot["stepSize"]))
        minimum_quantity = Decimal(str(lot["minQty"]))
        market_notional = next(
            (
                _filter(btc, name)
                for name in ("NOTIONAL", "MIN_NOTIONAL")
                if any(isinstance(item, dict) and item.get("filterType") == name for item in btc.get("filters", []))
            ),
            None,
        )
        assert market_notional is not None
        minimum_notional = Decimal(str(market_notional["minNotional"]))
        quantity = _aligned(
            max(minimum_quantity, minimum_notional * Decimal("1.10") / market_price),
            step,
            ROUND_UP,
        )
        assert usdt >= quantity * market_price
        market_request = _request(
            symbol="BTCUSDT",
            run_id=run_id,
            suffix="market",
            quantity=quantity,
            quantity_precision=_precision(step),
            price=None,
            price_precision=0,
            now=OnlyTimestamp.from_unix_nanos(timestamp_ms() * 1_000_000),
        )
        wire_id = only_binance_client_order_id(market_request.client_order_id)
        identities[wire_id] = OnlyBinanceResolvedOrderIdentity(
            market_request.order_id,
            market_request.client_order_id,
        )
        submitted = _json_object(rest.submit_order(market_request))
        venue_order_id = OnlyVenueOrderId(str(submitted["orderId"]))
        assert submitted.get("clientOrderId") == wire_id
        queried = _json_object(rest.query_order(symbol="BTCUSDT", client_order_id=market_request.client_order_id))
        assert queried["status"] == "FILLED"
        trades = json.loads(rest.trades(symbol="BTCUSDT", venue_order_id=venue_order_id))
        assert isinstance(trades, list) and trades
        assert {str(item["orderId"]) for item in trades if isinstance(item, dict)} == {str(venue_order_id)}
        stream_trade = inbound.wait_for_trade(market_request.order_id)
        assert stream_trade.fill.venue_order_id == venue_order_id
        assert only_binance_client_order_id(market_request.client_order_id) == wire_id
    finally:
        for request, venue_order_id in reversed(outstanding):
            rest.cancel_order(
                OnlyBrokerCancelRequest(
                    OnlyBrokerRequestId(f"cleanup-{request.order_id}"),
                    request.account_id,
                    request.order_id,
                    venue_order_id,
                    OnlyTimestamp.from_unix_nanos(timestamp_ms() * 1_000_000),
                    request.client_order_id,
                ),
                symbol=request.instrument_id.symbol.value,
            )
        stream.disconnect()
