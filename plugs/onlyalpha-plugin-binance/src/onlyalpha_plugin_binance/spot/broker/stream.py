"""Binance Spot User Data Stream normalization and trust lifecycle."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Protocol
from urllib.parse import urlencode

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerUpdateId
from onlyalpha.broker.inbound import OnlyBrokerInboundQueue
from onlyalpha.broker.models import OnlyBrokerBalanceSnapshot
from onlyalpha.broker.updates import (
    OnlyBrokerBalancesUpdate,
    OnlyBrokerInboundUpdate,
    OnlyBrokerOrderAcceptedUpdate,
    OnlyBrokerOrderCancelledUpdate,
    OnlyBrokerOrderExpiredUpdate,
    OnlyBrokerOrderRejectedUpdate,
    OnlyBrokerTradeUpdate,
)
from onlyalpha.domain.enums import OnlyLiquiditySide
from onlyalpha.domain.execution import OnlyOrderFill, OnlyOrderRejection
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClientOrderId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyTradeId,
    OnlyVenueOrderId,
    OnlyVenueTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha_plugin_binance.common.private_http import (
    OnlyBinanceCredentials,
    only_binance_hmac_sha256,
)
from onlyalpha_plugin_binance.errors import OnlyBinanceSchemaError
from onlyalpha_plugin_binance.spot.broker.codec import only_binance_client_order_id


class OnlyBinanceUserStreamTrust(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTED_UNTRUSTED = "CONNECTED_UNTRUSTED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    TRUSTED = "TRUSTED"


@dataclass(frozen=True, slots=True)
class OnlyBinanceResolvedOrderIdentity:
    order_id: OnlyOrderId
    client_order_id: OnlyClientOrderId


class OnlyBinanceOrderIdentityResolver(Protocol):
    def __call__(self, wire_client_order_id: str, venue_order_id: str) -> OnlyBinanceResolvedOrderIdentity: ...


class OnlyBinanceUserStreamTransport(Protocol):
    def connect(
        self,
        url: str,
        on_message: Callable[[bytes], None],
        on_disconnect: Callable[[str], None],
    ) -> None: ...

    def send(self, payload: bytes) -> None: ...

    def close(self) -> None: ...


class OnlyBinanceUserStreamConnection(Protocol):
    def recv(self) -> str | bytes: ...

    def send(self, payload: str) -> object: ...

    def close(self) -> None: ...


class OnlyBinanceUserStreamConnectionFactory(Protocol):
    def __call__(self, url: str, timeout_seconds: float) -> OnlyBinanceUserStreamConnection: ...


def _user_stream_connection(url: str, timeout_seconds: float) -> OnlyBinanceUserStreamConnection:
    import websocket

    return websocket.create_connection(url, timeout=timeout_seconds, enable_multithread=True)  # type: ignore[no-any-return]


class OnlyBinanceThreadedUserStreamTransport:
    """Bounded websocket-client transport; Broker payload semantics remain in the stream."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        max_message_bytes: int = 8 * 1024 * 1024,
        connection_factory: OnlyBinanceUserStreamConnectionFactory = _user_stream_connection,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 30 or max_message_bytes <= 0:
            raise ValueError("BINANCE_USER_STREAM_TRANSPORT_CONFIGURATION_INVALID")
        self._timeout_seconds = timeout_seconds
        self._max_message_bytes = max_message_bytes
        self._connection_factory = connection_factory
        self._connection: OnlyBinanceUserStreamConnection | None = None
        self._on_message: Callable[[bytes], None] | None = None
        self._on_disconnect: Callable[[str], None] | None = None
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    def connect(
        self,
        url: str,
        on_message: Callable[[bytes], None],
        on_disconnect: Callable[[str], None],
    ) -> None:
        if self._connection is not None:
            raise RuntimeError("BINANCE_USER_STREAM_ALREADY_CONNECTED")
        try:
            connection = self._connection_factory(url, self._timeout_seconds)
        except Exception as exc:
            raise RuntimeError(f"BINANCE_USER_STREAM_CONNECT_FAILED: {type(exc).__name__}") from exc
        self._connection = connection
        self._on_message = on_message
        self._on_disconnect = on_disconnect
        self._stop.clear()
        self._worker = threading.Thread(
            target=self._receive,
            name="onlyalpha-binance-user-stream",
            daemon=True,
        )
        self._worker.start()

    def send(self, payload: bytes) -> None:
        connection = self._connection
        if connection is None:
            raise RuntimeError("BINANCE_USER_STREAM_NOT_CONNECTED")
        try:
            connection.send(payload.decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"BINANCE_USER_STREAM_SEND_FAILED: {type(exc).__name__}") from exc

    def close(self) -> None:
        self._stop.set()
        connection = self._connection
        if connection is not None:
            connection.close()
        worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=self._timeout_seconds)
        self._connection = None
        self._worker = None

    def _receive(self) -> None:
        connection = self._connection
        on_message = self._on_message
        if connection is None or on_message is None:
            return
        failure = "BINANCE_USER_STREAM_DISCONNECTED"
        try:
            while not self._stop.is_set():
                raw = connection.recv()
                if raw in ("", b""):
                    break
                payload = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
                if len(payload) > self._max_message_bytes:
                    failure = "BINANCE_USER_STREAM_MESSAGE_TOO_LARGE"
                    break
                on_message(payload)
        except Exception as exc:
            failure = f"BINANCE_USER_STREAM_RECEIVE_FAILED: {type(exc).__name__}"
        finally:
            if not self._stop.is_set():
                connection.close()
                self._connection = None
                self._worker = None
                if self._on_disconnect is not None:
                    self._on_disconnect(failure)


