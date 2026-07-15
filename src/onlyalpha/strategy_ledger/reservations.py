"""Strategy virtual-cash Reservation state manager."""

from dataclasses import replace
from decimal import Decimal

from onlyalpha.domain.identifiers import OnlyOrderId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.strategy_ledger.enums import (
    OnlyStrategyCashReservationStage,
    OnlyStrategyCashReservationState,
)
from onlyalpha.strategy_ledger.identifiers import OnlyStrategyCashReservationId
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.models import OnlyStrategyCashReservation, only_zero_money


class OnlyStrategyCashReservationManager:
    """Idempotent reservations for one Strategy Ledger key."""

    def __init__(self, key: OnlyStrategyLedgerKey) -> None:
        self.key = key
        self._by_order: dict[OnlyOrderId, OnlyStrategyCashReservation] = {}

    def create(
        self,
        order_id: OnlyOrderId,
        estimated_notional: OnlyMoney,
        estimated_fee: OnlyMoney,
        timestamp: OnlyTimestamp,
    ) -> tuple[OnlyStrategyCashReservation, bool]:
        self._require_currency(estimated_notional)
        self._require_currency(estimated_fee)
        reserved = estimated_notional + estimated_fee
        previous = self._by_order.get(order_id)
        if previous is not None:
            if previous.estimated_notional != estimated_notional or previous.estimated_fee != estimated_fee:
                raise ValueError("Order ID reused for a different cash Reservation")
            return previous, False
        item = OnlyStrategyCashReservation(
            OnlyStrategyCashReservationId(f"SCRES-{self.key.runtime_id}-{self.key.cluster_id}-{order_id}"),
            self.key,
            order_id,
            estimated_notional,
            estimated_fee,
            reserved,
            only_zero_money(self.key.base_currency),
            reserved,
            OnlyStrategyCashReservationState.ACTIVE,
            OnlyStrategyCashReservationStage.LOCAL_ONLY,
            timestamp,
            timestamp,
        )
        self._by_order[order_id] = item
        return item, True

    def advance_stage(
        self,
        order_id: OnlyOrderId,
        stage: OnlyStrategyCashReservationStage,
        timestamp: OnlyTimestamp,
    ) -> tuple[OnlyStrategyCashReservation, bool]:
        item = self.require(order_id)
        if item.stage is stage:
            return item, False
        allowed = {
            OnlyStrategyCashReservationStage.LOCAL_ONLY: {OnlyStrategyCashReservationStage.SENT_TO_BROKER},
            OnlyStrategyCashReservationStage.SENT_TO_BROKER: {
                OnlyStrategyCashReservationStage.BROKER_ACKNOWLEDGED,
                OnlyStrategyCashReservationStage.RELEASE_PENDING,
            },
            OnlyStrategyCashReservationStage.BROKER_ACKNOWLEDGED: {
                OnlyStrategyCashReservationStage.RELEASE_PENDING,
            },
            OnlyStrategyCashReservationStage.RELEASE_PENDING: {OnlyStrategyCashReservationStage.RELEASED},
            OnlyStrategyCashReservationStage.RELEASED: set(),
        }
        if stage not in allowed[item.stage]:
            raise ValueError(f"invalid cash Reservation stage transition: {item.stage} -> {stage}")
        updated = replace(item, stage=stage, updated_at=timestamp, version=item.version + 1)
        self._by_order[order_id] = updated
        return updated, True

    def consume(
        self,
        order_id: OnlyOrderId,
        actual_amount: OnlyMoney,
        timestamp: OnlyTimestamp,
        *,
        allow_extra: bool,
    ) -> tuple[OnlyStrategyCashReservation, bool]:
        self._require_currency(actual_amount)
        item = self.require(order_id)
        if item.state in {OnlyStrategyCashReservationState.CONSUMED, OnlyStrategyCashReservationState.RELEASED}:
            return item, False
        excess = max(actual_amount.amount - item.remaining_amount.amount, Decimal(0))
        if excess and not allow_extra:
            raise ValueError("actual cash consumption exceeds Reservation")
        reserved = OnlyMoney(item.reserved_amount.amount + excess, self.key.base_currency)
        consumed = OnlyMoney(item.consumed_amount.amount + actual_amount.amount, self.key.base_currency)
        remaining = OnlyMoney(reserved.amount - consumed.amount, self.key.base_currency)
        state = (
            OnlyStrategyCashReservationState.CONSUMED
            if remaining.amount == 0
            else OnlyStrategyCashReservationState.PARTIALLY_CONSUMED
        )
        updated = replace(
            item,
            reserved_amount=reserved,
            consumed_amount=consumed,
            remaining_amount=remaining,
            state=state,
            updated_at=timestamp,
            version=item.version + 1,
        )
        self._by_order[order_id] = updated
        return updated, True

    def release(
        self,
        order_id: OnlyOrderId,
        timestamp: OnlyTimestamp,
    ) -> tuple[OnlyStrategyCashReservation, bool]:
        item = self.require(order_id)
        if item.state is OnlyStrategyCashReservationState.RELEASED:
            return item, False
        updated = replace(
            item,
            reserved_amount=item.consumed_amount,
            remaining_amount=only_zero_money(self.key.base_currency),
            state=OnlyStrategyCashReservationState.RELEASED,
            stage=OnlyStrategyCashReservationStage.RELEASED,
            updated_at=timestamp,
            version=item.version + 1,
        )
        self._by_order[order_id] = updated
        return updated, True

    def get(self, order_id: OnlyOrderId) -> OnlyStrategyCashReservation | None:
        return self._by_order.get(order_id)

    def require(self, order_id: OnlyOrderId) -> OnlyStrategyCashReservation:
        item = self.get(order_id)
        if item is None:
            raise KeyError(f"Strategy Cash Reservation not found: {order_id}")
        return item

    def active_reserved(self) -> OnlyMoney:
        return OnlyMoney(
            sum(
                (
                    item.remaining_amount.amount
                    for item in self._by_order.values()
                    if item.state
                    in {
                        OnlyStrategyCashReservationState.ACTIVE,
                        OnlyStrategyCashReservationState.PARTIALLY_CONSUMED,
                    }
                ),
                Decimal(0),
            ),
            self.key.base_currency,
        )

    def snapshots(self) -> tuple[OnlyStrategyCashReservation, ...]:
        return tuple(sorted(self._by_order.values(), key=lambda item: str(item.reservation_id)))

    def _require_currency(self, amount: OnlyMoney) -> None:
        if amount.currency != self.key.base_currency:
            raise ValueError("cash Reservation currency differs from Ledger base currency")
