from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from onlyalpha_plugin_binance.common.private_http import (
    OnlyBinanceDispatchKnowledge,
    OnlyBinancePrivateRequestError,
)
from onlyalpha_plugin_binance.spot.broker.codec import only_binance_client_order_id
from onlyalpha_plugin_binance.spot.broker.gateway import OnlyBinanceSpotBrokerGateway

from onlyalpha.broker.enums import OnlyBrokerConnectionState, OnlyBrokerOperationStatus
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerRequestId
from onlyalpha.broker.models import OnlyBrokerCancelRequest, OnlyBrokerOrderRequest
from onlyalpha.broker.reconciliation import (
    OnlyBrokerCommandEvidence,
    OnlyBrokerCommandEvidenceKind,
    OnlyBrokerCommandOperation,
    OnlyBrokerReadinessAuthority,
    OnlyDurableBrokerCommandEvidenceStore,
)
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
    OnlyVenueOrderId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyPrice, OnlyQuantity


def _order(symbol: str) -> OnlyBrokerOrderRequest:
    return OnlyBrokerOrderRequest(
        OnlyBrokerRequestId(f"submit-{symbol}"),
        OnlyOrderId(f"order-{symbol}"),
        OnlyClientOrderId(f"client-{symbol}"),
        OnlyAccountId("spot-testnet"),
        OnlyInstrumentId.parse(f"{symbol}.BINANCE"),
        OnlyOrderSide.BUY,
        OnlyOffset.OPEN,
        OnlyOrderType.LIMIT,
        OnlyTimeInForce.GTC,
        OnlyQuantity(Decimal("0.01000000"), 8),
        OnlyPrice(Decimal("25000.10"), 2),
        OnlyTimestamp.from_unix_nanos(1_000_000_000),
        f"OINT-{symbol}",
        "a" * 64,
    )


class _LostRest:
    def __init__(self) -> None:
        self.submit_count = 0

    def authenticate_account(self) -> bytes:
        return b'{"balances":[]}'

    def submit_order(self, _request) -> bytes:
        self.submit_count += 1
        raise OnlyBinancePrivateRequestError("BINANCE_PRIVATE_REQUEST_UNKNOWN", OnlyBinanceDispatchKnowledge.UNKNOWN)


class _QueryRest:
    def __init__(self) -> None:
        self.venue_by_client = {"client-one": "101", "client-two": "202"}
        self.trade_order_queries: list[OnlyVenueOrderId | None] = []

    def query_order(self, *, symbol, client_order_id=None, venue_order_id=None) -> bytes:
        del venue_order_id
        client = str(client_order_id)
        venue = self.venue_by_client[client]
        return json.dumps(
            {
                "symbol": symbol,
                "orderId": int(venue),
                "clientOrderId": client,
                "price": "25000.10",
                "origQty": "0.01000000",
                "executedQty": "0.01000000",
                "status": "FILLED",
                "timeInForce": "GTC",
                "type": "LIMIT",
                "side": "BUY",
                "updateTime": 1700000000100,
            }
        ).encode()

    def trades(self, *, symbol, venue_order_id=None, from_id=None) -> bytes:
        del from_id
        self.trade_order_queries.append(venue_order_id)
        assert venue_order_id is not None
        trade_id = int(str(venue_order_id)) + 1
        return json.dumps(
            [
                {
                    "symbol": symbol,
                    "id": trade_id,
                    "orderId": int(str(venue_order_id)),
                    "price": "25000.10",
                    "qty": "0.01000000",
                    "commission": "0.00001000",
                    "commissionAsset": "BTC",
                    "time": 1700000000000,
                    "isMaker": False,
                }
            ]
        ).encode()


class _FailingEvidenceStore:
    def load(self):
        return ()

    def append(self, _evidence) -> None:
        raise OSError("controlled durable commit failure")


