"""Manager-owned mutable Order aggregate; callers only receive snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

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
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyOrderRequestId,
    OnlyRuntimeId,
    OnlyTradeId,
    OnlyVenueOrderId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.fee.estimate import OnlyOrderFeeEstimate, OnlyOrderFundingPlan
from onlyalpha.fee.models import OnlyOrderFeePolicyBinding
from onlyalpha.order.enums import OnlyOrderApplyResult, OnlyOrderMutationType

ONLY_OPEN_ORDER_STATUSES = frozenset(
    {
        OnlyOrderStatus.CREATED,
        OnlyOrderStatus.SUBMITTED,
        OnlyOrderStatus.ACCEPTED,
        OnlyOrderStatus.PARTIALLY_FILLED,
        OnlyOrderStatus.PENDING_CANCEL,
    }
)
ONLY_TERMINAL_ORDER_STATUSES = frozenset(
    {
        OnlyOrderStatus.CANCELLED,
        OnlyOrderStatus.FILLED,
        OnlyOrderStatus.REJECTED,
        OnlyOrderStatus.EXPIRED,
        OnlyOrderStatus.FAILED,
    }
)


@dataclass(frozen=True, slots=True)
class OnlyOrderEntityResult:
    mutation_type: OnlyOrderMutationType
    previous_status: OnlyOrderStatus
    apply_result: OnlyOrderApplyResult
    changed: bool
    snapshot: OnlyOrderSnapshot
    error: str | None = None
    warnings: tuple[str, ...] = ()


class OnlyOrder:
    """Internal mutable entity whose state is changed only through domain methods."""

    def __init__(
        self,
        request: OnlyOrderRequest,
        order_id: OnlyOrderId,
        client_order_id: OnlyClientOrderId,
        runtime_id: OnlyRuntimeId,
        cluster_id: OnlyClusterId,
        account_id: OnlyAccountId,
        created_at: OnlyTimestamp,
    ) -> None:
        self._request = request
        self._order_id = order_id
        self._client_order_id = client_order_id
        self._runtime_id = runtime_id
        self._cluster_id = cluster_id
        self._account_id = account_id
        self._venue_order_id: OnlyVenueOrderId | None = None
        self._status = OnlyOrderStatus.CREATED
        self._filled_quantity = OnlyQuantity(Decimal("0"), request.quantity.precision)
        self._average_fill_price: OnlyPrice | None = None
        self._fill_count = 0
        self._cumulative_price_quantity = Decimal(0)
        self._last_trade_id: OnlyTradeId | None = None
        self._historical_fill_identity_missing = False
        self._created_at = created_at
        self._updated_at = created_at
        self._submitted_at: OnlyTimestamp | None = None
        self._accepted_at: OnlyTimestamp | None = None
        self._cancel_requested_at: OnlyTimestamp | None = None
        self._cancelled_at: OnlyTimestamp | None = None
        self._filled_at: OnlyTimestamp | None = None
        self._rejected_at: OnlyTimestamp | None = None
        self._expired_at: OnlyTimestamp | None = None
        self._failed_at: OnlyTimestamp | None = None
        self._version = 1
        self._last_external_sequence: int | None = None
        self._external_event_ids: set[str] = set()
        self._trade_ids: set[str] = set()
        self._venue_trade_ids: set[str] = set()
        self._rejection: OnlyOrderRejection | None = None
        self._failure: OnlyOrderFailure | None = None
        self._fee_policy_binding: OnlyOrderFeePolicyBinding | None = None
        self._fee_estimate: OnlyOrderFeeEstimate | None = None
        self._funding_plan: OnlyOrderFundingPlan | None = None

    @classmethod
    def restore(
        cls,
        snapshot: OnlyOrderSnapshot,
        *,
        external_event_ids: frozenset[str] = frozenset(),
        trade_ids: frozenset[str] = frozenset(),
        venue_trade_ids: frozenset[str] = frozenset(),
        request_account_id: OnlyAccountId | None = None,
    ) -> OnlyOrder:
        """Rehydrate committed authority without executing an Order transition."""

        request = OnlyOrderRequest(
            snapshot.request_id,
            snapshot.instrument_id,
            snapshot.side,
            snapshot.order_type,
            snapshot.quantity,
            snapshot.time_in_force,
            request_account_id,
            snapshot.offset,
            snapshot.price,
            snapshot.stop_price,
            snapshot.expire_time,
            snapshot.tags,
            snapshot.metadata,
            snapshot.execution_intent,
        )
        entity = cls(
            request,
            snapshot.order_id,
            snapshot.client_order_id,
            snapshot.runtime_id,
            snapshot.cluster_id,
            snapshot.account_id,
            snapshot.created_at,
        )
        entity._venue_order_id = snapshot.venue_order_id
        entity._status = snapshot.status
        entity._filled_quantity = snapshot.filled_quantity
        entity._average_fill_price = snapshot.average_fill_price
        entity._fill_count = snapshot.fill_count
        entity._cumulative_price_quantity = snapshot.cumulative_price_quantity
        entity._last_trade_id = snapshot.last_trade_id
        entity._historical_fill_identity_missing = snapshot.historical_fill_identity_missing
        entity._updated_at = snapshot.updated_at
        entity._submitted_at = snapshot.submitted_at
        entity._accepted_at = snapshot.accepted_at
        entity._cancel_requested_at = snapshot.cancel_requested_at
        entity._cancelled_at = snapshot.cancelled_at
        entity._filled_at = snapshot.filled_at
        entity._rejected_at = snapshot.rejected_at
        entity._expired_at = snapshot.expired_at
        entity._failed_at = snapshot.failed_at
        entity._version = snapshot.version
        entity._last_external_sequence = snapshot.last_external_sequence
        entity._external_event_ids = set(external_event_ids)
        entity._trade_ids = set(trade_ids)
        entity._venue_trade_ids = set(venue_trade_ids)
        entity._rejection = snapshot.rejection
        entity._failure = snapshot.failure
        entity._fee_policy_binding = snapshot.fee_policy_binding
        entity._fee_estimate = snapshot.fee_estimate
        entity._funding_plan = snapshot.funding_plan
        if entity.snapshot() != snapshot:
            raise ValueError("restored Order does not reproduce committed Snapshot")
        return entity

    @property
    def order_id(self) -> OnlyOrderId:
        return self._order_id

    @property
    def request_id(self) -> OnlyOrderRequestId:
        return self._request.request_id

    @property
    def client_order_id(self) -> OnlyClientOrderId:
        return self._client_order_id

    @property
    def venue_order_id(self) -> OnlyVenueOrderId | None:
        return self._venue_order_id

    @property
    def cluster_id(self) -> OnlyClusterId:
        return self._cluster_id

    @property
    def account_id(self) -> OnlyAccountId:
        return self._account_id

    @property
    def instrument_id(self) -> OnlyInstrumentId:
        return self._request.instrument_id

    @property
    def status(self) -> OnlyOrderStatus:
        return self._status

    @property
    def is_open(self) -> bool:
        return self._status in ONLY_OPEN_ORDER_STATUSES

    def snapshot(self) -> OnlyOrderSnapshot:
        remaining = self._request.quantity - self._filled_quantity
        if self._status is OnlyOrderStatus.FILLED:
            remaining = OnlyQuantity(Decimal("0"), self._request.quantity.precision)
        return OnlyOrderSnapshot(
            self._order_id,
            self._request.request_id,
            self._client_order_id,
            self._venue_order_id,
            self._runtime_id,
            self._cluster_id,
            self._account_id,
            self._request.instrument_id,
            self._request.side,
            self._request.offset,
            self._request.order_type,
            self._request.time_in_force,
            self._request.quantity,
            self._request.price,
            self._request.stop_price,
            self._request.expire_time,
            self._status,
            self._filled_quantity,
            remaining,
            self._average_fill_price,
            self._created_at,
            self._updated_at,
            self._submitted_at,
            self._accepted_at,
            self._cancel_requested_at,
            self._cancelled_at,
            self._filled_at,
            self._rejected_at,
            self._expired_at,
            self._failed_at,
            self._version,
            self._last_external_sequence,
            self._rejection,
            self._failure,
            self._request.tags,
            self._request.metadata,
            self._fill_count,
            self._cumulative_price_quantity,
            self._last_trade_id,
            self._historical_fill_identity_missing,
            self._fee_policy_binding,
            self._fee_estimate,
            self._funding_plan,
            self._request.execution_intent,
        )

    def install_fee_contract(
        self,
        binding: OnlyOrderFeePolicyBinding,
        estimate: OnlyOrderFeeEstimate,
        funding_plan: OnlyOrderFundingPlan,
    ) -> None:
        current = (self._fee_policy_binding, self._fee_estimate, self._funding_plan)
        incoming = (binding, estimate, funding_plan)
        if any(item is not None for item in current):
            if current != incoming:
                raise ValueError("ORDER_FEE_BINDING_CONFLICT")
            return
        if binding.order_id != self._order_id or funding_plan.order_id != self._order_id:
            raise ValueError("ORDER_FEE_BINDING_CONFLICT")
        self._fee_policy_binding = binding
        self._fee_estimate = estimate
        self._funding_plan = funding_plan

    def mark_submitted(self, timestamp: OnlyTimestamp) -> OnlyOrderEntityResult:
        if self._fee_policy_binding is None:
            return self._invalid(OnlyOrderMutationType.SUBMITTED, "ORDER_FEE_BINDING_REQUIRED")
        return self._transition(
            OnlyOrderMutationType.SUBMITTED,
            {OnlyOrderStatus.CREATED},
            OnlyOrderStatus.SUBMITTED,
            timestamp,
            "_submitted_at",
        )

    def apply_accepted(
        self,
        timestamp: OnlyTimestamp,
        venue_order_id: OnlyVenueOrderId,
        *,
        external_sequence: int | None = None,
        external_event_id: str | None = None,
    ) -> OnlyOrderEntityResult:
        if self._venue_order_id is not None and self._venue_order_id != venue_order_id:
            return self._invalid(OnlyOrderMutationType.ACCEPTED, "venue_order_id conflicts with existing mapping")
        duplicate = self._check_external(external_sequence, external_event_id)
        if duplicate is not None:
            return self._unchanged(OnlyOrderMutationType.ACCEPTED, duplicate)
        previous = self._status
        if self._status is OnlyOrderStatus.SUBMITTED:
            self._status = OnlyOrderStatus.ACCEPTED
            self._accepted_at = timestamp
        elif self._status in {
            OnlyOrderStatus.ACCEPTED,
            OnlyOrderStatus.PARTIALLY_FILLED,
            OnlyOrderStatus.PENDING_CANCEL,
            OnlyOrderStatus.FILLED,
            OnlyOrderStatus.CANCELLED,
        }:
            if self._venue_order_id == venue_order_id:
                self._remember_external(external_sequence, external_event_id)
                return self._unchanged(OnlyOrderMutationType.ACCEPTED, OnlyOrderApplyResult.DUPLICATE)
        else:
            return self._invalid(OnlyOrderMutationType.ACCEPTED, "Accepted update is illegal for current status")
        self._venue_order_id = venue_order_id
        effective_timestamp = self._updated_at if timestamp.unix_nanos < self._updated_at.unix_nanos else timestamp
        self._commit(effective_timestamp, external_sequence, external_event_id)
        warnings = (
            () if previous is OnlyOrderStatus.SUBMITTED else ("late Accepted enriched identity without rollback",)
        )
        return self._applied(OnlyOrderMutationType.ACCEPTED, previous, warnings)

    def apply_fill(self, fill: OnlyOrderFill) -> OnlyOrderEntityResult:
        if fill.order_id != self._order_id:
            return self._invalid(OnlyOrderMutationType.FILLED, "Fill order_id mismatch")
        if str(fill.trade_id) in self._trade_ids:
            return self._unchanged(OnlyOrderMutationType.FILLED, OnlyOrderApplyResult.DUPLICATE)
        if fill.venue_trade_id is not None and str(fill.venue_trade_id) in self._venue_trade_ids:
            return self._unchanged(OnlyOrderMutationType.FILLED, OnlyOrderApplyResult.DUPLICATE)
        external = self._check_external(fill.external_sequence, fill.external_event_id)
        if external is not None:
            return self._unchanged(OnlyOrderMutationType.FILLED, external)
        if self._status not in {
            OnlyOrderStatus.SUBMITTED,
            OnlyOrderStatus.ACCEPTED,
            OnlyOrderStatus.PARTIALLY_FILLED,
            OnlyOrderStatus.PENDING_CANCEL,
            OnlyOrderStatus.CANCELLED,
        }:
            return self._invalid(OnlyOrderMutationType.FILLED, "Fill is illegal for current status")
        if fill.quantity.precision != self._request.quantity.precision:
            return self._invalid(OnlyOrderMutationType.FILLED, "Fill quantity precision mismatch")
        new_quantity = self._filled_quantity + fill.quantity
        if new_quantity.value > self._request.quantity.value:
            return self._invalid(OnlyOrderMutationType.FILLED, "Fill exceeds Order quantity")
        previous = self._status
        self._cumulative_price_quantity += fill.price.value * fill.quantity.value
        self._average_fill_price = self._weighted_average(fill, new_quantity)
        self._filled_quantity = new_quantity
        self._fill_count += 1
        self._last_trade_id = fill.trade_id
        self._historical_fill_identity_missing = False
        if previous is not OnlyOrderStatus.CANCELLED:
            self._status = (
                OnlyOrderStatus.FILLED if new_quantity == self._request.quantity else OnlyOrderStatus.PARTIALLY_FILLED
            )
        if self._status is OnlyOrderStatus.FILLED:
            self._filled_at = fill.ts_event
        if fill.venue_order_id is not None and self._venue_order_id is None:
            self._venue_order_id = fill.venue_order_id
        self._trade_ids.add(str(fill.trade_id))
        if fill.venue_trade_id is not None:
            self._venue_trade_ids.add(str(fill.venue_trade_id))
        self._commit(fill.ts_init, fill.external_sequence, fill.external_event_id)
        warnings = ("late Fill applied after cancellation",) if previous is OnlyOrderStatus.CANCELLED else ()
        return self._applied(OnlyOrderMutationType.FILLED, previous, warnings)

    def request_cancel(self, timestamp: OnlyTimestamp) -> OnlyOrderEntityResult:
        if self._status is OnlyOrderStatus.PENDING_CANCEL:
            return self._unchanged(OnlyOrderMutationType.CANCEL_REQUESTED, OnlyOrderApplyResult.DUPLICATE)
        return self._transition(
            OnlyOrderMutationType.CANCEL_REQUESTED,
            {
                OnlyOrderStatus.SUBMITTED,
                OnlyOrderStatus.ACCEPTED,
                OnlyOrderStatus.PARTIALLY_FILLED,
            },
            OnlyOrderStatus.PENDING_CANCEL,
            timestamp,
            "_cancel_requested_at",
        )

    def apply_cancelled(
        self,
        timestamp: OnlyTimestamp,
        *,
        external_sequence: int | None = None,
        external_event_id: str | None = None,
    ) -> OnlyOrderEntityResult:
        duplicate = self._check_external(external_sequence, external_event_id)
        if duplicate is not None:
            return self._unchanged(OnlyOrderMutationType.CANCELLED, duplicate)
        if self._status is OnlyOrderStatus.CANCELLED:
            self._remember_external(external_sequence, external_event_id)
            return self._unchanged(OnlyOrderMutationType.CANCELLED, OnlyOrderApplyResult.DUPLICATE)
        return self._transition(
            OnlyOrderMutationType.CANCELLED,
            {
                OnlyOrderStatus.SUBMITTED,
                OnlyOrderStatus.ACCEPTED,
                OnlyOrderStatus.PARTIALLY_FILLED,
                OnlyOrderStatus.PENDING_CANCEL,
            },
            OnlyOrderStatus.CANCELLED,
            timestamp,
            "_cancelled_at",
            external_sequence,
            external_event_id,
        )

    def apply_rejected(
        self,
        timestamp: OnlyTimestamp,
        rejection: OnlyOrderRejection,
        *,
        external_sequence: int | None = None,
        external_event_id: str | None = None,
    ) -> OnlyOrderEntityResult:
        result = self._terminal_transition(
            OnlyOrderMutationType.REJECTED,
            {OnlyOrderStatus.CREATED, OnlyOrderStatus.SUBMITTED},
            OnlyOrderStatus.REJECTED,
            timestamp,
            "_rejected_at",
            external_sequence,
            external_event_id,
        )
        if result.changed:
            self._rejection = rejection
            return self._replace_snapshot(result)
        return result

    def apply_expired(
        self,
        timestamp: OnlyTimestamp,
        *,
        external_sequence: int | None = None,
        external_event_id: str | None = None,
    ) -> OnlyOrderEntityResult:
        return self._terminal_transition(
            OnlyOrderMutationType.EXPIRED,
            {OnlyOrderStatus.ACCEPTED, OnlyOrderStatus.PARTIALLY_FILLED},
            OnlyOrderStatus.EXPIRED,
            timestamp,
            "_expired_at",
            external_sequence,
            external_event_id,
        )

    def apply_failed(self, timestamp: OnlyTimestamp, failure: OnlyOrderFailure) -> OnlyOrderEntityResult:
        result = self._transition(
            OnlyOrderMutationType.FAILED,
            set(ONLY_OPEN_ORDER_STATUSES),
            OnlyOrderStatus.FAILED,
            timestamp,
            "_failed_at",
        )
        if result.changed:
            self._failure = failure
            return self._replace_snapshot(result)
        return result

    def _terminal_transition(
        self,
        mutation: OnlyOrderMutationType,
        allowed: set[OnlyOrderStatus],
        target: OnlyOrderStatus,
        timestamp: OnlyTimestamp,
        timestamp_field: str,
        external_sequence: int | None,
        external_event_id: str | None,
    ) -> OnlyOrderEntityResult:
        external = self._check_external(external_sequence, external_event_id)
        if external is not None:
            return self._unchanged(mutation, external)
        if self._status is target:
            self._remember_external(external_sequence, external_event_id)
            return self._unchanged(mutation, OnlyOrderApplyResult.DUPLICATE)
        return self._transition(
            mutation,
            allowed,
            target,
            timestamp,
            timestamp_field,
            external_sequence,
            external_event_id,
        )

    def _transition(
        self,
        mutation: OnlyOrderMutationType,
        allowed: set[OnlyOrderStatus],
        target: OnlyOrderStatus,
        timestamp: OnlyTimestamp,
        timestamp_field: str,
        external_sequence: int | None = None,
        external_event_id: str | None = None,
    ) -> OnlyOrderEntityResult:
        previous = self._status
        if previous not in allowed:
            return self._invalid(mutation, f"illegal Order transition: {previous.value} -> {target.value}")
        if timestamp.unix_nanos < self._updated_at.unix_nanos:
            return self._unchanged(mutation, OnlyOrderApplyResult.STALE, "update time precedes current state")
        self._status = target
        setattr(self, timestamp_field, timestamp)
        self._commit(timestamp, external_sequence, external_event_id)
        return self._applied(mutation, previous)

    def _commit(
        self,
        timestamp: OnlyTimestamp,
        external_sequence: int | None,
        external_event_id: str | None,
    ) -> None:
        self._updated_at = timestamp
        self._version += 1
        self._remember_external(external_sequence, external_event_id)

    def _remember_external(self, sequence: int | None, event_id: str | None) -> None:
        if sequence is not None:
            self._last_external_sequence = sequence
        if event_id:
            self._external_event_ids.add(event_id)

    def _check_external(self, sequence: int | None, event_id: str | None) -> OnlyOrderApplyResult | None:
        if event_id and event_id in self._external_event_ids:
            return OnlyOrderApplyResult.DUPLICATE
        if sequence is None or self._last_external_sequence is None:
            return None
        if sequence < self._last_external_sequence:
            return OnlyOrderApplyResult.STALE
        if sequence == self._last_external_sequence:
            return OnlyOrderApplyResult.CONFLICT if event_id else OnlyOrderApplyResult.DUPLICATE
        return None

    def _weighted_average(self, fill: OnlyOrderFill, new_quantity: OnlyQuantity) -> OnlyPrice:
        precision = fill.price.precision
        if self._average_fill_price is not None:
            precision = max(precision, self._average_fill_price.precision)
        if self._request.price is not None:
            precision = max(precision, self._request.price.precision)
        value = self._cumulative_price_quantity / new_quantity.value
        quantum = Decimal(1).scaleb(-precision)
        return OnlyPrice(value.quantize(quantum, rounding=ROUND_HALF_EVEN), precision)

    def _applied(
        self,
        mutation: OnlyOrderMutationType,
        previous: OnlyOrderStatus,
        warnings: tuple[str, ...] = (),
    ) -> OnlyOrderEntityResult:
        return OnlyOrderEntityResult(
            mutation,
            previous,
            OnlyOrderApplyResult.APPLIED,
            True,
            self.snapshot(),
            warnings=warnings,
        )

    def _invalid(self, mutation: OnlyOrderMutationType, error: str) -> OnlyOrderEntityResult:
        return OnlyOrderEntityResult(
            mutation,
            self._status,
            OnlyOrderApplyResult.INVALID,
            False,
            self.snapshot(),
            error,
        )

    def _unchanged(
        self,
        mutation: OnlyOrderMutationType,
        result: OnlyOrderApplyResult,
        warning: str | None = None,
    ) -> OnlyOrderEntityResult:
        return OnlyOrderEntityResult(
            mutation,
            self._status,
            result,
            False,
            self.snapshot(),
            warnings=() if warning is None else (warning,),
        )

    def _replace_snapshot(self, result: OnlyOrderEntityResult) -> OnlyOrderEntityResult:
        return OnlyOrderEntityResult(
            result.mutation_type,
            result.previous_status,
            result.apply_result,
            result.changed,
            self.snapshot(),
            result.error,
            result.warnings,
        )
