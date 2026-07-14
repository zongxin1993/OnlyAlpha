"""Runtime-owned Order state truth, indexes and controlled mutations."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.execution import (
    OnlyOrderFailure,
    OnlyOrderFill,
    OnlyOrderRejection,
    OnlyOrderRequest,
    OnlyOrderSnapshot,
)
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClientOrderId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyOrderRequestId,
    OnlyRuntimeId,
    OnlyVenueOrderId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.model import OnlyEvent
from onlyalpha.order.entities import OnlyOrder, OnlyOrderEntityResult
from onlyalpha.order.enums import OnlyOrderApplyResult, OnlyOrderMutationType
from onlyalpha.order.events import (
    OnlyOrderAcceptedEvent,
    OnlyOrderCancelledEvent,
    OnlyOrderCancelRequestedEvent,
    OnlyOrderCreatedEvent,
    OnlyOrderExpiredEvent,
    OnlyOrderFailedEvent,
    OnlyOrderFilledEvent,
    OnlyOrderPartiallyFilledEvent,
    OnlyOrderRejectedEvent,
    OnlyOrderSubmittedEvent,
)
from onlyalpha.order.exceptions import OnlyOrderNotFoundError
from onlyalpha.order.id_generator import OnlyClientOrderIdGenerator, OnlyOrderIdGenerator
from onlyalpha.order.results import OnlyOrderMutationResult


class OnlyOrderManager:
    """Single-threaded unique Order truth for one Runtime."""

    def __init__(
        self,
        engine_id: OnlyEngineId,
        runtime_id: OnlyRuntimeId,
        order_id_generator: OnlyOrderIdGenerator,
        client_order_id_generator: OnlyClientOrderIdGenerator,
    ) -> None:
        self.engine_id = engine_id
        self.runtime_id = runtime_id
        self._order_id_generator = order_id_generator
        self._client_order_id_generator = client_order_id_generator
        self._orders: dict[OnlyOrderId, OnlyOrder] = {}
        self._order_id_by_request_id: dict[OnlyOrderRequestId, OnlyOrderId] = {}
        self._order_id_by_client_order_id: dict[OnlyClientOrderId, OnlyOrderId] = {}
        self._order_id_by_venue_order_id: dict[OnlyVenueOrderId, OnlyOrderId] = {}
        self._open_order_ids: set[OnlyOrderId] = set()
        self._order_ids_by_cluster_id: dict[OnlyClusterId, list[OnlyOrderId]] = {}
        self._order_ids_by_account_id: dict[OnlyAccountId, list[OnlyOrderId]] = {}
        self._order_ids_by_instrument_id: dict[OnlyInstrumentId, list[OnlyOrderId]] = {}
        self._creation_order: list[OnlyOrderId] = []
        self._event_sequence = 0

    def create_order(
        self,
        request: OnlyOrderRequest,
        cluster_id: OnlyClusterId,
        account_id: OnlyAccountId,
        timestamp: OnlyTimestamp,
    ) -> OnlyOrderMutationResult:
        existing_id = self._order_id_by_request_id.get(request.request_id)
        if existing_id is not None:
            snapshot = self._orders[existing_id].snapshot()
            return OnlyOrderMutationResult(
                existing_id,
                OnlyOrderMutationType.CREATED,
                None,
                snapshot.status,
                OnlyOrderApplyResult.DUPLICATE,
                False,
                True,
                False,
                snapshot.version,
                snapshot,
            )
        order_id = self._order_id_generator.next_id()
        client_order_id = self._client_order_id_generator.next_id()
        order = OnlyOrder(request, order_id, client_order_id, self.runtime_id, cluster_id, account_id, timestamp)
        self._orders[order_id] = order
        self._order_id_by_request_id[request.request_id] = order_id
        self._order_id_by_client_order_id[client_order_id] = order_id
        self._open_order_ids.add(order_id)
        self._order_ids_by_cluster_id.setdefault(cluster_id, []).append(order_id)
        self._order_ids_by_account_id.setdefault(account_id, []).append(order_id)
        self._order_ids_by_instrument_id.setdefault(request.instrument_id, []).append(order_id)
        self._creation_order.append(order_id)
        snapshot = order.snapshot()
        event = self._event(OnlyOrderCreatedEvent, "ORDER_CREATED", snapshot, None, timestamp)
        return OnlyOrderMutationResult(
            order_id,
            OnlyOrderMutationType.CREATED,
            None,
            snapshot.status,
            OnlyOrderApplyResult.APPLIED,
            True,
            False,
            False,
            snapshot.version,
            snapshot,
            (event,),
        )

    def get_snapshot(self, order_id: OnlyOrderId) -> OnlyOrderSnapshot | None:
        order = self._orders.get(order_id)
        return None if order is None else order.snapshot()

    def require_snapshot(self, order_id: OnlyOrderId) -> OnlyOrderSnapshot:
        snapshot = self.get_snapshot(order_id)
        if snapshot is None:
            raise OnlyOrderNotFoundError(f"unknown Order: {order_id}")
        return snapshot

    def find_by_client_order_id(self, client_order_id: OnlyClientOrderId) -> OnlyOrderSnapshot | None:
        order_id = self._order_id_by_client_order_id.get(client_order_id)
        return None if order_id is None else self.require_snapshot(order_id)

    def find_by_venue_order_id(self, venue_order_id: OnlyVenueOrderId) -> OnlyOrderSnapshot | None:
        order_id = self._order_id_by_venue_order_id.get(venue_order_id)
        return None if order_id is None else self.require_snapshot(order_id)

    def mark_submitted(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> OnlyOrderMutationResult:
        return self._mutate(order_id, lambda order: order.mark_submitted(timestamp), timestamp)

    def apply_accepted(
        self,
        order_id: OnlyOrderId,
        timestamp: OnlyTimestamp,
        venue_order_id: OnlyVenueOrderId,
        *,
        external_sequence: int | None = None,
        external_event_id: str | None = None,
        event_time: OnlyTimestamp | None = None,
    ) -> OnlyOrderMutationResult:
        existing = self._order_id_by_venue_order_id.get(venue_order_id)
        if existing is not None and existing != order_id:
            snapshot = self.require_snapshot(order_id)
            return OnlyOrderMutationResult(
                order_id,
                OnlyOrderMutationType.ACCEPTED,
                snapshot.status,
                snapshot.status,
                OnlyOrderApplyResult.CONFLICT,
                False,
                False,
                False,
                snapshot.version,
                snapshot,
                error=f"venue_order_id already mapped: {venue_order_id}",
            )
        result = self._mutate(
            order_id,
            lambda order: order.apply_accepted(
                timestamp,
                venue_order_id,
                external_sequence=external_sequence,
                external_event_id=external_event_id,
            ),
            event_time or timestamp,
        )
        if result.changed:
            self._order_id_by_venue_order_id[venue_order_id] = order_id
        return result

    def apply_fill(self, fill: OnlyOrderFill) -> OnlyOrderMutationResult:
        snapshot = self.require_snapshot(fill.order_id)
        if fill.venue_order_id is not None:
            mapped = self._order_id_by_venue_order_id.get(fill.venue_order_id)
            if mapped is not None and mapped != fill.order_id:
                return OnlyOrderMutationResult(
                    fill.order_id,
                    OnlyOrderMutationType.FILLED,
                    snapshot.status,
                    snapshot.status,
                    OnlyOrderApplyResult.CONFLICT,
                    False,
                    False,
                    False,
                    snapshot.version,
                    snapshot,
                    error=f"venue_order_id already mapped: {fill.venue_order_id}",
                )
            if snapshot.venue_order_id is not None and snapshot.venue_order_id != fill.venue_order_id:
                return OnlyOrderMutationResult(
                    fill.order_id,
                    OnlyOrderMutationType.FILLED,
                    snapshot.status,
                    snapshot.status,
                    OnlyOrderApplyResult.CONFLICT,
                    False,
                    False,
                    False,
                    snapshot.version,
                    snapshot,
                    error="Fill venue_order_id conflicts with Order",
                )
        result = self._mutate(fill.order_id, lambda order: order.apply_fill(fill), fill.ts_event)
        if result.changed and fill.venue_order_id is not None:
            self._order_id_by_venue_order_id.setdefault(fill.venue_order_id, fill.order_id)
        return result

    def request_cancel(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> OnlyOrderMutationResult:
        return self._mutate(order_id, lambda order: order.request_cancel(timestamp), timestamp)

    def apply_cancelled(
        self,
        order_id: OnlyOrderId,
        timestamp: OnlyTimestamp,
        *,
        external_sequence: int | None = None,
        external_event_id: str | None = None,
        event_time: OnlyTimestamp | None = None,
    ) -> OnlyOrderMutationResult:
        return self._mutate(
            order_id,
            lambda order: order.apply_cancelled(
                timestamp,
                external_sequence=external_sequence,
                external_event_id=external_event_id,
            ),
            event_time or timestamp,
        )

    def apply_rejected(
        self,
        order_id: OnlyOrderId,
        timestamp: OnlyTimestamp,
        rejection: OnlyOrderRejection,
        *,
        external_sequence: int | None = None,
        external_event_id: str | None = None,
        event_time: OnlyTimestamp | None = None,
    ) -> OnlyOrderMutationResult:
        return self._mutate(
            order_id,
            lambda order: order.apply_rejected(
                timestamp,
                rejection,
                external_sequence=external_sequence,
                external_event_id=external_event_id,
            ),
            event_time or timestamp,
        )

    def apply_expired(
        self,
        order_id: OnlyOrderId,
        timestamp: OnlyTimestamp,
        *,
        external_sequence: int | None = None,
        external_event_id: str | None = None,
    ) -> OnlyOrderMutationResult:
        return self._mutate(
            order_id,
            lambda order: order.apply_expired(
                timestamp,
                external_sequence=external_sequence,
                external_event_id=external_event_id,
            ),
            timestamp,
        )

    def apply_failed(
        self,
        order_id: OnlyOrderId,
        timestamp: OnlyTimestamp,
        failure: OnlyOrderFailure,
    ) -> OnlyOrderMutationResult:
        return self._mutate(order_id, lambda order: order.apply_failed(timestamp, failure), timestamp)

    def list_open_orders(self) -> tuple[OnlyOrderSnapshot, ...]:
        return tuple(self._orders[item].snapshot() for item in self._creation_order if item in self._open_order_ids)

    def list_by_cluster(self, cluster_id: OnlyClusterId) -> tuple[OnlyOrderSnapshot, ...]:
        return self._snapshots(self._order_ids_by_cluster_id.get(cluster_id, ()))

    def list_by_account(self, account_id: OnlyAccountId) -> tuple[OnlyOrderSnapshot, ...]:
        return self._snapshots(self._order_ids_by_account_id.get(account_id, ()))

    def list_by_instrument(self, instrument_id: OnlyInstrumentId) -> tuple[OnlyOrderSnapshot, ...]:
        return self._snapshots(self._order_ids_by_instrument_id.get(instrument_id, ()))

    def list_recent(self, limit: int = 100) -> tuple[OnlyOrderSnapshot, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return self._snapshots(reversed(self._creation_order[-limit:]))

    def snapshot_all(self) -> tuple[OnlyOrderSnapshot, ...]:
        return self._snapshots(self._creation_order)

    def _mutate(
        self,
        order_id: OnlyOrderId,
        operation: Callable[[OnlyOrder], OnlyOrderEntityResult],
        event_time: OnlyTimestamp,
    ) -> OnlyOrderMutationResult:
        order = self._require_entity(order_id)
        entity_result = operation(order)
        snapshot = entity_result.snapshot
        if snapshot.status in {
            OnlyOrderStatus.CANCELLED,
            OnlyOrderStatus.FILLED,
            OnlyOrderStatus.REJECTED,
            OnlyOrderStatus.EXPIRED,
            OnlyOrderStatus.FAILED,
        }:
            self._open_order_ids.discard(order_id)
        elif snapshot.status in {
            OnlyOrderStatus.CREATED,
            OnlyOrderStatus.SUBMITTED,
            OnlyOrderStatus.ACCEPTED,
            OnlyOrderStatus.PARTIALLY_FILLED,
            OnlyOrderStatus.PENDING_CANCEL,
        }:
            self._open_order_ids.add(order_id)
        events: tuple[OnlyEvent, ...] = ()
        if entity_result.changed:
            event_class, event_type = self._event_spec(entity_result.mutation_type, snapshot.status)
            events = (self._event(event_class, event_type, snapshot, entity_result.previous_status, event_time),)
        return OnlyOrderMutationResult(
            order_id,
            entity_result.mutation_type,
            entity_result.previous_status,
            snapshot.status,
            entity_result.apply_result,
            entity_result.changed,
            entity_result.apply_result is OnlyOrderApplyResult.DUPLICATE,
            entity_result.apply_result is OnlyOrderApplyResult.STALE,
            snapshot.version,
            snapshot,
            events,
            entity_result.error,
            entity_result.warnings,
        )

    def _event(
        self,
        event_class: type[OnlyEvent],
        event_type: str,
        snapshot: OnlyOrderSnapshot,
        previous_status: OnlyOrderStatus | None,
        event_time: OnlyTimestamp,
    ) -> OnlyEvent:
        self._event_sequence += 1
        return event_class(
            event_type,
            event_time.to_datetime(),
            self.engine_id,
            snapshot.runtime_id,
            "order_manager",
            self._event_sequence,
            payload={
                "order_id": str(snapshot.order_id),
                "previous_status": None if previous_status is None else previous_status.value,
                "current_status": snapshot.status.value,
                "snapshot": snapshot.to_dict(),
            },
            cluster_id=snapshot.cluster_id,
            ts_init=snapshot.updated_at.to_datetime(),
            timestamp_ns=event_time.unix_nanos,
            ts_init_ns=snapshot.updated_at.unix_nanos,
        )

    @staticmethod
    def _event_spec(
        mutation: OnlyOrderMutationType,
        status: OnlyOrderStatus,
    ) -> tuple[type[OnlyEvent], str]:
        if mutation is OnlyOrderMutationType.FILLED:
            return (
                (OnlyOrderFilledEvent, "ORDER_FILLED")
                if status is OnlyOrderStatus.FILLED
                else (OnlyOrderPartiallyFilledEvent, "ORDER_PARTIALLY_FILLED")
            )
        mapping: dict[OnlyOrderMutationType, tuple[type[OnlyEvent], str]] = {
            OnlyOrderMutationType.SUBMITTED: (OnlyOrderSubmittedEvent, "ORDER_SUBMITTED"),
            OnlyOrderMutationType.ACCEPTED: (OnlyOrderAcceptedEvent, "ORDER_ACCEPTED"),
            OnlyOrderMutationType.CANCEL_REQUESTED: (
                OnlyOrderCancelRequestedEvent,
                "ORDER_CANCEL_REQUESTED",
            ),
            OnlyOrderMutationType.CANCELLED: (OnlyOrderCancelledEvent, "ORDER_CANCELLED"),
            OnlyOrderMutationType.REJECTED: (OnlyOrderRejectedEvent, "ORDER_REJECTED"),
            OnlyOrderMutationType.EXPIRED: (OnlyOrderExpiredEvent, "ORDER_EXPIRED"),
            OnlyOrderMutationType.FAILED: (OnlyOrderFailedEvent, "ORDER_FAILED"),
        }
        return mapping[mutation]

    def _require_entity(self, order_id: OnlyOrderId) -> OnlyOrder:
        try:
            return self._orders[order_id]
        except KeyError as exc:
            raise OnlyOrderNotFoundError(f"unknown Order: {order_id}") from exc

    def _snapshots(self, order_ids: Iterable[OnlyOrderId]) -> tuple[OnlyOrderSnapshot, ...]:
        return tuple(self._orders[item].snapshot() for item in order_ids)
