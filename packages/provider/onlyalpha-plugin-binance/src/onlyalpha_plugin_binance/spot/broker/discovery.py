"""Binance venue discovery translated into canonical Broker facts."""

from __future__ import annotations

from collections.abc import Callable

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId, OnlyBrokerRequestId, OnlyBrokerUpdateId
from onlyalpha.broker.models import OnlyBrokerOrderRequest, OnlyBrokerOrderSnapshot
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
from onlyalpha_plugin_binance.spot.broker.gateway import OnlyBinanceSpotBrokerGateway
from onlyalpha_plugin_binance.spot.broker.normalize import only_normalize_binance_spot_order
from onlyalpha_plugin_binance.spot.broker.rest import OnlyBinanceSpotPrivateRestClient


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
    ) -> None:
        self._runtime_id = runtime_id
        self._gateway_id = gateway_id
        self._account_id = account_id
        self._rest = rest
        self._gateway = gateway
        self._now = now
        self._sequence = 0

    def discover_order(self, order: OnlyOrderSnapshot) -> tuple[OnlyBrokerInboundUpdate, ...]:
        if order.runtime_id != self._runtime_id or order.account_id != self._account_id:
            raise ValueError("BINANCE_DISCOVERY_SCOPE_CONFLICT")
        request = self._request(order)
        self._gateway.restore_order_request(request)
        venue = self._query_order(request)
        common = {
            "runtime_id": self._runtime_id,
            "gateway_id": self._gateway_id,
            "account_id": self._account_id,
            "source_sequence": venue.source_sequence,
            "ts_event": venue.updated_at,
            "ts_init": self._now(),
            "correlation_id": str(order.client_order_id),
            "causation_id": "binance-reconciliation",
            "order_id": order.order_id,
            "quality_flags": ("RECONCILIATION_DISCOVERY",),
        }
        updates: list[OnlyBrokerInboundUpdate] = []
        if venue.status not in {OnlyOrderStatus.REJECTED, OnlyOrderStatus.EXPIRED}:
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
                        source_sequence=self._next_sequence(),
                        ts_event=trade.fill.ts_event,
                        ts_init=trade.fill.ts_init,
                        correlation_id=str(order.client_order_id),
                        causation_id="binance-reconciliation",
                        quality_flags=("RECONCILIATION_DISCOVERY",),
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
                )
            )
        elif venue.status is OnlyOrderStatus.REJECTED:
            updates.append(
                OnlyBrokerOrderRejectedUpdate(
                    **common,  # type: ignore[arg-type]
                    update_id=OnlyBrokerUpdateId(f"binance-order:{venue.venue_order_id}:rejected"),
                    rejection=OnlyOrderRejection("VENUE_REJECTED", "Binance rejected order"),
                )
            )
        return tuple(updates)

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


__all__ = ["OnlyBinanceSpotVenueDiscovery"]
