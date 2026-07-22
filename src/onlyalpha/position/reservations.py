"""Position sell Reservation lifecycle and broker-freeze de-duplication."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.position.allocation_manager import OnlyPositionAllocationManager
from onlyalpha.position.enums import (
    OnlyPositionMode,
    OnlyPositionReservationStage,
    OnlyPositionReservationState,
    OnlyPositionSide,
    OnlySettlementBucket,
)
from onlyalpha.position.identifiers import OnlyPositionReservationId
from onlyalpha.position.keys import OnlyPositionAllocationKey, OnlyPositionKey
from onlyalpha.position.manager import OnlyPositionManager


@dataclass(frozen=True, slots=True)
class OnlyPositionReservation(OnlyDomainModel):
    reservation_id: OnlyPositionReservationId
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId
    position_side: OnlyPositionSide
    position_mode: OnlyPositionMode
    order_id: OnlyOrderId
    quantity: OnlyQuantity
    remaining_quantity: OnlyQuantity
    settlement_bucket: OnlySettlementBucket
    stage: OnlyPositionReservationStage
    state: OnlyPositionReservationState
    created_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    version: int = 1


@dataclass(frozen=True, slots=True)
class OnlyPositionReservationResult(OnlyDomainModel):
    reservation: OnlyPositionReservation
    changed: bool


class OnlyPositionReservationManager:
    """Coordinates account and Cluster reservations without double broker freeze."""

    def __init__(
        self,
        runtime_id: OnlyRuntimeId,
        positions: OnlyPositionManager,
        allocations: OnlyPositionAllocationManager,
    ) -> None:
        self.runtime_id = runtime_id
        self._positions = positions
        self._allocations = allocations
        self._by_order: dict[OnlyOrderId, OnlyPositionReservation] = {}

    def create(
        self,
        account_id: OnlyAccountId,
        cluster_id: OnlyClusterId,
        instrument_id: OnlyInstrumentId,
        order_id: OnlyOrderId,
        quantity: OnlyQuantity,
        timestamp: OnlyTimestamp,
        *,
        position_side: OnlyPositionSide = OnlyPositionSide.LONG,
        position_mode: OnlyPositionMode = OnlyPositionMode.NETTING,
    ) -> OnlyPositionReservationResult:
        previous = self._by_order.get(order_id)
        if previous is not None:
            expected = (account_id, cluster_id, instrument_id, quantity, position_side, position_mode)
            actual = (
                previous.account_id,
                previous.cluster_id,
                previous.instrument_id,
                previous.quantity,
                previous.position_side,
                previous.position_mode,
            )
            if expected != actual:
                raise ValueError("Order ID reused for a different Position Reservation")
            return OnlyPositionReservationResult(previous, False)
        account_key = OnlyPositionKey(self.runtime_id, account_id, instrument_id, position_side, position_mode)
        allocation_key = OnlyPositionAllocationKey(
            self.runtime_id, account_id, cluster_id, instrument_id, position_side
        )
        account_available = self._positions.require_snapshot(account_key).available_quantity
        cluster_available = self._allocations.calculate_cluster_available(allocation_key, account_available)
        if quantity.value > cluster_available.value:
            raise ValueError("Position Reservation exceeds effective Cluster/account availability")
        self._positions.freeze(account_key, quantity, risk=True)
        try:
            self._allocations.reserve(allocation_key, quantity)
        except Exception:
            self._positions.release(account_key, quantity, risk=True)
            raise
        reservation = OnlyPositionReservation(
            OnlyPositionReservationId(f"PRES-{self.runtime_id}-{order_id}"),
            self.runtime_id,
            account_id,
            cluster_id,
            instrument_id,
            position_side,
            position_mode,
            order_id,
            quantity,
            quantity,
            OnlySettlementBucket.SETTLED,
            OnlyPositionReservationStage.LOCAL_ONLY,
            OnlyPositionReservationState.ACTIVE,
            timestamp,
            timestamp,
        )
        self._by_order[order_id] = reservation
        return OnlyPositionReservationResult(reservation, True)

    def advance_stage(
        self,
        order_id: OnlyOrderId,
        stage: OnlyPositionReservationStage,
        timestamp: OnlyTimestamp,
    ) -> OnlyPositionReservationResult:
        reservation = self._require(order_id)
        if reservation.stage is stage:
            return OnlyPositionReservationResult(reservation, False)
        allowed = {
            OnlyPositionReservationStage.LOCAL_ONLY: {OnlyPositionReservationStage.SENT_TO_BROKER},
            OnlyPositionReservationStage.SENT_TO_BROKER: {
                OnlyPositionReservationStage.BROKER_ACKNOWLEDGED,
                OnlyPositionReservationStage.RELEASE_PENDING,
            },
            OnlyPositionReservationStage.BROKER_ACKNOWLEDGED: {
                OnlyPositionReservationStage.RELEASE_PENDING,
            },
            OnlyPositionReservationStage.RELEASE_PENDING: {OnlyPositionReservationStage.RELEASED},
            OnlyPositionReservationStage.RELEASED: set(),
        }
        if stage not in allowed[reservation.stage]:
            raise ValueError(f"invalid Position Reservation stage transition: {reservation.stage} -> {stage}")
        if stage is OnlyPositionReservationStage.BROKER_ACKNOWLEDGED:
            # Broker available/frozen now reflects the hold; keep Cluster hold, remove local account double deduction.
            self._positions.release(self._account_key(reservation), reservation.remaining_quantity, risk=True)
        updated = replace(reservation, stage=stage, updated_at=timestamp, version=reservation.version + 1)
        self._by_order[order_id] = updated
        return OnlyPositionReservationResult(updated, True)

    def consume(
        self,
        order_id: OnlyOrderId,
        quantity: OnlyQuantity,
        timestamp: OnlyTimestamp,
        *,
        allocation_hold_already_released: bool = False,
    ) -> OnlyPositionReservationResult:
        reservation = self._require(order_id)
        if reservation.state in {OnlyPositionReservationState.CONSUMED, OnlyPositionReservationState.RELEASED}:
            return OnlyPositionReservationResult(reservation, False)
        consumed = min(quantity.value, reservation.remaining_quantity.value)
        if consumed == 0:
            return OnlyPositionReservationResult(reservation, False)
        consumed_quantity = OnlyQuantity(consumed, reservation.quantity.precision)
        if reservation.stage in {
            OnlyPositionReservationStage.LOCAL_ONLY,
            OnlyPositionReservationStage.SENT_TO_BROKER,
        }:
            self._positions.release(self._account_key(reservation), consumed_quantity, risk=True)
        if not allocation_hold_already_released:
            self._allocations.release(self._allocation_key(reservation), consumed_quantity)
        remaining = OnlyQuantity(
            reservation.remaining_quantity.value - consumed,
            reservation.remaining_quantity.precision,
        )
        state = (
            OnlyPositionReservationState.CONSUMED
            if remaining.value == 0
            else OnlyPositionReservationState.PARTIALLY_CONSUMED
        )
        updated = replace(
            reservation,
            remaining_quantity=remaining,
            state=state,
            updated_at=timestamp,
            version=reservation.version + 1,
        )
        self._by_order[order_id] = updated
        return OnlyPositionReservationResult(updated, True)

    def release(
        self,
        order_id: OnlyOrderId,
        timestamp: OnlyTimestamp,
        *,
        broker_confirmed: bool = True,
    ) -> OnlyPositionReservationResult:
        reservation = self._require(order_id)
        if reservation.state is OnlyPositionReservationState.RELEASED:
            return OnlyPositionReservationResult(reservation, False)
        broker_holds = reservation.stage in {
            OnlyPositionReservationStage.BROKER_ACKNOWLEDGED,
            OnlyPositionReservationStage.RELEASE_PENDING,
        }
        if broker_holds and not broker_confirmed:
            if reservation.stage is OnlyPositionReservationStage.RELEASE_PENDING:
                return OnlyPositionReservationResult(reservation, False)
            updated = replace(
                reservation,
                stage=OnlyPositionReservationStage.RELEASE_PENDING,
                updated_at=timestamp,
                version=reservation.version + 1,
            )
            self._by_order[order_id] = updated
            return OnlyPositionReservationResult(updated, True)
        if reservation.stage in {
            OnlyPositionReservationStage.LOCAL_ONLY,
            OnlyPositionReservationStage.SENT_TO_BROKER,
        }:
            self._positions.release(self._account_key(reservation), reservation.remaining_quantity, risk=True)
        self._allocations.release(self._allocation_key(reservation), reservation.remaining_quantity)
        updated = replace(
            reservation,
            remaining_quantity=OnlyQuantity(Decimal(0), reservation.quantity.precision),
            stage=OnlyPositionReservationStage.RELEASED,
            state=OnlyPositionReservationState.RELEASED,
            updated_at=timestamp,
            version=reservation.version + 1,
        )
        self._by_order[order_id] = updated
        return OnlyPositionReservationResult(updated, True)

    def get(self, order_id: OnlyOrderId) -> OnlyPositionReservation | None:
        return self._by_order.get(order_id)

    def active_quantity(
        self,
        instrument_id: OnlyInstrumentId,
        *,
        account_id: OnlyAccountId | None = None,
        cluster_id: OnlyClusterId | None = None,
        local_only: bool = False,
    ) -> OnlyQuantity:
        matches = [
            item
            for item in self._by_order.values()
            if item.instrument_id == instrument_id
            and (account_id is None or item.account_id == account_id)
            and (cluster_id is None or item.cluster_id == cluster_id)
            and item.state
            in {
                OnlyPositionReservationState.ACTIVE,
                OnlyPositionReservationState.PARTIALLY_CONSUMED,
            }
            and (
                not local_only
                or item.stage
                in {
                    OnlyPositionReservationStage.LOCAL_ONLY,
                    OnlyPositionReservationStage.SENT_TO_BROKER,
                }
            )
        ]
        precision = max((item.quantity.precision for item in matches), default=0)
        return OnlyQuantity(
            sum((item.remaining_quantity.value for item in matches), start=Decimal(0)),
            precision,
        )

    def _require(self, order_id: OnlyOrderId) -> OnlyPositionReservation:
        reservation = self._by_order.get(order_id)
        if reservation is None:
            raise KeyError(f"Position Reservation not found: {order_id}")
        return reservation

    def _account_key(self, reservation: OnlyPositionReservation) -> OnlyPositionKey:
        return OnlyPositionKey(
            self.runtime_id,
            reservation.account_id,
            reservation.instrument_id,
            reservation.position_side,
            reservation.position_mode,
        )

    def _allocation_key(self, reservation: OnlyPositionReservation) -> OnlyPositionAllocationKey:
        return OnlyPositionAllocationKey(
            self.runtime_id,
            reservation.account_id,
            reservation.cluster_id,
            reservation.instrument_id,
            reservation.position_side,
        )


class OnlyOrderPositionReservationAdapter:
    """Narrow adapter used by Order without exposing Position Managers."""

    def __init__(
        self,
        manager: OnlyPositionReservationManager,
        position_mode: Callable[[OnlyOrderSnapshot, OnlyTimestamp], OnlyPositionMode] | None = None,
    ) -> None:
        self._manager = manager
        self._position_mode = position_mode or (lambda _order, _timestamp: OnlyPositionMode.NETTING)

    def reserve(self, order: OnlyOrderSnapshot, timestamp: OnlyTimestamp) -> None:
        if order.offset is OnlyOffset.OPEN or (order.offset is OnlyOffset.NONE and order.side is OnlyOrderSide.BUY):
            return
        position_side = OnlyPositionSide.SHORT if order.side is OnlyOrderSide.BUY else OnlyPositionSide.LONG
        self._manager.create(
            order.account_id,
            order.cluster_id,
            order.instrument_id,
            order.order_id,
            order.quantity,
            timestamp,
            position_side=position_side,
            position_mode=self._position_mode(order, timestamp),
        )

    def sent(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None:
        reservation = self._manager.get(order_id)
        if reservation is not None:
            self._manager.advance_stage(order_id, OnlyPositionReservationStage.SENT_TO_BROKER, timestamp)

    def acknowledged(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None:
        reservation = self._manager.get(order_id)
        if reservation is not None:
            self._manager.advance_stage(order_id, OnlyPositionReservationStage.BROKER_ACKNOWLEDGED, timestamp)

    def consume(
        self,
        order_id: OnlyOrderId,
        quantity: OnlyQuantity,
        timestamp: OnlyTimestamp,
        *,
        allocation_hold_already_released: bool = False,
    ) -> None:
        if self._manager.get(order_id) is not None:
            self._manager.consume(
                order_id,
                quantity,
                timestamp,
                allocation_hold_already_released=allocation_hold_already_released,
            )

    def release(
        self,
        order_id: OnlyOrderId,
        timestamp: OnlyTimestamp,
        *,
        broker_confirmed: bool,
    ) -> None:
        if self._manager.get(order_id) is not None:
            self._manager.release(order_id, timestamp, broker_confirmed=broker_confirmed)