class _CancelRest:
    def __init__(self, *, lose_cancel: bool = False) -> None:
        self.submit_count = 0
        self.cancel_count = 0
        self.lose_cancel = lose_cancel

    def submit_order(self, request) -> bytes:
        self.submit_count += 1
        return json.dumps(
            {
                "orderId": 1,
                "clientOrderId": only_binance_client_order_id(request.client_order_id),
            }
        ).encode()

    def cancel_order(self, _request, *, symbol: str) -> bytes:
        assert symbol == "BTCUSDT"
        self.cancel_count += 1
        if self.lose_cancel:
            raise OnlyBinancePrivateRequestError(
                "BINANCE_PRIVATE_EXECUTION_UNKNOWN: controlled",
                OnlyBinanceDispatchKnowledge.UNKNOWN,
            )
        return b'{"orderId":1,"status":"CANCELED"}'


def _ready(readiness: OnlyBrokerReadinessAuthority) -> None:
    readiness.transport_connected()
    readiness.authenticated()
    readiness.account_scope_established()
    readiness.discovery_completed()
    readiness.reconciliation_converged()
    readiness.stream_trusted()


def test_gateway_unknown_is_durable_and_same_semantic_submit_never_dispatches_twice(tmp_path: Path) -> None:
    rest = _LostRest()
    readiness = OnlyBrokerReadinessAuthority()
    _ready(readiness)
    evidence_path = (tmp_path / "commands.jsonl").resolve()
    store = OnlyDurableBrokerCommandEvidenceStore(evidence_path)
    gateway = OnlyBinanceSpotBrokerGateway(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        account_id=OnlyAccountId("spot-testnet"),
        rest=rest,  # type: ignore[arg-type]
        readiness=readiness,
        evidence=store,
        currencies={"USDT": OnlyCurrency("USDT", 8, OnlyCurrencyType.CRYPTO)},
        now=lambda: OnlyTimestamp.from_unix_nanos(10),
    )
    request = replace(
        _order("BTCUSDT"),
        runtime_intent_transaction_id="OINT-runtime-order",
        runtime_intent_authority_hash="a" * 64,
    )
    first = gateway.submit_order(request)
    second = gateway.submit_order(request)
    assert first.status is second.status is OnlyBrokerOperationStatus.UNKNOWN
    assert first.client_order_id == second.client_order_id == request.client_order_id
    assert rest.submit_count == 1
    assert [item.kind for item in store.load()] == [
        OnlyBrokerCommandEvidenceKind.INTENT_DURABLE,
        OnlyBrokerCommandEvidenceKind.DISPATCHED,
        OnlyBrokerCommandEvidenceKind.UNKNOWN,
    ]
    intent = store.load()[0]
    assert intent.operation is OnlyBrokerCommandOperation.SUBMIT
    assert intent.runtime_intent_transaction_id == request.runtime_intent_transaction_id
    assert intent.runtime_intent_authority_hash == request.runtime_intent_authority_hash
    assert OnlyBrokerOrderRequest.from_json(intent.request_payload) == request
    assert readiness.snapshot.unresolved_unknown_count == 1
    assert gateway.connection_snapshot().state is OnlyBrokerConnectionState.CONNECTED


def test_gateway_rejects_submit_without_runtime_intent_reference_before_transport(tmp_path: Path) -> None:
    rest = _LostRest()
    readiness = OnlyBrokerReadinessAuthority()
    _ready(readiness)
    gateway = OnlyBinanceSpotBrokerGateway(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        account_id=OnlyAccountId("spot-testnet"),
        rest=rest,  # type: ignore[arg-type]
        readiness=readiness,
        evidence=OnlyDurableBrokerCommandEvidenceStore((tmp_path / "commands.jsonl").resolve()),
        currencies={},
        now=lambda: OnlyTimestamp.from_unix_nanos(10),
    )

    result = gateway.submit_order(
        replace(_order("BTCUSDT"), runtime_intent_transaction_id="", runtime_intent_authority_hash="")
    )

    assert result.status is OnlyBrokerOperationStatus.NOT_READY
    assert result.immediate_error == "RUNTIME_ORDER_INTENT_REFERENCE_MISSING"
    assert rest.submit_count == 0


