"""Runtime-scoped deterministic Risk Reservations."""

from dataclasses import dataclass, replace
from decimal import Decimal

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyQuantity
from onlyalpha.risk.enums import (
    OnlyRiskReleaseReason,
    OnlyRiskReservationApplyResult,
    OnlyRiskReservationState,
    OnlyRiskReservationType,
)
from onlyalpha.risk.identifiers import OnlyRiskReservationId


@dataclass(frozen=True, slots=True)
class OnlyRiskReservation(OnlyDomainModel):
    reservation_id: OnlyRiskReservationId
    reservation_type: OnlyRiskReservationType
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId
    order_id: OnlyOrderId
    instrument_id: OnlyInstrumentId
    reserved_notional: OnlyMoney | None
    reserved_quantity: OnlyQuantity
    created_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    state: OnlyRiskReservationState = OnlyRiskReservationState.ACTIVE
    version: int = 1
    release_reason: OnlyRiskReleaseReason | None = None


@dataclass(frozen=True, slots=True)
class OnlyRiskReservationResult:
    apply_result: OnlyRiskReservationApplyResult
    changed: bool
    reservation: OnlyRiskReservation | None
    error: str | None = None


class OnlyRiskReservationManager:
    """Single-writer Reservation truth for one Runtime."""

    def __init__(self, runtime_id: OnlyRuntimeId) -> None:
        self.runtime_id = runtime_id
        self._sequence = 0
        self._reservations: dict[OnlyRiskReservationId, OnlyRiskReservation] = {}
        self._reservation_id_by_order_id: dict[OnlyOrderId, OnlyRiskReservationId] = {}

    def create(
        self,
        cluster_id: OnlyClusterId,
        account_id: OnlyAccountId,
        order_id: OnlyOrderId,
        instrument_id: OnlyInstrumentId,
        reserved_notional: OnlyMoney | None,
        reserved_quantity: OnlyQuantity,
        timestamp: OnlyTimestamp,
    ) -> OnlyRiskReservationResult:
        existing_id = self._reservation_id_by_order_id.get(order_id)
        if existing_id is not None:
            return OnlyRiskReservationResult(
                OnlyRiskReservationApplyResult.DUPLICATE,
                False,
                self._reservations[existing_id],
            )
        self._sequence += 1
        reservation_id = OnlyRiskReservationId(f"{self.runtime_id}-RISK-{self._sequence:06d}")
        reservation = OnlyRiskReservation(
            reservation_id,
            OnlyRiskReservationType.ORDER,
            self.runtime_id,
            cluster_id,
            account_id,
            order_id,
            instrument_id,
            reserved_notional,
            reserved_quantity,
            timestamp,
            timestamp,
        )
        self._reservations[reservation_id] = reservation
        self._reservation_id_by_order_id[order_id] = reservation_id
        return OnlyRiskReservationResult(OnlyRiskReservationApplyResult.APPLIED, True, reservation)

    def release(
        self,
        reservation_id: OnlyRiskReservationId,
        reason: OnlyRiskReleaseReason,
        timestamp: OnlyTimestamp,
        *,
        runtime_id: OnlyRuntimeId,
        cluster_id: OnlyClusterId,
    ) -> OnlyRiskReservationResult:
        reservation = self._reservations.get(reservation_id)
        if reservation is None:
            return OnlyRiskReservationResult(OnlyRiskReservationApplyResult.NOT_FOUND, False, None)
        if reservation.runtime_id != runtime_id or reservation.cluster_id != cluster_id:
            return OnlyRiskReservationResult(
                OnlyRiskReservationApplyResult.INVALID,
                False,
                reservation,
                "Reservation Scope mismatch",
            )
        if reservation.state is OnlyRiskReservationState.RELEASED:
            return OnlyRiskReservationResult(OnlyRiskReservationApplyResult.DUPLICATE, False, reservation)
        if reservation.state is not OnlyRiskReservationState.ACTIVE:
            return OnlyRiskReservationResult(
                OnlyRiskReservationApplyResult.INVALID,
                False,
                reservation,
                f"Reservation is not ACTIVE: {reservation.state.value}",
            )
        updated = replace(
            reservation,
            state=OnlyRiskReservationState.RELEASED,
            release_reason=reason,
            updated_at=timestamp,
            version=reservation.version + 1,
        )
        self._reservations[reservation_id] = updated
        return OnlyRiskReservationResult(OnlyRiskReservationApplyResult.APPLIED, True, updated)

    def release_for_order(
        self,
        order_id: OnlyOrderId,
        reason: OnlyRiskReleaseReason,
        timestamp: OnlyTimestamp,
        *,
        runtime_id: OnlyRuntimeId,
        cluster_id: OnlyClusterId,
    ) -> OnlyRiskReservationResult:
        reservation_id = self._reservation_id_by_order_id.get(order_id)
        if reservation_id is None:
            return OnlyRiskReservationResult(OnlyRiskReservationApplyResult.NOT_FOUND, False, None)
        return self.release(
            reservation_id,
            reason,
            timestamp,
            runtime_id=runtime_id,
            cluster_id=cluster_id,
        )

    def release_cluster(
        self,
        cluster_id: OnlyClusterId,
        timestamp: OnlyTimestamp,
    ) -> tuple[OnlyRiskReservationResult, ...]:
        return tuple(
            self.release(
                item.reservation_id,
                OnlyRiskReleaseReason.CLUSTER_STOPPED,
                timestamp,
                runtime_id=self.runtime_id,
                cluster_id=cluster_id,
            )
            for item in self.snapshot_active()
            if item.cluster_id == cluster_id
        )

    def get_for_order(self, order_id: OnlyOrderId) -> OnlyRiskReservation | None:
        reservation_id = self._reservation_id_by_order_id.get(order_id)
        return None if reservation_id is None else self._reservations[reservation_id]

    def snapshot_all(self) -> tuple[OnlyRiskReservation, ...]:
        return tuple(self._reservations[key] for key in sorted(self._reservations, key=str))

    def snapshot_active(self) -> tuple[OnlyRiskReservation, ...]:
        return tuple(item for item in self.snapshot_all() if item.state is OnlyRiskReservationState.ACTIVE)

    def active_notional(
        self,
        currency: OnlyCurrency,
        *,
        cluster_id: OnlyClusterId | None = None,
        account_id: OnlyAccountId | None = None,
        instrument_id: OnlyInstrumentId | None = None,
    ) -> OnlyMoney:
        amount = sum(
            (
                item.reserved_notional.amount
                for item in self.snapshot_active()
                if item.reserved_notional is not None
                and item.reserved_notional.currency == currency
                and (cluster_id is None or item.cluster_id == cluster_id)
                and (account_id is None or item.account_id == account_id)
                and (instrument_id is None or item.instrument_id == instrument_id)
            ),
            Decimal("0"),
        )
        return OnlyMoney(amount, currency)

    def active_quantity(
        self,
        instrument_id: OnlyInstrumentId,
        *,
        cluster_id: OnlyClusterId | None = None,
        account_id: OnlyAccountId | None = None,
    ) -> Decimal:
        return sum(
            (
                item.reserved_quantity.value
                for item in self.snapshot_active()
                if item.instrument_id == instrument_id
                and (cluster_id is None or item.cluster_id == cluster_id)
                and (account_id is None or item.account_id == account_id)
            ),
            Decimal("0"),
        )
