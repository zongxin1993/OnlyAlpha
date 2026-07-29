"""Instruction-driven margin reservation and occupation lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyInstrumentId, OnlyOrderId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency
from onlyalpha.margin.models import OnlyMarginReservation
from onlyalpha.market.runtime_rules import OnlyMarginInstruction


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

    def __init__(self, runtime_id: OnlyRuntimeId) -> None:
        self.runtime_id = runtime_id
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
        return tuple(
            self._states[key]
            for key in sorted(self._states)
            if self._states[key].reserved > 0 or self._states[key].occupied > 0
        )

    def occupied(self, account_id: str, instrument_id: str, currency: str) -> Decimal:
        return self._occupied.get((account_id, instrument_id, currency), (Decimal(0), Decimal(0)))[0]

    def apply(self, instruction: OnlyMarginInstruction) -> OnlyMarginRecord:
        if instruction.action == "RELEASE":
            return self._apply_release(instruction)
        current = self._states.get(instruction.source_order_id)
        if current is None:
            reservation_id = f"MRES-{self.runtime_id}-{instruction.source_order_id}"
            account_id = OnlyAccountId(instruction.account_id)
            instrument_id = OnlyInstrumentId.parse(instruction.instrument_id)
            order_id = OnlyOrderId(instruction.source_order_id)
            currency = OnlyCurrency(instruction.currency)
            original = reserved = occupied = released = maintenance = Decimal(0)
            created_at = instruction.timestamp
            version = 0
        else:
            if (
                current.currency.code != instruction.currency
                or str(current.account_id) != instruction.account_id
                or str(current.instrument_id) != instruction.instrument_id
            ):
                raise ValueError("margin instruction currency differs from reservation")
            reservation_id = current.reservation_id
            account_id = current.account_id
            instrument_id = current.instrument_id
            order_id = current.source_order_id
            currency = current.currency
            original = current.original_reserved
            reserved, occupied, released, maintenance = (
                current.reserved,
                current.occupied,
                current.released,
                current.maintenance_required,
            )
            created_at = current.created_at
            version = current.version
        scope = (instruction.account_id, instruction.instrument_id, instruction.currency)
        scope_occupied, scope_maintenance = self._occupied.get(scope, (Decimal(0), Decimal(0)))
        if instruction.action == "RESERVE":
            original += instruction.amount
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
        else:
            raise ValueError(f"unsupported margin instruction action: {instruction.action}")
        if min(original, reserved, occupied, released, maintenance, scope_occupied, scope_maintenance) < 0:
            raise ValueError("margin state cannot become negative")
        state = OnlyMarginReservation(
            reservation_id,
            self.runtime_id,
            account_id,
            instrument_id,
            order_id,
            currency,
            original,
            reserved,
            occupied,
            released,
            maintenance,
            created_at,
            instruction.timestamp,
            version + 1,
        )
        self._states[str(order_id)] = state
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

    def _apply_release(self, instruction: OnlyMarginInstruction) -> OnlyMarginRecord:
        scope = (instruction.account_id, instruction.instrument_id, instruction.currency)
        scope_occupied, scope_maintenance = self._occupied.get(scope, (Decimal(0), Decimal(0)))
        candidates = tuple(
            state
            for _, state in sorted(self._states.items())
            if str(state.account_id) == instruction.account_id
            and str(state.instrument_id) == instruction.instrument_id
            and state.currency.code == instruction.currency
            and (state.reserved > 0 or state.occupied > 0)
        )
        remaining = instruction.amount
        released_occupied = Decimal(0)
        for state in candidates:
            if remaining == 0:
                break
            from_reserved = min(state.reserved, remaining)
            remaining -= from_reserved
            from_occupied = min(state.occupied, remaining)
            remaining -= from_occupied
            released = from_reserved + from_occupied
            if released == 0:
                continue
            maintenance = max(state.maintenance_required - instruction.maintenance_required, Decimal(0))
            self._states[str(state.source_order_id)] = OnlyMarginReservation(
                state.reservation_id,
                state.runtime_id,
                state.account_id,
                state.instrument_id,
                state.source_order_id,
                state.currency,
                state.original_reserved,
                state.reserved - from_reserved,
                state.occupied - from_occupied,
                state.released + released,
                maintenance,
                state.created_at,
                instruction.timestamp,
                state.version + 1,
            )
            released_occupied += from_occupied
        scope_occupied -= released_occupied
        scope_maintenance = max(scope_maintenance - instruction.maintenance_required, Decimal(0))
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
            sum((item.reserved for item in self._states.values() if self._margin_scope(item) == scope), Decimal(0)),
            scope_occupied,
            scope_maintenance,
        )
        self._records.append(record)
        return record

    def capture_checkpoint(self) -> object:
        return {
            "occupied": [[list(key), str(value[0]), str(value[1])] for key, value in sorted(self._occupied.items())],
            "records": [
                {
                    "account_id": item.account_id,
                    "action": item.action,
                    "amount": str(item.amount),
                    "currency": item.currency,
                    "instrument_id": item.instrument_id,
                    "maintenance_required_after": str(item.maintenance_required_after),
                    "occupied_after": str(item.occupied_after),
                    "reserved_after": str(item.reserved_after),
                    "sequence": item.sequence,
                    "source_order_id": item.source_order_id,
                    "source_trade_id": item.source_trade_id,
                }
                for item in self._records
            ],
            "states": [
                {
                    "account_id": str(item.account_id),
                    "created_at_ns": item.created_at.unix_nanos,
                    "currency": item.currency.code,
                    "instrument_id": str(item.instrument_id),
                    "maintenance_required": str(item.maintenance_required),
                    "occupied": str(item.occupied),
                    "original_reserved": str(item.original_reserved),
                    "released": str(item.released),
                    "reservation_id": item.reservation_id,
                    "reserved": str(item.reserved),
                    "source_order_id": str(item.source_order_id),
                    "updated_at_ns": item.updated_at.unix_nanos,
                    "version": item.version,
                }
                for item in sorted(self._states.values(), key=lambda value: str(value.source_order_id))
            ],
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Margin checkpoint must be an object")
        self._states = {}
        for item in payload["states"]:
            if not isinstance(item, dict):
                raise ValueError("Margin checkpoint state must be an object")
            state = OnlyMarginReservation(
                str(item["reservation_id"]),
                self.runtime_id,
                OnlyAccountId(str(item["account_id"])),
                OnlyInstrumentId.parse(str(item["instrument_id"])),
                OnlyOrderId(str(item["source_order_id"])),
                OnlyCurrency(str(item["currency"])),
                Decimal(str(item["original_reserved"])),
                Decimal(str(item["reserved"])),
                Decimal(str(item["occupied"])),
                Decimal(str(item["released"])),
                Decimal(str(item["maintenance_required"])),
                OnlyTimestamp.from_unix_nanos(int(item["created_at_ns"])),
                OnlyTimestamp.from_unix_nanos(int(item["updated_at_ns"])),
                int(item["version"]),
            )
            self._states[str(state.source_order_id)] = state
        occupied_states: dict[tuple[str, str, str], tuple[Decimal, Decimal]] = {}
        for key, occupied, maintenance in payload["occupied"]:
            if not isinstance(key, list) or len(key) != 3:
                raise ValueError("Margin occupied checkpoint scope must contain three values")
            occupied_states[(str(key[0]), str(key[1]), str(key[2]))] = (
                Decimal(str(occupied)),
                Decimal(str(maintenance)),
            )
        self._occupied = occupied_states
        self._records = [
            OnlyMarginRecord(
                int(item["sequence"]),
                str(item["action"]),
                str(item["account_id"]),
                str(item["instrument_id"]),
                str(item["source_order_id"]),
                str(item["source_trade_id"]),
                str(item["currency"]),
                Decimal(str(item["amount"])),
                Decimal(str(item["reserved_after"])),
                Decimal(str(item["occupied_after"])),
                Decimal(str(item["maintenance_required_after"])),
            )
            for item in payload["records"]
            if isinstance(item, dict)
        ]

    @staticmethod
    def _margin_scope(reservation: OnlyMarginReservation) -> tuple[str, str, str]:
        return str(reservation.account_id), str(reservation.instrument_id), reservation.currency.code