def test_gateway_restart_restores_correlation_without_resubmit(tmp_path: Path) -> None:
    rest = _LostRest()
    readiness = OnlyBrokerReadinessAuthority()
    _ready(readiness)
    store = OnlyDurableBrokerCommandEvidenceStore((tmp_path / "commands.jsonl").resolve())
    request = _order("ETHUSDT")
    first = OnlyBinanceSpotBrokerGateway(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        account_id=request.account_id,
        rest=rest,  # type: ignore[arg-type]
        readiness=readiness,
        evidence=store,
        currencies={},
        now=lambda: OnlyTimestamp.from_unix_nanos(10),
    )
    first.submit_order(request)
    recovered_readiness = OnlyBrokerReadinessAuthority()
    _ready(recovered_readiness)
    recovered = OnlyBinanceSpotBrokerGateway(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        account_id=request.account_id,
        rest=rest,  # type: ignore[arg-type]
        readiness=recovered_readiness,
        evidence=OnlyDurableBrokerCommandEvidenceStore((tmp_path / "commands.jsonl").resolve()),
        currencies={},
        now=lambda: OnlyTimestamp.from_unix_nanos(11),
    )
    recovered.restore_order_request(request)
    result = recovered.submit_order(request)
    assert result.status is OnlyBrokerOperationStatus.UNKNOWN
    assert rest.submit_count == 1
    assert recovered_readiness.snapshot.unresolved_unknown_count == 1


def test_durable_intent_without_dispatch_can_recover_without_guessing_external_state(tmp_path: Path) -> None:
    request = _order("ETHUSDT")
    store = OnlyDurableBrokerCommandEvidenceStore((tmp_path / "commands.jsonl").resolve())
    store.append(
        OnlyBrokerCommandEvidence(
            f"{request.order_id}:00000001:INTENT_DURABLE",
            OnlyBrokerCommandEvidenceKind.INTENT_DURABLE,
            request.order_id,
            request.client_order_id,
            None,
            OnlyTimestamp.from_unix_nanos(1),
        )
    )
    rest = _LostRest()
    readiness = OnlyBrokerReadinessAuthority()
    _ready(readiness)
    recovered = OnlyBinanceSpotBrokerGateway(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        account_id=request.account_id,
        rest=rest,  # type: ignore[arg-type]
        readiness=readiness,
        evidence=store,
        currencies={},
        now=lambda: OnlyTimestamp.from_unix_nanos(10),
    )
    recovered.restore_order_request(request)
    result = recovered.submit_order(request)
    assert result.status is OnlyBrokerOperationStatus.UNKNOWN
    assert rest.submit_count == 1
    assert [item.kind for item in store.load()] == [
        OnlyBrokerCommandEvidenceKind.INTENT_DURABLE,
        OnlyBrokerCommandEvidenceKind.DISPATCHED,
        OnlyBrokerCommandEvidenceKind.UNKNOWN,
    ]


def test_gateway_ready_requires_all_barriers_and_stream_loss_revokes_it(tmp_path: Path) -> None:
    readiness = OnlyBrokerReadinessAuthority()
    gateway = OnlyBinanceSpotBrokerGateway(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        account_id=OnlyAccountId("spot-testnet"),
        rest=_LostRest(),  # type: ignore[arg-type]
        readiness=readiness,
        evidence=OnlyDurableBrokerCommandEvidenceStore((tmp_path / "commands.jsonl").resolve()),
        currencies={},
        now=lambda: OnlyTimestamp.from_unix_nanos(10),
    )
    assert gateway.connect().snapshot.state is OnlyBrokerConnectionState.CONNECTED
    assert gateway.authenticate().snapshot.state is OnlyBrokerConnectionState.CONNECTED
    gateway.baseline_discovered()
    gateway.reconciliation_converged()
    assert gateway.connection_snapshot().state is OnlyBrokerConnectionState.CONNECTED
    gateway.stream_trusted()
    assert gateway.connection_snapshot().state is OnlyBrokerConnectionState.READY
    gateway.stream_lost()
    assert gateway.connection_snapshot().state is OnlyBrokerConnectionState.CONNECTED


