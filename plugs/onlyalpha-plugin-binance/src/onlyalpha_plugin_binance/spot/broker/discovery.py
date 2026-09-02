"""Binance venue discovery translated into canonical Broker facts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerRequestId, OnlyBrokerUpdateId
from onlyalpha.broker.models import OnlyBrokerOrderRequest, OnlyBrokerOrderSnapshot
from onlyalpha.broker.reconciliation import (
    OnlyBrokerCommandOperation,
    OnlyBrokerVenueDiscoveryResult,
    OnlyBrokerVenuePresence,
)
from onlyalpha.broker.updates import (
    OnlyBrokerInboundUpdate,
    OnlyBrokerOrderAcceptedUpdate,
    OnlyBrokerOrderCancelledUpdate,
    OnlyBrokerOrderExpiredUpdate,
    OnlyBrokerOrderRejectedUpdate,
    OnlyBrokerTradeUpdate,
)
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.execution import OnlyOrderRejection, OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha_plugin_binance.common.private_http import OnlyBinancePrivateRequestError
from onlyalpha_plugin_binance.spot.broker.codec import only_binance_client_order_id
from onlyalpha_plugin_binance.spot.broker.gateway import OnlyBinanceSpotBrokerGateway
from onlyalpha_plugin_binance.spot.broker.normalize import only_normalize_binance_spot_order
from onlyalpha_plugin_binance.spot.broker.rest import OnlyBinanceSpotPrivateRestClient

# Binance may omit zero-execution CANCELED/EXPIRED orders after three days.
# A negative lookup beyond that boundary cannot prove that submit never existed.
_BINANCE_STRONG_NEGATIVE_PROOF_WINDOW_NS = 3 * 24 * 60 * 60 * 1_000_000_000


class OnlyBinanceOrderPresenceClassifier:
    """Maps mutable Binance query semantics to the provider-neutral proof contract."""

    @staticmethod
    def classify(
        error: OnlyBinancePrivateRequestError,
        *,
        operation: OnlyBrokerCommandOperation,
        order: OnlyOrderSnapshot,
        observed_at: OnlyTimestamp,
        stable_venue_history: bool,
    ) -> OnlyBrokerVenuePresence:
        recent_exact_submit_query = (
            operation is OnlyBrokerCommandOperation.SUBMIT
            and stable_venue_history
            and observed_at.unix_nanos >= order.created_at.unix_nanos
            and observed_at.unix_nanos - order.created_at.unix_nanos <= _BINANCE_STRONG_NEGATIVE_PROOF_WINDOW_NS
        )
        if error.code == "BINANCE_PRIVATE_KNOWN_ERROR: -2013" and recent_exact_submit_query:
            return OnlyBrokerVenuePresence.ABSENT_PROVEN
        return OnlyBrokerVenuePresence.INCONCLUSIVE


class OnlyBinanceSpotVenueDiscovery:
    def __init__(
        self,
        *,
        runtime_id: OnlyRuntimeId,
        gateway_id: OnlyBrokerGatewayId,
        account_id: OnlyAccountId,
        rest: OnlyBinanceSpotPrivateRestClient,
        gateway: OnlyBinanceSpotBrokerGateway,
        now: Callable[[], OnlyTimestamp],
        stable_venue_history: bool = False,
    ) -> None:
        self._runtime_id = runtime_id
        self._gateway_id = gateway_id
        self._account_id = account_id
        self._rest = rest
        self._gateway = gateway
        self._now = now
        self._sequence = 0
        self._stable_venue_history = stable_venue_history

    def discover_order(
        self,
        order: OnlyOrderSnapshot,
        *,
        operation: OnlyBrokerCommandOperation,
    ) -> OnlyBrokerVenueDiscoveryResult:
        if order.runtime_id != self._runtime_id or order.account_id != self._account_id:
            raise ValueError("BINANCE_DISCOVERY_SCOPE_CONFLICT")
        request = self._request(order)
        self._gateway.restore_order_request(request)
        observed_at = self._now()
        try:
            venue = self._query_order(request)
        except OnlyBinancePrivateRequestError as exc:
            presence = OnlyBinanceOrderPresenceClassifier.classify(
                exc,
                operation=operation,
                order=order,
                observed_at=observed_at,
                stable_venue_history=self._stable_venue_history,
            )
            return self._result(
                order,
                operation,
                presence,
                observed_at,
                proof_detail=exc.code,
            )
        self._gateway.resolve_order_identity(
            only_binance_client_order_id(order.client_order_id),
            str(venue.venue_order_id),
        )
        common = {
            "runtime_id": self._runtime_id,
            "gateway_id": self._gateway_id,
            "account_id": self._account_id,
            # REST order snapshots do not expose a total provider event sequence.
            # Zero is a sentinel paired with an explicit quality flag; the Core
            # must not interpret it as fabricated provider history.
            "source_sequence": 0,
            "ts_event": venue.updated_at,
            "ts_init": self._now(),
            "correlation_id": str(order.client_order_id),
            "causation_id": "binance-reconciliation",
            "order_id": order.order_id,
            "quality_flags": ("RECONCILIATION_DISCOVERY", "PROVIDER_SEQUENCE_UNAVAILABLE"),
        }
        updates: list[OnlyBrokerInboundUpdate] = []
        if venue.status in {OnlyOrderStatus.ACCEPTED, OnlyOrderStatus.PARTIALLY_FILLED} and (
            order.status is OnlyOrderStatus.SUBMITTED or order.venue_order_id is None
        ):
            updates.append(
                OnlyBrokerOrderAcceptedUpdate(
                    **common,  # type: ignore[arg-type]
                    update_id=OnlyBrokerUpdateId(f"binance-order:{venue.venue_order_id}:accepted"),
                    venue_order_id=venue.venue_order_id,
                )
            )
        for trade in self._gateway.query_trades(self._account_id):
            if trade.fill.order_id == order.order_id:
                updates.append(
                    OnlyBrokerTradeUpdate(
                        runtime_id=self._runtime_id,
                        gateway_id=self._gateway_id,
                        account_id=self._account_id,
                        update_id=OnlyBrokerUpdateId(str(trade.fill.external_event_id)),
                        source_sequence=trade.source_sequence,
                        ts_event=trade.fill.ts_event,
                        ts_init=trade.fill.ts_init,
                        correlation_id=str(order.client_order_id),
                        causation_id="binance-reconciliation",
                        quality_flags=(
                            "RECONCILIATION_DISCOVERY",
                            *(("PROVIDER_SEQUENCE_UNAVAILABLE",) if trade.source_sequence == 0 else ()),
                        ),
                        order_id=order.order_id,
                        fill=trade.fill,
                    )
                )
        terminal = {
            OnlyOrderStatus.CANCELLED: OnlyBrokerOrderCancelledUpdate,
            OnlyOrderStatus.EXPIRED: OnlyBrokerOrderExpiredUpdate,
        }.get(venue.status)
        if terminal is not None:
            updates.append(
                terminal(
                    **common,  # type: ignore[arg-type]
                    update_id=OnlyBrokerUpdateId(f"binance-order:{venue.venue_order_id}:{venue.status.value}"),
                    venue_order_id=venue.venue_order_id,
                )
            )
        elif venue.status is OnlyOrderStatus.REJECTED:
            updates.append(
                OnlyBrokerOrderRejectedUpdate(
                    **common,  # type: ignore[arg-type]
                    update_id=OnlyBrokerUpdateId(f"binance-order:{venue.venue_order_id}:rejected"),
                    rejection=OnlyOrderRejection("VENUE_REJECTED", "Binance rejected order"),
                    venue_order_id=venue.venue_order_id,
                )
            )
        return self._result(
            order,
            operation,
            OnlyBrokerVenuePresence.PRESENT,
            observed_at,
            venue=venue,
            updates=tuple(updates),
        )

    def verify_order(self, order: OnlyOrderSnapshot) -> bool:
        if order.runtime_id != self._runtime_id or order.account_id != self._account_id:
            return False
        request = self._request(order)
        self._gateway.restore_order_request(request)
        venue = self._query_order(request)
        identity_matches = (
            venue.order_id == order.order_id
            and venue.client_order_id == order.client_order_id
            and (order.venue_order_id is None or venue.venue_order_id == order.venue_order_id)
        )
        return identity_matches and venue.status is order.status and venue.filled_quantity == order.filled_quantity

    @staticmethod
    def _request(order: OnlyOrderSnapshot) -> OnlyBrokerOrderRequest:
        return OnlyBrokerOrderRequest(
            gateway_request_id=OnlyBrokerRequestId(f"reconcile-{order.order_id}"),
            order_id=order.order_id,
            client_order_id=order.client_order_id,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            side=order.side,
            offset=order.offset,
            order_type=order.order_type,
            time_in_force=order.time_in_force,
            quantity=order.quantity,
            price=order.price,
            submitted_at=order.submitted_at or order.created_at,
        )

    def _query_order(self, request: OnlyBrokerOrderRequest) -> OnlyBrokerOrderSnapshot:
        payload = self._rest.query_order(
            symbol=request.instrument_id.symbol.value,
            client_order_id=request.client_order_id,
        )
        return only_normalize_binance_spot_order(
            payload,
            request,
            gateway_id=self._gateway_id,
            source_sequence=self._next_sequence(),
        )

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    @staticmethod
    def _result(
        order: OnlyOrderSnapshot,
        operation: OnlyBrokerCommandOperation,
        presence: OnlyBrokerVenuePresence,
        observed_at: OnlyTimestamp,
        *,
        venue: OnlyBrokerOrderSnapshot | None = None,
        updates: tuple[OnlyBrokerInboundUpdate, ...] = (),
        proof_detail: str = "",
    ) -> OnlyBrokerVenueDiscoveryResult:
        proof_payload = json.dumps(
            {
                "provider": "BINANCE_SPOT",
                "query": "GET /api/v3/order by origClientOrderId",
                "operation": operation.value,
                "order_id": str(order.order_id),
                "client_order_id": str(order.client_order_id),
                "presence": presence.value,
                "venue_order_id": None if venue is None else str(venue.venue_order_id),
                "venue_status": None if venue is None else venue.status.value,
                "detail": proof_detail,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        fingerprint = hashlib.sha256(proof_payload.encode("utf-8")).hexdigest()
        return OnlyBrokerVenueDiscoveryResult(
            presence,
            order.order_id,
            operation,
            updates,
            f"BINANCE-SPOT-ORDER-PROOF-{fingerprint}",
            fingerprint,
            observed_at,
            venue,
        )


__all__ = ["OnlyBinanceOrderPresenceClassifier", "OnlyBinanceSpotVenueDiscovery"]
