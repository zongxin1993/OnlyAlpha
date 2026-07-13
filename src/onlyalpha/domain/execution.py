"""Immutable order, request and trade domain models."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import (
    OnlyLiquiditySide,
    OnlyOffset,
    OnlyOrderSide,
    OnlyOrderStatus,
    OnlyOrderType,
    OnlyTimeInForce,
)
from onlyalpha.domain.errors import OnlyStateTransitionError, OnlyValidationError
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyTradeId,
    OnlyVenueOrderId,
)
from onlyalpha.domain.time import only_require_utc
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity

ONLY_TERMINAL_ORDER_STATUSES = frozenset(
    {
        OnlyOrderStatus.DENIED,
        OnlyOrderStatus.REJECTED,
        OnlyOrderStatus.CANCELED,
        OnlyOrderStatus.EXPIRED,
        OnlyOrderStatus.FILLED,
    }
)

ONLY_ORDER_TRANSITIONS: dict[OnlyOrderStatus, frozenset[OnlyOrderStatus]] = {
    OnlyOrderStatus.INITIALIZED: frozenset({OnlyOrderStatus.DENIED, OnlyOrderStatus.SUBMITTED}),
    OnlyOrderStatus.SUBMITTED: frozenset(
        {OnlyOrderStatus.ACCEPTED, OnlyOrderStatus.REJECTED, OnlyOrderStatus.CANCELED}
    ),
    OnlyOrderStatus.ACCEPTED: frozenset(
        {
            OnlyOrderStatus.PARTIALLY_FILLED,
            OnlyOrderStatus.PENDING_CANCEL,
            OnlyOrderStatus.CANCELED,
            OnlyOrderStatus.EXPIRED,
            OnlyOrderStatus.FILLED,
        }
    ),
    OnlyOrderStatus.PARTIALLY_FILLED: frozenset(
        {
            OnlyOrderStatus.PARTIALLY_FILLED,
            OnlyOrderStatus.PENDING_CANCEL,
            OnlyOrderStatus.CANCELED,
            OnlyOrderStatus.FILLED,
        }
    ),
    OnlyOrderStatus.PENDING_CANCEL: frozenset(
        {OnlyOrderStatus.CANCELED, OnlyOrderStatus.PARTIALLY_FILLED, OnlyOrderStatus.FILLED}
    ),
}


def _require_aware(timestamp: datetime, name: str) -> None:
    only_require_utc(timestamp, name)


@dataclass(frozen=True, slots=True)
class OnlyOrderRequest(OnlyDomainModel):
    order_id: OnlyOrderId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId
    side: OnlyOrderSide
    offset: OnlyOffset
    order_type: OnlyOrderType
    quantity: OnlyQuantity
    time_in_force: OnlyTimeInForce
    submitted_at: datetime
    limit_price: OnlyPrice | None = None
    stop_price: OnlyPrice | None = None
    expire_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_aware(self.submitted_at, "submitted_at")
        if self.quantity.value <= 0:
            raise OnlyValidationError("order quantity must be positive")
        if self.order_type in {OnlyOrderType.LIMIT, OnlyOrderType.STOP_LIMIT, OnlyOrderType.LIMIT_IF_TOUCHED}:
            if self.limit_price is None:
                raise OnlyValidationError("limit order requires limit_price")
        if (
            self.order_type
            in {
                OnlyOrderType.STOP_MARKET,
                OnlyOrderType.STOP_LIMIT,
                OnlyOrderType.MARKET_IF_TOUCHED,
                OnlyOrderType.LIMIT_IF_TOUCHED,
            }
            and self.stop_price is None
        ):
            raise OnlyValidationError("triggered order requires stop_price")
        if self.time_in_force is OnlyTimeInForce.GTD:
            if self.expire_at is None:
                raise OnlyValidationError("GTD order requires expire_at")
            _require_aware(self.expire_at, "expire_at")
            if self.expire_at <= self.submitted_at:
                raise OnlyValidationError("expire_at must follow submitted_at")


@dataclass(frozen=True, slots=True)
class OnlyCancelRequest(OnlyDomainModel):
    order_id: OnlyOrderId
    account_id: OnlyAccountId
    requested_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.requested_at, "requested_at")


@dataclass(frozen=True, slots=True)
class OnlyOrder(OnlyDomainModel):
    """Order state snapshot; transitions return a new snapshot."""

    request: OnlyOrderRequest
    status: OnlyOrderStatus
    filled_quantity: OnlyQuantity
    updated_at: datetime
    average_fill_price: OnlyPrice | None = None
    venue_order_id: OnlyVenueOrderId | None = None
    rejection_reason: str | None = None
    report_ids: tuple[str, ...] = ()

    @property
    def order_id(self) -> OnlyOrderId:
        return self.request.order_id

    @property
    def client_order_id(self) -> OnlyOrderId:
        return self.request.order_id

    @property
    def created_at(self) -> datetime:
        return self.request.submitted_at

    def __post_init__(self) -> None:
        _require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.request.submitted_at:
            raise OnlyValidationError("order updated_at cannot precede submitted_at")
        if self.filled_quantity.precision != self.request.quantity.precision:
            raise OnlyValidationError("filled quantity precision mismatch")
        if self.filled_quantity.value > self.request.quantity.value:
            raise OnlyValidationError("filled quantity exceeds requested quantity")
        if self.status is OnlyOrderStatus.FILLED and self.filled_quantity != self.request.quantity:
            raise OnlyValidationError("FILLED order must have full filled quantity")
        if self.filled_quantity.value > 0 and self.average_fill_price is None:
            raise OnlyValidationError("filled order quantity requires average_fill_price")
        if self.status is OnlyOrderStatus.PARTIALLY_FILLED:
            if not 0 < self.filled_quantity.value < self.request.quantity.value:
                raise OnlyValidationError("PARTIALLY_FILLED requires a partial positive quantity")

    @property
    def is_terminal(self) -> bool:
        return self.status in ONLY_TERMINAL_ORDER_STATUSES

    @property
    def remaining_quantity(self) -> OnlyQuantity:
        return self.request.quantity - self.filled_quantity

    def transition(
        self,
        status: OnlyOrderStatus,
        updated_at: datetime,
        *,
        filled_quantity: OnlyQuantity | None = None,
        average_fill_price: OnlyPrice | None = None,
        venue_order_id: OnlyVenueOrderId | None = None,
        rejection_reason: str | None = None,
    ) -> OnlyOrder:
        allowed = ONLY_ORDER_TRANSITIONS.get(self.status, frozenset())
        if status not in allowed:
            raise OnlyStateTransitionError(f"illegal order transition: {self.status} -> {status}")
        if updated_at < self.updated_at:
            raise OnlyStateTransitionError("order update time cannot move backwards")
        return replace(
            self,
            status=status,
            updated_at=updated_at,
            filled_quantity=filled_quantity or self.filled_quantity,
            average_fill_price=average_fill_price or self.average_fill_price,
            venue_order_id=venue_order_id or self.venue_order_id,
            rejection_reason=rejection_reason,
        )

    @classmethod
    def initialized(cls, request: OnlyOrderRequest) -> OnlyOrder:
        return cls(
            request=request,
            status=OnlyOrderStatus.INITIALIZED,
            filled_quantity=OnlyQuantity(Decimal("0"), request.quantity.precision),
            updated_at=request.submitted_at,
        )

    def transition_submitted(self, updated_at: datetime) -> OnlyOrder:
        return self.transition(OnlyOrderStatus.SUBMITTED, updated_at)

    def transition_accepted(self, updated_at: datetime, *, venue_order_id: str) -> OnlyOrder:
        return self.transition(
            OnlyOrderStatus.ACCEPTED,
            updated_at,
            venue_order_id=OnlyVenueOrderId(venue_order_id),
        )

    def apply_fill(
        self,
        *,
        filled_quantity: OnlyQuantity,
        average_fill_price: OnlyPrice,
        updated_at: datetime,
        report_id: str,
    ) -> OnlyOrder:
        """Apply an incremental fill once; duplicate report IDs are idempotent."""
        if report_id in self.report_ids:
            return self
        total = self.filled_quantity + filled_quantity
        status = OnlyOrderStatus.FILLED if total == self.request.quantity else OnlyOrderStatus.PARTIALLY_FILLED
        updated = self.transition(
            status,
            updated_at,
            filled_quantity=total,
            average_fill_price=average_fill_price,
        )
        return replace(updated, report_ids=updated.report_ids + (report_id,))


@dataclass(frozen=True, slots=True)
class OnlyTrade(OnlyDomainModel):
    """Immutable execution fact associated with one order."""

    trade_id: OnlyTradeId
    order_id: OnlyOrderId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    side: OnlyOrderSide
    offset: OnlyOffset
    price: OnlyPrice
    quantity: OnlyQuantity
    commission: OnlyMoney
    liquidity_side: OnlyLiquiditySide
    executed_at: datetime
    initialized_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_aware(self.executed_at, "executed_at")
        if self.initialized_at is not None:
            _require_aware(self.initialized_at, "initialized_at")
            if self.initialized_at < self.executed_at:
                raise OnlyValidationError("trade initialized_at cannot precede executed_at")
        if self.quantity.value <= 0:
            raise OnlyValidationError("trade quantity must be positive")
        if self.commission.amount < 0:
            raise OnlyValidationError("trade commission cannot be negative")

    @property
    def fee(self) -> OnlyMoney:
        return self.commission

    @property
    def ts_event(self) -> datetime:
        return self.executed_at

    @property
    def ts_init(self) -> datetime:
        return self.initialized_at or self.executed_at