def test_trade_and_fee_queries_prove_exact_order_identity_for_same_symbol(tmp_path: Path) -> None:
    first = replace(
        _order("BTCUSDT"),
        order_id=OnlyOrderId("order-one"),
        client_order_id=OnlyClientOrderId("client-one"),
    )
    second = replace(
        _order("BTCUSDT"),
        gateway_request_id=OnlyBrokerRequestId("submit-two"),
        order_id=OnlyOrderId("order-two"),
        client_order_id=OnlyClientOrderId("client-two"),
    )
    rest = _QueryRest()
    gateway = OnlyBinanceSpotBrokerGateway(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        account_id=first.account_id,
        rest=rest,  # type: ignore[arg-type]
        readiness=OnlyBrokerReadinessAuthority(),
        evidence=OnlyDurableBrokerCommandEvidenceStore((tmp_path / "commands.jsonl").resolve()),
        currencies={"BTC": OnlyCurrency("BTC", 8, OnlyCurrencyType.CRYPTO)},
        now=lambda: OnlyTimestamp.from_unix_nanos(1_700_000_001_000_000_000),
    )
    gateway.restore_order_request(first)
    gateway.restore_order_request(second)

    trades = gateway.query_trades(first.account_id)
    assert [(item.fill.order_id, item.fill.venue_order_id) for item in trades] == [
        (first.order_id, OnlyVenueOrderId("101")),
        (second.order_id, OnlyVenueOrderId("202")),
    ]
    fees = gateway.query_fee_evidence(first.account_id)
    assert {item.scope.trade_id for item in fees} == {item.fill.trade_id for item in trades}
    assert {item.reported_total.amount for item in fees if item.reported_total is not None} == {Decimal("0.00001000")}
    assert rest.trade_order_queries == [
        OnlyVenueOrderId("101"),
        OnlyVenueOrderId("202"),
        OnlyVenueOrderId("101"),
        OnlyVenueOrderId("202"),
    ]


def test_durable_submit_intent_failure_prevents_external_dispatch() -> None:
    rest = _LostRest()
    readiness = OnlyBrokerReadinessAuthority()
    _ready(readiness)
    gateway = OnlyBinanceSpotBrokerGateway(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        account_id=OnlyAccountId("spot-testnet"),
        rest=rest,  # type: ignore[arg-type]
        readiness=readiness,
        evidence=_FailingEvidenceStore(),
        currencies={},
        now=lambda: OnlyTimestamp.from_unix_nanos(10),
    )

    with pytest.raises(OSError, match="durable commit failure"):
        gateway.submit_order(_order("BTCUSDT"))
    assert rest.submit_count == 0


def test_crash_after_durable_intent_before_dispatch_recovers_exact_request(tmp_path: Path) -> None:
    rest = _LostRest()
    readiness = OnlyBrokerReadinessAuthority()
    _ready(readiness)
    path = (tmp_path / "commands.jsonl").resolve()
    request = _order("BTCUSDT")
    gateway = OnlyBinanceSpotBrokerGateway(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        account_id=request.account_id,
        rest=rest,  # type: ignore[arg-type]
        readiness=readiness,
        evidence=OnlyDurableBrokerCommandEvidenceStore(path),
        currencies={},
        now=lambda: OnlyTimestamp.from_unix_nanos(10),
        before_dispatch=lambda _operation, _order_id: (_ for _ in ()).throw(RuntimeError("controlled crash")),
    )
    with pytest.raises(RuntimeError, match="controlled crash"):
        gateway.submit_order(request)
    assert rest.submit_count == 0
    evidence = OnlyDurableBrokerCommandEvidenceStore(path).load()
    assert [item.kind for item in evidence] == [OnlyBrokerCommandEvidenceKind.INTENT_DURABLE]
    assert OnlyBrokerOrderRequest.from_json(evidence[0].request_payload) == request


