"""Instruction-driven margin reservation and occupation lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.market.runtime_rules import OnlyMarginInstruction


@dataclass(frozen=True, slots=True)
class OnlyMarginReservation:
    source_order_id: str
    currency: str
    reserved: Decimal
    occupied: Decimal
    maintenance_required: Decimal


@dataclass(frozen=True, slots=True)
class OnlyMarginRecord:
    sequence: int
    action: str
    source_order_id: str
    source_trade_id: str
    currency: str
    amount: Decimal
    reserved_after: Decimal
    occupied_after: Decimal
    maintenance_required_after: Decimal


class OnlyMarginManager:
    """Own margin state; rates and actions come exclusively from instructions."""

    def __init__(self) -> None:
        self._states: dict[str, OnlyMarginReservation] = {}
        self._records: list[OnlyMarginRecord] = []

    @property
    def records(self) -> tuple[OnlyMarginRecord, ...]:
        return tuple(self._records)

    def get(self, order_id: str) -> OnlyMarginReservation | None:
        return self._states.get(order_id)

    def apply(self, instruction: OnlyMarginInstruction) -> OnlyMarginRecord:
        current = self._states.get(
            instruction.source_order_id,
            OnlyMarginReservation(
                instruction.source_order_id, instruction.currency, Decimal(0), Decimal(0), Decimal(0)
            ),
        )
        if current.currency != instruction.currency:
            raise ValueError("margin instruction currency differs from reservation")
        reserved, occupied, maintenance = current.reserved, current.occupied, current.maintenance_required
        if instruction.action == "RESERVE":
            reserved += instruction.amount
            maintenance += instruction.maintenance_required
        elif instruction.action == "OCCUPY":
            moved = min(reserved, instruction.amount)
            reserved -= moved
            occupied += instruction.amount
            maintenance += instruction.maintenance_required
        elif instruction.action == "RELEASE":
            remaining = instruction.amount
            from_reserved = min(reserved, remaining)
            reserved -= from_reserved
            remaining -= from_reserved
            occupied = max(occupied - remaining, Decimal(0))
            maintenance = max(maintenance - instruction.maintenance_required, Decimal(0))
        else:
            raise ValueError(f"unsupported margin instruction action: {instruction.action}")
        state = OnlyMarginReservation(current.source_order_id, current.currency, reserved, occupied, maintenance)
        self._states[current.source_order_id] = state
        record = OnlyMarginRecord(
            len(self._records) + 1,
            instruction.action,
            instruction.source_order_id,
            instruction.source_trade_id,
            instruction.currency,
            instruction.amount,
            reserved,
            occupied,
            maintenance,
        )
        self._records.append(record)
        return record


OnlyMarginProcessor = OnlyMarginManager