def _decimal(raw: object, code: str) -> Decimal:
    if not isinstance(raw, str):
        raise OnlyBinanceSchemaError(f"{code}_QUOTED_DECIMAL_REQUIRED")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise OnlyBinanceSchemaError(f"{code}_DECIMAL_INVALID") from exc
    if not value.is_finite() or value < 0:
        raise OnlyBinanceSchemaError(f"{code}_DECIMAL_INVALID")
    return value


def _precision(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        raise OnlyBinanceSchemaError("BINANCE_DECIMAL_PRECISION_INVALID")
    return max(0, -exponent)


class OnlyBinanceSpotUserStreamNormalizer:
    def __init__(
        self,
        *,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        identities: OnlyBinanceOrderIdentityResolver,
        currencies: Mapping[str, OnlyCurrency],
        received_at: Callable[[], OnlyTimestamp],
    ) -> None:
        self._runtime_id = runtime_id
        self._gateway_id = gateway_id
        self._account_id = account_id
        self._identities = identities
        self._currencies = dict(currencies)
        self._received_at = received_at

    def normalize(self, payload: bytes, source_sequence: int) -> OnlyBrokerInboundUpdate:
        try:
            raw = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise OnlyBinanceSchemaError("BINANCE_USER_EVENT_JSON_INVALID") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("e"), str) or not isinstance(raw.get("E"), int):
            raise OnlyBinanceSchemaError("BINANCE_USER_EVENT_REQUIRED_FIELD_INVALID")
        event_type = raw["e"]
        event_time = OnlyTimestamp.from_unix_nanos(raw["E"] * 1_000_000)
        received_at = self._received_at()
        provider_clock_ahead = received_at < event_time
        initialized = event_time if provider_clock_ahead else received_at
        common: dict[str, Any] = {
            "runtime_id": self._runtime_id,
            "gateway_id": self._gateway_id,
            "account_id": self._account_id,
            "update_id": OnlyBrokerUpdateId(self._event_id(raw)),
            "source_sequence": source_sequence,
            "ts_event": event_time,
            "ts_init": initialized,
            "correlation_id": str(raw.get("c", event_type)),
            "causation_id": str(raw.get("C", raw.get("c", event_type))),
            "metadata": {"provider_event_type": event_type},
            "quality_flags": (
                "PROVIDER_SEQUENCE_UNAVAILABLE",
                *(("PROVIDER_CLOCK_AHEAD",) if provider_clock_ahead else ()),
            ),
        }
        if event_type == "executionReport":
            return self._execution_report(raw, common)
        if event_type == "outboundAccountPosition":
            return self._balances(raw, common)
        raise OnlyBinanceSchemaError(f"BINANCE_USER_EVENT_UNSUPPORTED: {event_type}")

    def _execution_report(self, raw: dict[str, Any], common: dict[str, Any]) -> OnlyBrokerInboundUpdate:
        required = ("c", "i", "x", "X", "s")
        if any(name not in raw for name in required) or not isinstance(raw["c"], str):
            raise OnlyBinanceSchemaError("BINANCE_EXECUTION_REPORT_REQUIRED_FIELD_INVALID")
        execution_type = raw["x"]
        original_client_order_id = raw.get("C")
        wire_order_client_id = (
            original_client_order_id
            if execution_type == "CANCELED" and isinstance(original_client_order_id, str) and original_client_order_id
            else raw["c"]
        )
        identity = self._identities(wire_order_client_id, str(raw["i"]))
        if only_binance_client_order_id(identity.client_order_id) != wire_order_client_id:
            raise OnlyBinanceSchemaError("BINANCE_EXECUTION_CLIENT_IDENTITY_CONFLICT")
        venue_order_id = OnlyVenueOrderId(str(raw["i"]))
        fields = {
            **common,
            "order_id": identity.order_id,
        }
        if execution_type == "NEW":
            return OnlyBrokerOrderAcceptedUpdate(**fields, venue_order_id=venue_order_id)
        if execution_type == "REJECTED":
            return OnlyBrokerOrderRejectedUpdate(
                **fields,
                rejection=OnlyOrderRejection(str(raw.get("r", "VENUE_REJECTED")), "Binance rejected order"),
                venue_order_id=venue_order_id,
            )
        if execution_type == "CANCELED":
            return OnlyBrokerOrderCancelledUpdate(**fields, venue_order_id=venue_order_id)
        if execution_type in {"EXPIRED", "TRADE_PREVENTION"}:
            return OnlyBrokerOrderExpiredUpdate(**fields, venue_order_id=venue_order_id)
        if execution_type == "TRADE":
            quantity = _decimal(raw.get("l"), "BINANCE_LAST_EXECUTED_QUANTITY")
            price = _decimal(raw.get("L"), "BINANCE_LAST_EXECUTED_PRICE")
            trade_id = raw.get("t")
            if quantity <= 0 or price <= 0 or not isinstance(trade_id, int | str) or isinstance(trade_id, bool):
                raise OnlyBinanceSchemaError("BINANCE_TRADE_EXECUTION_INVALID")
            transaction_ms = raw.get("T")
            if not isinstance(transaction_ms, int) or isinstance(transaction_ms, bool) or transaction_ms < 0:
                raise OnlyBinanceSchemaError("BINANCE_TRADE_TIME_INVALID")
            fill = OnlyOrderFill(
                OnlyTradeId(f"BINANCE:{raw['s']}:{trade_id}"),
                identity.order_id,
                OnlyPrice(price, _precision(price)),
                OnlyQuantity(quantity, _precision(quantity)),
                OnlyTimestamp.from_unix_nanos(transaction_ms * 1_000_000),
                common["ts_init"],
                OnlyVenueTradeId(str(trade_id)),
                venue_order_id,
                OnlyLiquiditySide.MAKER if raw.get("m") is True else OnlyLiquiditySide.TAKER,
                common["source_sequence"],
                str(common["update_id"]),
                {"symbol": str(raw["s"])},
            )
            return OnlyBrokerTradeUpdate(**fields, fill=fill)
        raise OnlyBinanceSchemaError(f"BINANCE_EXECUTION_TYPE_UNSUPPORTED: {execution_type}")

    def _balances(self, raw: dict[str, Any], common: dict[str, Any]) -> OnlyBrokerBalancesUpdate:
        balances = raw.get("B")
        if not isinstance(balances, list) or not balances:
            raise OnlyBinanceSchemaError("BINANCE_ACCOUNT_POSITION_BALANCES_INVALID")
        snapshots: list[OnlyBrokerBalanceSnapshot] = []
        for item in balances:
            if not isinstance(item, dict) or not isinstance(item.get("a"), str):
                raise OnlyBinanceSchemaError("BINANCE_ACCOUNT_POSITION_BALANCE_INVALID")
            currency = self._currencies.get(item["a"])
            if currency is None:
                raise OnlyBinanceSchemaError(f"BINANCE_BALANCE_CURRENCY_UNRESOLVED: {item['a']}")
            free = OnlyMoney(_decimal(item.get("f"), "BINANCE_BALANCE_FREE"), currency)
            locked = OnlyMoney(_decimal(item.get("l"), "BINANCE_BALANCE_LOCKED"), currency)
            snapshots.append(OnlyBrokerBalanceSnapshot(currency, free + locked, free, locked))
        return OnlyBrokerBalancesUpdate(
            **common,
            snapshots=tuple(sorted(snapshots, key=lambda item: item.currency.code)),
        )

    @staticmethod
    def _event_id(raw: dict[str, Any]) -> str:
        return "binance-user:" + ":".join(
            str(item)
            for item in (
                raw.get("e"),
                raw.get("s", "account"),
                raw.get("i", "-"),
                raw.get("t", "-"),
                raw.get("x", "-"),
                raw.get("E"),
            )
        )


