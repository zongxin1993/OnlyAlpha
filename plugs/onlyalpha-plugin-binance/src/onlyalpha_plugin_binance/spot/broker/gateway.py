"""Binance Spot Broker Gateway composition without owning Order projection truth."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from onlyalpha.broker.capabilities import OnlyBrokerCapabilities
from onlyalpha.broker.enums import OnlyBrokerCapability, OnlyBrokerOperationStatus
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.models import (
    OnlyBrokerAccountSnapshot,
    OnlyBrokerBalanceSnapshot,
    OnlyBrokerCancelRequest,
    OnlyBrokerCancelResult,
    OnlyBrokerConnectionResult,
    OnlyBrokerConnectionSnapshot,
    OnlyBrokerOrderRequest,
    OnlyBrokerOrderSnapshot,
    OnlyBrokerOrderSubmitResult,
    OnlyBrokerPositionSnapshot,
    OnlyBrokerQuery,
    OnlyBrokerTradeSnapshot,
)
from onlyalpha.broker.reconciliation import (
    OnlyBrokerCommandEvidence,
    OnlyBrokerCommandEvidenceKind,
    OnlyBrokerCommandEvidenceStore,
    OnlyBrokerCommandOperation,
    OnlyBrokerReadinessAuthority,
)
from onlyalpha.domain.enums import OnlyLiquiditySide
from onlyalpha.domain.execution import OnlyOrderFill
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId, OnlyTradeId, OnlyVenueOrderId, OnlyVenueTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.fee.evidence import OnlyExternalFeeEvidence, OnlyExternalFeeEvidenceMode
from onlyalpha.fee.evidence_scope import OnlyExternalFeeEvidenceScope
from onlyalpha_plugin_binance.common.private_http import (
    OnlyBinanceDispatchKnowledge,
    OnlyBinancePrivateRequestError,
)
from onlyalpha_plugin_binance.errors import OnlyBinanceSchemaError
from onlyalpha_plugin_binance.spot.broker.codec import only_binance_client_order_id
from onlyalpha_plugin_binance.spot.broker.dto import (
    OnlyBinanceSpotAccountDto,
    OnlyBinanceSpotOrdersDto,
    OnlyBinanceSpotTradesDto,
)
from onlyalpha_plugin_binance.spot.broker.normalize import (
    only_normalize_binance_spot_balances,
    only_normalize_binance_spot_order,
)
from onlyalpha_plugin_binance.spot.broker.rest import OnlyBinanceSpotPrivateRestClient

if TYPE_CHECKING:
    from onlyalpha_plugin_binance.spot.broker.stream import OnlyBinanceResolvedOrderIdentity

_CAPABILITIES = OnlyBrokerCapabilities(
    frozenset(
        {
            OnlyBrokerCapability.CONNECT,
            OnlyBrokerCapability.AUTHENTICATE,
            OnlyBrokerCapability.SUBMIT_ORDER,
            OnlyBrokerCapability.CANCEL_ORDER,
            OnlyBrokerCapability.QUERY_BALANCES,
            OnlyBrokerCapability.QUERY_OPEN_ORDERS,
            OnlyBrokerCapability.QUERY_ORDERS,
            OnlyBrokerCapability.QUERY_TRADES,
            OnlyBrokerCapability.QUERY_FEE_EVIDENCE,
            OnlyBrokerCapability.PUSH_ORDER_UPDATES,
            OnlyBrokerCapability.PUSH_TRADE_UPDATES,
            OnlyBrokerCapability.PUSH_ACCOUNT_UPDATES,
            OnlyBrokerCapability.MARKET_ORDER,
            OnlyBrokerCapability.LIMIT_ORDER,
            OnlyBrokerCapability.PARTIAL_FILL,
        }
    )
)


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


def _same_semantic_order(left: OnlyBrokerOrderRequest, right: OnlyBrokerOrderRequest) -> bool:
    return (
        left.order_id,
        left.client_order_id,
        left.account_id,
        left.instrument_id,
        left.side,
        left.offset,
        left.order_type,
        left.time_in_force,
        left.quantity,
        left.price,
        left.submitted_at,
    ) == (
        right.order_id,
        right.client_order_id,
        right.account_id,
        right.instrument_id,
        right.side,
        right.offset,
        right.order_type,
        right.time_in_force,
        right.quantity,
        right.price,
        right.submitted_at,
    )


class OnlyBinanceSpotBrokerGateway:
    def __init__(
        self,
        *,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        rest: OnlyBinanceSpotPrivateRestClient,
        readiness: OnlyBrokerReadinessAuthority,
        evidence: OnlyBrokerCommandEvidenceStore,
        currencies: Mapping[str, OnlyCurrency],
        now: Callable[[], OnlyTimestamp],
        before_dispatch: Callable[[OnlyBrokerCommandOperation, OnlyOrderId], None] = lambda _operation, _order_id: None,
    ) -> None:
        self._gateway_id = gateway_id
        self._account_id = account_id
        self._rest = rest
        self._readiness = readiness
        self._evidence = evidence
        self._currencies = dict(currencies)
        self._now = now
        self._before_dispatch = before_dispatch
        self._requests: dict[str, OnlyBrokerOrderRequest] = {}
        self._cancel_requests: dict[OnlyOrderId, OnlyBrokerCancelRequest] = {}
        self._durable_commands: set[tuple[OnlyBrokerCommandOperation, str]] = set()
        recovered = evidence.load()
        self._sequence = len(recovered)
        self._dispatched_order_ids: set[OnlyOrderId] = set()
        self._evidence_identity_by_client: dict[str, OnlyOrderId] = {}
        self._venue_by_order: dict[OnlyOrderId, OnlyVenueOrderId] = {}
        self._order_by_venue: dict[OnlyVenueOrderId, OnlyOrderId] = {}
        evidence_client_by_order: dict[OnlyOrderId, str] = {}
        latest_by_command: dict[tuple[OnlyBrokerCommandOperation, str], OnlyBrokerCommandEvidenceKind] = {}
        latest_detail_by_command: dict[tuple[OnlyBrokerCommandOperation, str], str] = {}
        for item in recovered:
            key = only_binance_client_order_id(item.client_order_id)
            prior = self._evidence_identity_by_client.get(key)
            if prior is not None and prior != item.order_id:
                self._readiness.identity_conflict()
                raise ValueError("BINANCE_COMMAND_EVIDENCE_IDENTITY_CONFLICT")
            self._evidence_identity_by_client[key] = item.order_id
            if evidence_client_by_order.setdefault(item.order_id, key) != key:
                self._readiness.identity_conflict()
                raise ValueError("BINANCE_COMMAND_EVIDENCE_IDENTITY_CONFLICT")
            if item.venue_order_id is not None:
                prior_venue = self._venue_by_order.setdefault(item.order_id, item.venue_order_id)
                prior_order = self._order_by_venue.setdefault(item.venue_order_id, item.order_id)
                if prior_venue != item.venue_order_id or prior_order != item.order_id:
                    self._readiness.identity_conflict()
                    raise ValueError("BINANCE_COMMAND_EVIDENCE_VENUE_IDENTITY_CONFLICT")
            command_id = item.command_id or f"SUBMIT:{item.order_id}"
            if item.kind is OnlyBrokerCommandEvidenceKind.INTENT_DURABLE:
                self._durable_commands.add((item.operation, command_id))
            latest_by_command[(item.operation, command_id)] = item.kind
            latest_detail_by_command[(item.operation, command_id)] = item.detail_code
            if (
                item.operation is OnlyBrokerCommandOperation.SUBMIT
                and item.kind is OnlyBrokerCommandEvidenceKind.DISPATCHED
            ):
                self._dispatched_order_ids.add(item.order_id)
            if item.kind is OnlyBrokerCommandEvidenceKind.INTENT_DURABLE and item.request_payload:
                if item.operation is OnlyBrokerCommandOperation.SUBMIT:
                    self.restore_order_request(OnlyBrokerOrderRequest.from_json(item.request_payload))
                else:
                    cancel_request = OnlyBrokerCancelRequest.from_json(item.request_payload)
                    self._cancel_requests[cancel_request.order_id] = cancel_request
        self._unresolved_commands: set[tuple[OnlyBrokerCommandOperation, str]] = set()
        self._known_command_results: dict[tuple[OnlyBrokerCommandOperation, str], str] = {}
        for command, kind in latest_by_command.items():
            if kind in {
                OnlyBrokerCommandEvidenceKind.DISPATCHED,
                OnlyBrokerCommandEvidenceKind.UNKNOWN,
                OnlyBrokerCommandEvidenceKind.RECONCILIATION_STARTED,
            }:
                self._unresolved_commands.add(command)
                self._readiness.mark_unknown(command[1])
            elif kind is OnlyBrokerCommandEvidenceKind.KNOWN_RESULT:
                self._known_command_results[command] = latest_detail_by_command[command]

    @property
    def capabilities(self) -> OnlyBrokerCapabilities:
        return _CAPABILITIES

    def connect(self) -> OnlyBrokerConnectionResult:
        self._readiness.transport_connected()
        return OnlyBrokerConnectionResult(OnlyBrokerOperationStatus.RECEIVED, self.connection_snapshot())

    def authenticate(self) -> OnlyBrokerConnectionResult:
        self._rest.authenticate_account()
        self._readiness.authenticated()
        self._readiness.account_scope_established()
        return OnlyBrokerConnectionResult(OnlyBrokerOperationStatus.RECEIVED, self.connection_snapshot())

    def disconnect(self) -> OnlyBrokerConnectionResult:
        self._readiness.disconnected()
        return OnlyBrokerConnectionResult(OnlyBrokerOperationStatus.RECEIVED, self.connection_snapshot())

    def connection_snapshot(self) -> OnlyBrokerConnectionSnapshot:
        snapshot = self._readiness.snapshot
        return OnlyBrokerConnectionSnapshot(self._gateway_id, snapshot.state, self._now())

    def baseline_discovered(self) -> None:
        self._readiness.discovery_completed()

    def reconciliation_converged(self) -> None:
        self._readiness.reconciliation_converged()

    def stream_trusted(self) -> None:
        self._readiness.stream_trusted()

    def stream_lost(self) -> None:
        self._readiness.stream_lost()

    def restore_order_request(self, request: OnlyBrokerOrderRequest) -> None:
        """Restore provider correlation state from authoritative local Order evidence."""
        key = only_binance_client_order_id(request.client_order_id)
        evidence_order_id = self._evidence_identity_by_client.get(key)
        if evidence_order_id is not None and evidence_order_id != request.order_id:
            self._readiness.identity_conflict()
            raise ValueError("BINANCE_CLIENT_ORDER_IDENTITY_CONFLICT")
        prior = self._requests.get(key)
        if prior is not None and not _same_semantic_order(prior, request):
            self._readiness.identity_conflict()
            raise ValueError("BINANCE_CLIENT_ORDER_IDENTITY_CONFLICT")
        self._requests[key] = request

    def resolve_order_identity(
        self, wire_client_order_id: str, venue_order_id: str
    ) -> OnlyBinanceResolvedOrderIdentity:
        """Correlate provider identity without becoming Order projection authority."""

        from onlyalpha_plugin_binance.spot.broker.stream import OnlyBinanceResolvedOrderIdentity

        request = self._requests.get(wire_client_order_id)
        if request is None:
            self._readiness.identity_conflict()
            raise ValueError("BINANCE_CLIENT_ORDER_IDENTITY_UNPROVABLE")
        venue = OnlyVenueOrderId(venue_order_id)
        known_venue = self._venue_by_order.get(request.order_id)
        known_order = self._order_by_venue.get(venue)
        if (known_venue is not None and known_venue != venue) or (
            known_order is not None and known_order != request.order_id
        ):
            self._readiness.identity_conflict()
            raise ValueError("BINANCE_VENUE_ORDER_IDENTITY_CONFLICT")
        self._venue_by_order[request.order_id] = venue
        self._order_by_venue[venue] = request.order_id
        return OnlyBinanceResolvedOrderIdentity(request.order_id, request.client_order_id)

    def submit_order(self, request: OnlyBrokerOrderRequest) -> OnlyBrokerOrderSubmitResult:
        if not request.runtime_intent_transaction_id or not request.runtime_intent_authority_hash:
            return OnlyBrokerOrderSubmitResult(
                False,
                OnlyBrokerOperationStatus.NOT_READY,
                request.gateway_request_id,
                request.client_order_id,
                "RUNTIME_ORDER_INTENT_REFERENCE_MISSING",
            )
        key = only_binance_client_order_id(request.client_order_id)
        prior = self._requests.get(key)
        if prior is not None and not _same_semantic_order(prior, request):
            self._readiness.identity_conflict()
            raise ValueError("BINANCE_CLIENT_ORDER_IDENTITY_CONFLICT")
        command_id = self._command_id(OnlyBrokerCommandOperation.SUBMIT, request)
        command_key = OnlyBrokerCommandOperation.SUBMIT, command_id
        known_detail = self._known_command_results.get(command_key)
        if known_detail is not None:
            return OnlyBrokerOrderSubmitResult(
                not known_detail,
                OnlyBrokerOperationStatus.REJECTED if known_detail else OnlyBrokerOperationStatus.RECEIVED,
                request.gateway_request_id,
                request.client_order_id,
                known_detail,
            )
        if request.order_id in self._dispatched_order_ids or command_key in self._unresolved_commands:
            return OnlyBrokerOrderSubmitResult(
                False,
                OnlyBrokerOperationStatus.UNKNOWN,
                request.gateway_request_id,
                request.client_order_id,
                "semantic submission already dispatched; reconcile by ClientOrderId",
            )
        if not self._readiness.snapshot.ready:
            return OnlyBrokerOrderSubmitResult(
                False,
                OnlyBrokerOperationStatus.NOT_READY,
                request.gateway_request_id,
                request.client_order_id,
                "Broker is not READY",
            )
        self._requests[key] = request
        if command_key not in self._durable_commands:
            self._append(OnlyBrokerCommandEvidenceKind.INTENT_DURABLE, request)
            self._durable_commands.add(command_key)
        self._before_dispatch(OnlyBrokerCommandOperation.SUBMIT, request.order_id)
        self._append(OnlyBrokerCommandEvidenceKind.DISPATCHED, request)
        self._dispatched_order_ids.add(request.order_id)
        try:
            response = self._rest.submit_order(request)
            self._bind_submit_response(request, response)
        except OnlyBinancePrivateRequestError as exc:
            if exc.knowledge is OnlyBinanceDispatchKnowledge.UNKNOWN:
                self._append(OnlyBrokerCommandEvidenceKind.UNKNOWN, request, detail_code=exc.code)
                self._unresolved_commands.add(command_key)
                self._readiness.mark_unknown(command_id)
                return OnlyBrokerOrderSubmitResult(
                    True,
                    OnlyBrokerOperationStatus.UNKNOWN,
                    request.gateway_request_id,
                    request.client_order_id,
                    exc.code,
                )
            self._append(OnlyBrokerCommandEvidenceKind.KNOWN_RESULT, request, detail_code=exc.code)
            self._known_command_results[command_key] = exc.code
            return OnlyBrokerOrderSubmitResult(
                False,
                OnlyBrokerOperationStatus.REJECTED,
                request.gateway_request_id,
                request.client_order_id,
                exc.code,
            )
        self._append(OnlyBrokerCommandEvidenceKind.KNOWN_RESULT, request)
        self._known_command_results[command_key] = ""
        return OnlyBrokerOrderSubmitResult(
            True,
            OnlyBrokerOperationStatus.RECEIVED,
            request.gateway_request_id,
            request.client_order_id,
        )

    def cancel_order(self, request: OnlyBrokerCancelRequest) -> OnlyBrokerCancelResult:
        order = self._require_request(request.order_id)
        canonical = (
            request if request.client_order_id is not None else replace(request, client_order_id=order.client_order_id)
        )
        command_id = self._command_id(OnlyBrokerCommandOperation.CANCEL, canonical)
        command_key = OnlyBrokerCommandOperation.CANCEL, command_id
        if canonical.venue_order_id is not None:
            self.resolve_order_identity(
                only_binance_client_order_id(order.client_order_id),
                str(canonical.venue_order_id),
            )
        known_detail = self._known_command_results.get(command_key)
        if known_detail is not None:
            return OnlyBrokerCancelResult(
                not known_detail,
                OnlyBrokerOperationStatus.REJECTED if known_detail else OnlyBrokerOperationStatus.RECEIVED,
                request.gateway_request_id,
                known_detail,
            )
        if command_key in self._unresolved_commands:
            return OnlyBrokerCancelResult(
                False,
                OnlyBrokerOperationStatus.UNKNOWN,
                request.gateway_request_id,
                "cancel command outcome unresolved; reconcile same order identity",
            )
        if command_key not in self._durable_commands:
            self._append(
                OnlyBrokerCommandEvidenceKind.INTENT_DURABLE,
                canonical,
                operation=OnlyBrokerCommandOperation.CANCEL,
            )
            self._durable_commands.add(command_key)
        self._cancel_requests[request.order_id] = canonical
        self._before_dispatch(OnlyBrokerCommandOperation.CANCEL, request.order_id)
        self._append(OnlyBrokerCommandEvidenceKind.DISPATCHED, canonical, operation=OnlyBrokerCommandOperation.CANCEL)
        try:
            response = self._rest.cancel_order(canonical, symbol=order.instrument_id.symbol.value)
            self._validate_cancel_response(order, response)
        except OnlyBinancePrivateRequestError as exc:
            self._append(
                OnlyBrokerCommandEvidenceKind.UNKNOWN
                if exc.knowledge is OnlyBinanceDispatchKnowledge.UNKNOWN
                else OnlyBrokerCommandEvidenceKind.KNOWN_RESULT,
                canonical,
                operation=OnlyBrokerCommandOperation.CANCEL,
                detail_code=exc.code,
            )
            if exc.knowledge is OnlyBinanceDispatchKnowledge.UNKNOWN:
                self._unresolved_commands.add(command_key)
                self._readiness.mark_unknown(command_id)
            else:
                self._known_command_results[command_key] = exc.code
            return OnlyBrokerCancelResult(
                exc.knowledge is OnlyBinanceDispatchKnowledge.UNKNOWN,
                OnlyBrokerOperationStatus.UNKNOWN
                if exc.knowledge is OnlyBinanceDispatchKnowledge.UNKNOWN
                else OnlyBrokerOperationStatus.REJECTED,
                request.gateway_request_id,
                exc.code,
            )
        self._append(
            OnlyBrokerCommandEvidenceKind.KNOWN_RESULT,
            canonical,
            operation=OnlyBrokerCommandOperation.CANCEL,
        )
        self._known_command_results[command_key] = ""
        return OnlyBrokerCancelResult(True, OnlyBrokerOperationStatus.RECEIVED, request.gateway_request_id)

    def query_account(self, account_id: OnlyAccountId) -> OnlyBrokerAccountSnapshot:
        self._require_account(account_id)
        OnlyBinanceSpotAccountDto.parse(self._rest.account())
        raise NotImplementedError("BINANCE_SPOT_MULTI_ASSET_ACCOUNT_SNAPSHOT_UNSUPPORTED; use query_balances")

    def query_balances(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerBalanceSnapshot, ...]:
        self._require_account(account_id)
        return only_normalize_binance_spot_balances(self._rest.account(), self._currencies)

    def query_positions(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerPositionSnapshot, ...]:
        self._require_account(account_id)
        return ()

    def query_open_orders(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerOrderSnapshot, ...]:
        self._require_account(account_id)
        return self._normalize_orders(self._rest.open_orders())

    def query_orders(
        self, account_id: OnlyAccountId, query: OnlyBrokerQuery | None = None
    ) -> tuple[OnlyBrokerOrderSnapshot, ...]:
        self._require_account(account_id)
        del query
        snapshots = []
        for request in sorted(self._requests.values(), key=lambda item: str(item.order_id)):
            payload = self._rest.query_order(
                symbol=request.instrument_id.symbol.value,
                client_order_id=request.client_order_id,
            )
            snapshots.append(
                only_normalize_binance_spot_order(
                    payload,
                    request,
                    gateway_id=self._gateway_id,
                    source_sequence=self._next_sequence(),
                )
            )
        return tuple(snapshots)

    def query_trades(
        self, account_id: OnlyAccountId, query: OnlyBrokerQuery | None = None
    ) -> tuple[OnlyBrokerTradeSnapshot, ...]:
        self._require_account(account_id)
        del query
        snapshots: list[OnlyBrokerTradeSnapshot] = []
        for request in sorted(self._requests.values(), key=lambda item: str(item.order_id)):
            venue_order_id = self._query_venue_order_id(request)
            raw = OnlyBinanceSpotTradesDto.parse(
                self._rest.trades(
                    symbol=request.instrument_id.symbol.value,
                    venue_order_id=venue_order_id,
                )
            ).raw
            for item in raw:
                if str(item.get("orderId")) == "None":
                    raise OnlyBinanceSchemaError("BINANCE_TRADE_ORDER_ID_INVALID")
                venue_order_id = OnlyVenueOrderId(str(item["orderId"]))
                price = _decimal(item.get("price"), "BINANCE_TRADE_PRICE")
                quantity = _decimal(item.get("qty"), "BINANCE_TRADE_QUANTITY")
                trade_id = item.get("id")
                time_ms = item.get("time")
                if not isinstance(trade_id, int | str) or not isinstance(time_ms, int):
                    raise OnlyBinanceSchemaError("BINANCE_TRADE_IDENTITY_INVALID")
                fill = OnlyOrderFill(
                    OnlyTradeId(f"BINANCE:{request.instrument_id.symbol.value}:{trade_id}"),
                    request.order_id,
                    OnlyPrice(price, _precision(price)),
                    OnlyQuantity(quantity, _precision(quantity)),
                    OnlyTimestamp.from_unix_nanos(time_ms * 1_000_000),
                    self._now(),
                    OnlyVenueTradeId(str(trade_id)),
                    venue_order_id,
                    OnlyLiquiditySide.MAKER if item.get("isMaker") is True else OnlyLiquiditySide.TAKER,
                    external_sequence=(int(trade_id) if isinstance(trade_id, int) else None),
                    external_event_id=f"binance-trade:{request.instrument_id.symbol.value}:{trade_id}",
                )
                snapshots.append(
                    OnlyBrokerTradeSnapshot(
                        self._gateway_id,
                        account_id,
                        fill.trade_id,
                        fill,
                        int(trade_id) if isinstance(trade_id, int) else 0,
                    )
                )
        return tuple(snapshots)

    def query_fee_evidence(self, account_id: OnlyAccountId) -> tuple[OnlyExternalFeeEvidence, ...]:
        self._require_account(account_id)
        evidence: list[OnlyExternalFeeEvidence] = []
        for request in sorted(self._requests.values(), key=lambda item: str(item.order_id)):
            symbol = request.instrument_id.symbol.value
            venue_order_id = self._query_venue_order_id(request)
            raw = OnlyBinanceSpotTradesDto.parse(self._rest.trades(symbol=symbol, venue_order_id=venue_order_id)).raw
            for item in raw:
                trade_id = item.get("id")
                time_ms = item.get("time")
                asset = item.get("commissionAsset")
                if (
                    not isinstance(trade_id, int | str)
                    or isinstance(trade_id, bool)
                    or not isinstance(time_ms, int)
                    or isinstance(time_ms, bool)
                    or not isinstance(asset, str)
                ):
                    raise OnlyBinanceSchemaError("BINANCE_TRADE_FEE_IDENTITY_INVALID")
                currency = self._currencies.get(asset)
                if currency is None:
                    raise OnlyBinanceSchemaError(f"BINANCE_TRADE_FEE_CURRENCY_UNRESOLVED: {asset}")
                commission = _decimal(item.get("commission"), "BINANCE_TRADE_COMMISSION")
                canonical_trade_id = OnlyTradeId(f"BINANCE:{symbol}:{trade_id}")
                occurred_at = OnlyTimestamp.from_unix_nanos(time_ms * 1_000_000)
                evidence.append(
                    OnlyExternalFeeEvidence.create(
                        broker_id=str(self._gateway_id),
                        account_id=account_id,
                        scope=OnlyExternalFeeEvidenceScope.trade(canonical_trade_id),
                        mode=OnlyExternalFeeEvidenceMode.COMMISSION_ONLY,
                        external_reference=f"binance-trade:{symbol}:{trade_id}:commission",
                        report_version="binance-spot-myTrades-v3",
                        revision_sequence=1,
                        supersedes_evidence_id=None,
                        reported_total=OnlyMoney(commission, currency),
                        reported_components=(),
                        effective_at=occurred_at,
                        received_at=self._now(),
                    )
                )
        return tuple(sorted(evidence, key=lambda item: item.evidence_id))

    def _query_venue_order_id(self, request: OnlyBrokerOrderRequest) -> OnlyVenueOrderId:
        payload = self._rest.query_order(
            symbol=request.instrument_id.symbol.value,
            client_order_id=request.client_order_id,
        )
        snapshot = only_normalize_binance_spot_order(
            payload,
            request,
            gateway_id=self._gateway_id,
            source_sequence=self._next_sequence(),
        )
        self.resolve_order_identity(
            only_binance_client_order_id(request.client_order_id),
            str(snapshot.venue_order_id),
        )
        return snapshot.venue_order_id

    def _normalize_orders(self, payload: bytes) -> tuple[OnlyBrokerOrderSnapshot, ...]:
        raw = OnlyBinanceSpotOrdersDto.parse(payload).raw
        result = []
        for item in raw:
            client = item.get("clientOrderId")
            if not isinstance(client, str) or client not in self._requests:
                self._readiness.identity_conflict()
                raise OnlyBinanceSchemaError("BINANCE_DISCOVERED_CLIENT_ORDER_ID_UNPROVABLE")
            request = self._requests[client]
            snapshot = only_normalize_binance_spot_order(
                json.dumps(item).encode("utf-8"),
                request,
                gateway_id=self._gateway_id,
                source_sequence=self._next_sequence(),
            )
            self.resolve_order_identity(client, str(snapshot.venue_order_id))
            result.append(snapshot)
        return tuple(result)

    def _bind_submit_response(self, request: OnlyBrokerOrderRequest, payload: bytes) -> None:
        try:
            raw = json.loads(payload)
            raw_venue_order_id = raw.get("orderId") if isinstance(raw, dict) else None
            client_order_id = raw.get("clientOrderId") if isinstance(raw, dict) else None
            if (
                not isinstance(raw_venue_order_id, int | str)
                or isinstance(raw_venue_order_id, bool)
                or client_order_id != only_binance_client_order_id(request.client_order_id)
            ):
                raise OnlyBinanceSchemaError("BINANCE_SUBMIT_ACK_IDENTITY_INVALID")
            venue_order_id = OnlyVenueOrderId(str(raw_venue_order_id))
        except (json.JSONDecodeError, UnicodeDecodeError, OnlyBinanceSchemaError, ValueError) as exc:
            raise OnlyBinancePrivateRequestError(
                "BINANCE_PRIVATE_EXECUTION_UNKNOWN: SUBMIT_ACK_INVALID",
                OnlyBinanceDispatchKnowledge.UNKNOWN,
            ) from exc
        self.resolve_order_identity(str(client_order_id), str(venue_order_id))

    def _validate_cancel_response(self, order: OnlyBrokerOrderRequest, payload: bytes) -> None:
        try:
            raw = json.loads(payload)
            raw_venue_order_id = raw.get("orderId") if isinstance(raw, dict) else None
            status = raw.get("status") if isinstance(raw, dict) else None
            if (
                not isinstance(raw_venue_order_id, int | str)
                or isinstance(raw_venue_order_id, bool)
                or status != "CANCELED"
            ):
                raise OnlyBinanceSchemaError("BINANCE_CANCEL_ACK_IDENTITY_INVALID")
            venue_order_id = OnlyVenueOrderId(str(raw_venue_order_id))
        except (json.JSONDecodeError, UnicodeDecodeError, OnlyBinanceSchemaError, ValueError) as exc:
            raise OnlyBinancePrivateRequestError(
                "BINANCE_PRIVATE_EXECUTION_UNKNOWN: CANCEL_ACK_INVALID",
                OnlyBinanceDispatchKnowledge.UNKNOWN,
            ) from exc
        self.resolve_order_identity(
            only_binance_client_order_id(order.client_order_id),
            str(venue_order_id),
        )

    def _require_request(self, order_id: OnlyOrderId) -> OnlyBrokerOrderRequest:
        matches = tuple(item for item in self._requests.values() if item.order_id == order_id)
        if len(matches) != 1:
            raise ValueError("BINANCE_ORDER_IDENTITY_UNPROVABLE")
        return matches[0]

    def _require_account(self, account_id: OnlyAccountId) -> None:
        if account_id != self._account_id:
            raise ValueError("BINANCE_ACCOUNT_IDENTITY_CONFLICT")

    def _append(
        self,
        kind: OnlyBrokerCommandEvidenceKind,
        request: OnlyBrokerOrderRequest | OnlyBrokerCancelRequest,
        *,
        operation: OnlyBrokerCommandOperation = OnlyBrokerCommandOperation.SUBMIT,
        detail_code: str = "",
    ) -> None:
        self._sequence += 1
        payload = request.to_json()
        fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        client_order_id = request.client_order_id
        if client_order_id is None:
            raise ValueError("BINANCE_COMMAND_CLIENT_ORDER_ID_REQUIRED")
        self._evidence.append(
            OnlyBrokerCommandEvidence(
                f"{request.order_id}:{operation.value}:{self._sequence:08d}:{kind.value}",
                kind,
                request.order_id,
                client_order_id,
                request.venue_order_id if isinstance(request, OnlyBrokerCancelRequest) else None,
                self._now(),
                detail_code,
                operation,
                self._command_id(operation, request),
                payload,
                fingerprint,
                request.runtime_intent_transaction_id if isinstance(request, OnlyBrokerOrderRequest) else "",
                request.runtime_intent_authority_hash if isinstance(request, OnlyBrokerOrderRequest) else "",
            )
        )

    @staticmethod
    def _command_id(
        operation: OnlyBrokerCommandOperation,
        request: OnlyBrokerOrderRequest | OnlyBrokerCancelRequest,
    ) -> str:
        if operation is OnlyBrokerCommandOperation.SUBMIT:
            return f"SUBMIT:{request.order_id}"
        return f"CANCEL:{request.order_id}"

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence


__all__ = ["OnlyBinanceSpotBrokerGateway"]