def test_crash_after_dispatch_marker_never_resubmits_same_semantic_order(tmp_path: Path) -> None:
    class _CrashAfterDispatch:
        def __init__(self) -> None:
            self.submit_count = 0

        def submit_order(self, _request) -> bytes:
            self.submit_count += 1
            raise RuntimeError("process crash before response handling")

    rest = _CrashAfterDispatch()
    path = (tmp_path / "commands.jsonl").resolve()
    request = _order("BTCUSDT")
    readiness = OnlyBrokerReadinessAuthority()
    _ready(readiness)
    gateway = OnlyBinanceSpotBrokerGateway(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        account_id=request.account_id,
        rest=rest,  # type: ignore[arg-type]
        readiness=readiness,
        evidence=OnlyDurableBrokerCommandEvidenceStore(path),
        currencies={},
        now=lambda: OnlyTimestamp.from_unix_nanos(10),
    )
    with pytest.raises(RuntimeError, match="process crash"):
        gateway.submit_order(request)
    recovered_readiness = OnlyBrokerReadinessAuthority()
    _ready(recovered_readiness)
    recovered = OnlyBinanceSpotBrokerGateway(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        account_id=request.account_id,
        rest=rest,  # type: ignore[arg-type]
        readiness=recovered_readiness,
        evidence=OnlyDurableBrokerCommandEvidenceStore(path),
        currencies={},
        now=lambda: OnlyTimestamp.from_unix_nanos(11),
    )
    assert recovered.submit_order(request).status is OnlyBrokerOperationStatus.UNKNOWN
    assert rest.submit_count == 1
    assert recovered_readiness.snapshot.unresolved_unknown_count == 1


def test_cancel_uncertainty_is_durable_and_suppresses_second_cancel(tmp_path: Path) -> None:
    rest = _CancelRest(lose_cancel=True)
    readiness = OnlyBrokerReadinessAuthority()
    _ready(readiness)
    store = OnlyDurableBrokerCommandEvidenceStore((tmp_path / "commands.jsonl").resolve())
    gateway = OnlyBinanceSpotBrokerGateway(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        account_id=OnlyAccountId("spot-testnet"),
        rest=rest,  # type: ignore[arg-type]
        readiness=readiness,
        evidence=store,
        currencies={},
        now=lambda: OnlyTimestamp.from_unix_nanos(10),
    )
    order = _order("BTCUSDT")
    assert gateway.submit_order(order).status is OnlyBrokerOperationStatus.RECEIVED
    cancel = OnlyBrokerCancelRequest(
        OnlyBrokerRequestId("cancel-BTCUSDT"),
        order.account_id,
        order.order_id,
        OnlyVenueOrderId("1"),
        OnlyTimestamp.from_unix_nanos(20),
        order.client_order_id,
    )
    assert gateway.cancel_order(cancel).status is OnlyBrokerOperationStatus.UNKNOWN
    assert gateway.cancel_order(cancel).status is OnlyBrokerOperationStatus.UNKNOWN
    assert rest.cancel_count == 1
    cancel_evidence = [item for item in store.load() if item.operation is OnlyBrokerCommandOperation.CANCEL]
    assert [item.kind for item in cancel_evidence] == [
        OnlyBrokerCommandEvidenceKind.INTENT_DURABLE,
        OnlyBrokerCommandEvidenceKind.DISPATCHED,
        OnlyBrokerCommandEvidenceKind.UNKNOWN,
    ]
    assert OnlyBrokerCancelRequest.from_json(cancel_evidence[0].request_payload) == cancel
    recovered_readiness = OnlyBrokerReadinessAuthority()
    _ready(recovered_readiness)
    recovered = OnlyBinanceSpotBrokerGateway(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        account_id=order.account_id,
        rest=rest,  # type: ignore[arg-type]
        readiness=recovered_readiness,
        evidence=OnlyDurableBrokerCommandEvidenceStore((tmp_path / "commands.jsonl").resolve()),
        currencies={},
        now=lambda: OnlyTimestamp.from_unix_nanos(30),
    )
    assert recovered.cancel_order(cancel).status is OnlyBrokerOperationStatus.UNKNOWN
    assert rest.cancel_count == 1
    assert recovered_readiness.snapshot.unresolved_unknown_count == 1


