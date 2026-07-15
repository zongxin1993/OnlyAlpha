"""Runtime-private controlled mutable account Position entity."""

from decimal import ROUND_HALF_EVEN, Decimal

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyPositionId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.position.enums import OnlyPositionStatus
from onlyalpha.position.exceptions import OnlyPositionInvariantError, OnlyPositionOverSellError
from onlyalpha.position.keys import OnlyPositionKey
from onlyalpha.position.models import (
    OnlyPositionRestriction,
    OnlyPositionSnapshot,
    OnlyPositionTrade,
    only_zero_quantity,
)
from onlyalpha.position.pnl import OnlyPnLModel


class OnlyPosition:
    """Controlled mutable entity; callers receive only immutable snapshots."""

    def __init__(
        self,
        position_id: OnlyPositionId,
        key: OnlyPositionKey,
        trade: OnlyPositionTrade,
    ) -> None:
        precision = trade.quantity.precision
        zero = only_zero_quantity(precision)
        self.position_id = position_id
        self.key = key
        self.status = OnlyPositionStatus.OPEN
        self.total_quantity = zero
        self.settled_quantity = zero
        self.unsettled_quantity = zero
        self.order_frozen_quantity = zero
        self.risk_reserved_quantity = zero
        self.average_open_price: OnlyPrice | None = None
        self.realized_pnl = OnlyMoney(Decimal(0), trade.fee.currency)
        self.fees = OnlyMoney(Decimal(0), trade.fee.currency)
        self.opened_at = trade.ts_event
        self.updated_at = trade.ts_event
        self.closed_at: OnlyTimestamp | None = None
        self.version = 0
        self.last_trade_sequence: int | None = None
        self.last_trade_order: tuple[int, int, str] | None = None
        self.quality_flags: tuple[str, ...] = ()
        self.broker_available_quantity: OnlyQuantity | None = None
        self._restrictions: dict[object, OnlyPositionRestriction] = {}

    @property
    def restricted_quantity(self) -> OnlyQuantity:
        value = sum((item.quantity.value for item in self._restrictions.values()), Decimal(0))
        return OnlyQuantity(min(value, self.settled_quantity.value), self.total_quantity.precision)

    def snapshot(self) -> OnlyPositionSnapshot:
        return OnlyPositionSnapshot(
            self.position_id,
            self.key,
            self.status,
            self.total_quantity,
            self.settled_quantity,
            self.unsettled_quantity,
            self.order_frozen_quantity,
            self.risk_reserved_quantity,
            self.restricted_quantity,
            self.average_open_price,
            self.realized_pnl,
            self.fees,
            self.opened_at,
            self.updated_at,
            self.closed_at,
            self.version,
            self.last_trade_sequence,
            self.last_trade_order,
            self.quality_flags,
            self.broker_available_quantity,
        )

    def apply_trade(self, trade: OnlyPositionTrade, pnl_model: OnlyPnLModel) -> OnlyMoney:
        before_quantity = self.total_quantity
        if trade.side is OnlyOrderSide.BUY:
            self._increase(trade)
            pnl_delta = OnlyMoney(Decimal(0), trade.fee.currency)
        else:
            if trade.quantity.value > self.snapshot().available_quantity.value:
                # A fill may consume quantity already held by its own order freeze.
                usable_with_order_freeze = self.snapshot().available_quantity.value + self.order_frozen_quantity.value
                if trade.quantity.value > usable_with_order_freeze:
                    raise OnlyPositionOverSellError("sell exceeds effective available Position quantity")
            if self.average_open_price is None:
                raise OnlyPositionInvariantError("open Position is missing average cost")
            pnl_delta = pnl_model.realized(
                self.key.position_side,
                self.average_open_price,
                trade.price,
                trade.quantity,
                trade.multiplier,
                trade.fee.currency,
            )
            self.settled_quantity = OnlyQuantity(
                self.settled_quantity.value - trade.quantity.value,
                self.settled_quantity.precision,
            )
            self.total_quantity = OnlyQuantity(
                self.total_quantity.value - trade.quantity.value,
                self.total_quantity.precision,
            )
            consumed_freeze = min(self.order_frozen_quantity.value, trade.quantity.value)
            self.order_frozen_quantity = OnlyQuantity(
                self.order_frozen_quantity.value - consumed_freeze,
                self.order_frozen_quantity.precision,
            )
            self.realized_pnl = self.realized_pnl + pnl_delta
        if self.fees.currency != trade.fee.currency:
            raise OnlyPositionInvariantError("Position fee currency changed")
        self.fees = self.fees + trade.fee
        self.updated_at = trade.ts_event
        self.version += 1
        self.last_trade_sequence = trade.external_sequence
        self.last_trade_order = trade.stable_order
        if self.total_quantity.value == 0:
            self.status = OnlyPositionStatus.CLOSED
            self.average_open_price = None
            self.closed_at = trade.ts_event
        elif before_quantity.value == 0:
            self.status = OnlyPositionStatus.OPEN
        self._check()
        return pnl_delta

    def _increase(self, trade: OnlyPositionTrade) -> None:
        old_value = self.total_quantity.value
        new_value = old_value + trade.quantity.value
        if self.average_open_price is None:
            average = trade.price.value
        else:
            average = (self.average_open_price.value * old_value + trade.price.value * trade.quantity.value) / new_value
        precision = max(trade.price.precision, self.average_open_price.precision if self.average_open_price else 0)
        quantum = Decimal(1).scaleb(-precision)
        self.average_open_price = OnlyPrice(average.quantize(quantum, rounding=ROUND_HALF_EVEN), precision)
        self.total_quantity = OnlyQuantity(new_value, max(self.total_quantity.precision, trade.quantity.precision))
        if trade.settlement_bucket.value == "SETTLED":
            self.settled_quantity = OnlyQuantity(
                self.settled_quantity.value + trade.quantity.value,
                self.total_quantity.precision,
            )
        else:
            self.unsettled_quantity = OnlyQuantity(
                self.unsettled_quantity.value + trade.quantity.value,
                self.total_quantity.precision,
            )

    def freeze(self, quantity: OnlyQuantity, *, risk: bool) -> None:
        if quantity.value <= 0 or quantity.value > self.snapshot().available_quantity.value:
            raise OnlyPositionOverSellError("freeze exceeds available Position quantity")
        if risk:
            self.risk_reserved_quantity = self.risk_reserved_quantity + quantity
        else:
            self.order_frozen_quantity = self.order_frozen_quantity + quantity
        self.version += 1

    def release(self, quantity: OnlyQuantity, *, risk: bool) -> None:
        current = self.risk_reserved_quantity if risk else self.order_frozen_quantity
        released = min(current.value, quantity.value)
        replacement = OnlyQuantity(current.value - released, current.precision)
        if risk:
            self.risk_reserved_quantity = replacement
        else:
            self.order_frozen_quantity = replacement
        if released > 0:
            self.version += 1

    def apply_restriction(self, restriction: OnlyPositionRestriction) -> None:
        existing = self._restrictions.get(restriction.restriction_id)
        if existing == restriction:
            return
        if existing is not None:
            raise OnlyPositionInvariantError("Restriction ID reused with different content")
        self._restrictions[restriction.restriction_id] = restriction
        self.version += 1

    def remove_restriction(self, restriction_id: object) -> bool:
        if self._restrictions.pop(restriction_id, None) is None:
            return False
        self.version += 1
        return True

    def settle(self) -> OnlyQuantity:
        moved = self.unsettled_quantity
        if moved.value:
            self.settled_quantity = self.settled_quantity + moved
            self.unsettled_quantity = only_zero_quantity(moved.precision)
            self.version += 1
        return moved

    def set_reconciling(self, broker_available: OnlyQuantity | None = None) -> None:
        self.status = OnlyPositionStatus.RECONCILING
        self.broker_available_quantity = broker_available
        self.quality_flags = tuple(sorted(set(self.quality_flags + ("RECONCILING",))))
        self.version += 1

    def clear_reconciling(self) -> None:
        if self.status is OnlyPositionStatus.RECONCILING:
            self.status = OnlyPositionStatus.OPEN
            self.quality_flags = tuple(item for item in self.quality_flags if item != "RECONCILING")
            self.version += 1

    def set_broker_available(self, quantity: OnlyQuantity) -> None:
        if self.broker_available_quantity == quantity:
            return
        self.broker_available_quantity = quantity
        self.version += 1

    def _check(self) -> None:
        if self.settled_quantity.value + self.unsettled_quantity.value != self.total_quantity.value:
            raise OnlyPositionInvariantError("Position settlement buckets diverged")
        if self.total_quantity.value > 0 and self.average_open_price is None:
            raise OnlyPositionInvariantError("open Position requires average cost")
