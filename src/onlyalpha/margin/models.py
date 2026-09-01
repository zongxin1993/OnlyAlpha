"""Immutable Margin authority snapshots."""

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.enums import OnlyMarginMode
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyInstrumentId, OnlyOrderId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.trading import OnlyPositionSide
from onlyalpha.domain.value import OnlyCurrency


@dataclass(frozen=True, slots=True)
class OnlyMarginReservation:
    reservation_id: str
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    source_order_id: OnlyOrderId
    currency: OnlyCurrency
    original_reserved: Decimal
    reserved: Decimal
    occupied: Decimal
    released: Decimal
    maintenance_required: Decimal
    created_at: OnlyTimestamp
    updated_at: OnlyTimestamp
    version: int
    margin_mode: OnlyMarginMode = OnlyMarginMode.CROSS
    isolation_key: str | None = None
    position_side: OnlyPositionSide = OnlyPositionSide.LONG

    def __post_init__(self) -> None:
        if (
            min(self.original_reserved, self.reserved, self.occupied, self.released, self.maintenance_required) < 0
            or self.reserved + self.occupied + self.released != self.original_reserved
            or self.version < 1
            or self.updated_at < self.created_at
        ):
            raise ValueError("Margin Reservation authority/lifecycle is invalid")
        if self.margin_mode not in {OnlyMarginMode.CROSS, OnlyMarginMode.ISOLATED}:
            raise ValueError("Margin Reservation mode is invalid")
        if self.margin_mode is OnlyMarginMode.ISOLATED and not (self.isolation_key or "").strip():
            raise ValueError("Isolated Margin Reservation requires isolation key")
        if self.margin_mode is OnlyMarginMode.CROSS and self.isolation_key is not None:
            raise ValueError("Cross Margin Reservation cannot carry isolation key")
        if self.position_side not in {OnlyPositionSide.LONG, OnlyPositionSide.SHORT}:
            raise ValueError("Margin Reservation requires a directional Position side")


__all__ = ["OnlyMarginReservation"]