def test_durable_cancel_intent_failure_prevents_external_dispatch() -> None:
    rest = _CancelRest()
    readiness = OnlyBrokerReadinessAuthority()
    _ready(readiness)
    order = _order("BTCUSDT")
    gateway = OnlyBinanceSpotBrokerGateway(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        account_id=order.account_id,
        rest=rest,  # type: ignore[arg-type]
        readiness=readiness,
        evidence=_FailingEvidenceStore(),
        currencies={},
        now=lambda: OnlyTimestamp.from_unix_nanos(10),
    )
    gateway.restore_order_request(order)
    with pytest.raises(OSError, match="durable commit failure"):
        gateway.cancel_order(
            OnlyBrokerCancelRequest(
                OnlyBrokerRequestId("cancel-BTCUSDT"),
                order.account_id,
                order.order_id,
                None,
                OnlyTimestamp.from_unix_nanos(20),
                order.client_order_id,
            )
        )
    assert rest.cancel_count == 0


def test_successful_submit_ack_binds_venue_identity_and_conflict_fails_closed(tmp_path: Path) -> None:
    rest = _CancelRest()
    readiness = OnlyBrokerReadinessAuthority()
    _ready(readiness)
    request = _order("BTCUSDT")
    gateway = OnlyBinanceSpotBrokerGateway(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        account_id=request.account_id,
        rest=rest,  # type: ignore[arg-type]
        readiness=readiness,
        evidence=OnlyDurableBrokerCommandEvidenceStore((tmp_path / "commands.jsonl").resolve()),
        currencies={},
        now=lambda: OnlyTimestamp.from_unix_nanos(10),
    )

    assert gateway.submit_order(request).status is OnlyBrokerOperationStatus.RECEIVED
    assert gateway.submit_order(request).status is OnlyBrokerOperationStatus.RECEIVED
    assert rest.submit_count == 1
    cancel = OnlyBrokerCancelRequest(
        OnlyBrokerRequestId("cancel-BTCUSDT"),
        request.account_id,
        request.order_id,
        OnlyVenueOrderId("1"),
        OnlyTimestamp.from_unix_nanos(20),
        request.client_order_id,
    )
    assert gateway.cancel_order(cancel).status is OnlyBrokerOperationStatus.RECEIVED
    assert gateway.cancel_order(cancel).status is OnlyBrokerOperationStatus.RECEIVED
    assert rest.cancel_count == 1
    with pytest.raises(ValueError, match="VENUE_ORDER_IDENTITY_CONFLICT"):
        gateway.resolve_order_identity(
            only_binance_client_order_id(request.client_order_id),
            "2",
        )
    assert readiness.snapshot.identity_conflict
    assert readiness.snapshot.state is OnlyBrokerConnectionState.FAILED


def test_semantically_malformed_submit_ack_is_unknown_and_never_reposts(tmp_path: Path) -> None:
    class _MalformedAckRest:
        def __init__(self) -> None:
            self.submit_count = 0

        def submit_order(self, _request) -> bytes:
            self.submit_count += 1
            return b"{}"

    rest = _MalformedAckRest()
    readiness = OnlyBrokerReadinessAuthority()
    _ready(readiness)
    request = _order("BTCUSDT")
    gateway = OnlyBinanceSpotBrokerGateway(
        gateway_id=OnlyBrokerGatewayId("binance-testnet"),
        account_id=request.account_id,
        rest=rest,  # type: ignore[arg-type]
        readiness=readiness,
        evidence=OnlyDurableBrokerCommandEvidenceStore((tmp_path / "commands.jsonl").resolve()),
        currencies={},
        now=lambda: OnlyTimestamp.from_unix_nanos(10),
    )

    assert gateway.submit_order(request).status is OnlyBrokerOperationStatus.UNKNOWN
    assert gateway.submit_order(request).status is OnlyBrokerOperationStatus.UNKNOWN
    assert rest.submit_count == 1
    assert readiness.snapshot.unresolved_unknown_count == 1
