"""Instruction-driven margin reservation and occupation lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.market.runtime_rules import OnlyMarginInstruction


@dataclass(frozen=True, slots=True)
class OnlyMarginReservation:
    account_id: str
    instrument_id: str
    source_order_id: str
    currency: str
    reserved: Decimal
    occupied: Decimal
    maintenance_required: Decimal


@dataclass(frozen=True, slots=True)
class OnlyMarginRecord:
    sequence: int
    action: str
    account_id: str
    instrument_id: str
    source_order_id: str
    source_trade_id: str
    currency: str
    amount: Decimal
    reserved_after: Decimal
    occupied_after: Decimal
    maintenance_required_after: Decimal

    @property
    def active(self) -> bool:
        return self.reserved_after > 0 or self.occupied_after > 0


class OnlyMarginManager:
    """Own margin state; rates and actions come exclusively from instructions."""

    def __init__(self) -> None:
        self._states: dict[str, OnlyMarginReservation] = {}
        self._occupied: dict[tuple[str, str, str], tuple[Decimal, Decimal]] = {}
        self._records: list[OnlyMarginRecord] = []

    @property
    def records(self) -> tuple[OnlyMarginRecord, ...]:
        return tuple(self._records)

    def get(self, order_id: str) -> OnlyMarginReservation | None:
        return self._states.get(order_id)

    @property
    def active_reservations(self) -> tuple[OnlyMarginReservation, ...]:
        return tuple(self._states[key] for key in sorted(self._states) if self._states[key].reserved > 0)

    def occupied(self, account_id: str, instrument_id: str, currency: str) -> Decimal:
        return self._occupied.get((account_id, instrument_id, currency), (Decimal(0), Decimal(0)))[0]

    def apply(self, instruction: OnlyMarginInstruction) -> OnlyMarginRecord:
        current = self._states.get(
            instruction.source_order_id,
            OnlyMarginReservation(
                instruction.account_id,
                instruction.instrument_id,
                instruction.source_order_id,
                instruction.currency,
                Decimal(0),
                Decimal(0),
                Decimal(0),
            ),
        )
        if (
            current.currency != instruction.currency
            or current.account_id != instruction.account_id
            or current.instrument_id != instruction.instrument_id
        ):
            raise ValueError("margin instruction currency differs from reservation")
        reserved, occupied, maintenance = current.reserved, current.occupied, current.maintenance_required
        scope = (instruction.account_id, instruction.instrument_id, instruction.currency)
        scope_occupied, scope_maintenance = self._occupied.get(scope, (Decimal(0), Decimal(0)))
        if instruction.action == "RESERVE":
            reserved += instruction.amount
            maintenance += instruction.maintenance_required
        elif instruction.action == "OCCUPY":
            moved = min(reserved, instruction.amount)
            if moved != instruction.amount:
                raise ValueError("margin occupation exceeds the order reservation")
            reserved -= moved
            occupied += instruction.amount
            maintenance = instruction.maintenance_required
            scope_occupied += instruction.amount
            scope_maintenance += instruction.maintenance_required
        elif instruction.action == "RELEASE":
            from_reserved = min(reserved, instruction.amount)
            reserved -= from_reserved
            if from_reserved:
                maintenance = max(maintenance - instruction.maintenance_required, Decimal(0))
            released = min(scope_occupied, instruction.amount - from_reserved)
            scope_occupied -= released
            if released:
                scope_maintenance = max(scope_maintenance - instruction.maintenance_required, Decimal(0))
        else:
            raise ValueError(f"unsupported margin instruction action: {instruction.action}")
        if min(reserved, occupied, maintenance, scope_occupied, scope_maintenance) < 0:
            raise ValueError("margin state cannot become negative")
        state = OnlyMarginReservation(
            current.account_id,
            current.instrument_id,
            current.source_order_id,
            current.currency,
            reserved,
            occupied,
            maintenance,
        )
        self._states[current.source_order_id] = state
        self._occupied[scope] = (scope_occupied, scope_maintenance)
        record = OnlyMarginRecord(
            len(self._records) + 1,
            instruction.action,
            instruction.account_id,
            instruction.instrument_id,
            instruction.source_order_id,
            instruction.source_trade_id,
            instruction.currency,
            instruction.amount,
            reserved,
            scope_occupied,
            scope_maintenance,
        )
        self._records.append(record)
        return record