class OnlyBinanceSpotUserStream:
    def __init__(
        self,
        *,
        websocket_base_url: str,
        transport: OnlyBinanceUserStreamTransport,
        normalizer: OnlyBinanceSpotUserStreamNormalizer,
        inbound: OnlyBrokerInboundQueue,
        credentials: OnlyBinanceCredentials,
        timestamp_ms: Callable[[], int],
        recv_window_ms: int = 5_000,
        on_subscription_acknowledged: Callable[[], None] = lambda: None,
    ) -> None:
        if not websocket_base_url.startswith("wss://") or not 1 <= recv_window_ms <= 60_000:
            raise ValueError("BINANCE_USER_STREAM_URL_INVALID")
        self._base_url = websocket_base_url.rstrip("/")
        self._transport = transport
        self._normalizer = normalizer
        self._inbound = inbound
        self._credentials = credentials
        self._timestamp_ms = timestamp_ms
        self._recv_window_ms = recv_window_ms
        self._on_subscription_acknowledged = on_subscription_acknowledged
        self._trust = OnlyBinanceUserStreamTrust.DISCONNECTED
        self._sequence = 0
        self._subscription_request_id: str | None = None
        self._subscription_id: int | None = None

    @property
    def trust(self) -> OnlyBinanceUserStreamTrust:
        return self._trust

    def connect(self, request_id: str) -> None:
        if not request_id or len(request_id) > 36 or any(character.isspace() for character in request_id):
            raise ValueError("BINANCE_USER_STREAM_REQUEST_ID_INVALID")
        self._trust = OnlyBinanceUserStreamTrust.CONNECTED_UNTRUSTED
        self._subscription_request_id = request_id
        self._subscription_id = None
        self._transport.connect(self._base_url, self._on_message, self._on_disconnect)
        timestamp = self._timestamp_ms()
        if timestamp < 0:
            raise ValueError("BINANCE_TIMESTAMP_INVALID")
        params: dict[str, int | str] = {
            "apiKey": self._credentials.api_key,
            "recvWindow": self._recv_window_ms,
            "timestamp": timestamp,
        }
        signing_payload = urlencode(sorted((key, str(value)) for key, value in params.items()))
        params["signature"] = only_binance_hmac_sha256(self._credentials.secret_key, signing_payload)
        self._transport.send(
            json.dumps(
                {
                    "id": request_id,
                    "method": "userDataStream.subscribe.signature",
                    "params": params,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )

    def mark_reconciled(self) -> None:
        if (
            self._trust
            not in {
                OnlyBinanceUserStreamTrust.CONNECTED_UNTRUSTED,
                OnlyBinanceUserStreamTrust.RECONCILIATION_REQUIRED,
            }
            or self._subscription_id is None
        ):
            raise RuntimeError("BINANCE_STREAM_RECONCILIATION_STATE_INVALID")
        self._trust = OnlyBinanceUserStreamTrust.TRUSTED

    def disconnect(self) -> None:
        self._transport.close()
        self._trust = OnlyBinanceUserStreamTrust.DISCONNECTED

    def _on_message(self, payload: bytes) -> None:
        try:
            raw = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise OnlyBinanceSchemaError("BINANCE_USER_STREAM_ENVELOPE_INVALID") from exc
        if isinstance(raw, dict) and raw.get("id") == self._subscription_request_id:
            result = raw.get("result")
            subscription_id = result.get("subscriptionId") if isinstance(result, dict) else None
            if raw.get("status") != 200 or not isinstance(subscription_id, int):
                self._trust = OnlyBinanceUserStreamTrust.RECONCILIATION_REQUIRED
                raise OnlyBinanceSchemaError("BINANCE_USER_STREAM_SUBSCRIPTION_REJECTED")
            self._subscription_id = subscription_id
            self._on_subscription_acknowledged()
            return
        event = raw.get("event") if isinstance(raw, dict) else None
        event_payload = (
            json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if isinstance(event, dict)
            else payload
        )
        self._sequence += 1
        self._inbound.put(self._normalizer.normalize(event_payload, self._sequence))

    def _on_disconnect(self, _reason: str) -> None:
        self._subscription_id = None
        self._trust = OnlyBinanceUserStreamTrust.RECONCILIATION_REQUIRED


__all__ = [name for name in globals() if name.startswith("Only")]
