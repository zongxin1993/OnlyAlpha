"""Immutable Margin authority snapshots."""

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyInstrumentId, OnlyOrderId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
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

    def __post_init__(self) -> None:
        if (
            min(self.original_reserved, self.reserved, self.occupied, self.released, self.maintenance_required) < 0
            or self.reserved + self.occupied + self.released != self.original_reserved
            or self.version < 1
            or self.updated_at < self.created_at
        ):
            raise ValueError("Margin Reservation authority/lifecycle is invalid")


__all__ = ["OnlyMarginReservation"]
