"""Runtime-owned immutable fee fact ledger.

The manager records instructions; it never interprets a market profile or a
broker report and therefore cannot become a second fee authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.fee.models import OnlyFeeInstruction


@dataclass(frozen=True, slots=True)
class OnlyFeeRecord:
    fee_record_id: str
    instruction_id: str
    idempotency_key: str
    account_id: str
    instrument_id: str
    order_id: str
    trade_id: str
    fee_type: str
    authority: str
    status: str
    accrued: Decimal
    charged: Decimal
    currency: str
    schedule_id: str | None
    schedule_version: str | None
    sequence: int


class OnlyFeeManager:
    """Append-only fee facts, idempotent by the resolved instruction key."""

    def __init__(self) -> None:
        self._records: list[OnlyFeeRecord] = []
        self._instruction_keys: set[str] = set()

    @property
    def records(self) -> tuple[OnlyFeeRecord, ...]:
        return tuple(self._records)

    def apply(self, instruction: OnlyFeeInstruction, *, instrument_id: str) -> tuple[OnlyFeeRecord, ...]:
        if instruction.idempotency_key in self._instruction_keys:
            return ()
        emitted: list[OnlyFeeRecord] = []
        for component in instruction.fee_breakdown.components:
            sequence = len(self._records) + 1
            record = OnlyFeeRecord(
                f"FEE-{instruction.instruction_id}-{sequence:08d}",
                instruction.instruction_id,
                instruction.idempotency_key,
                instruction.account_id,
                instrument_id,
                instruction.order_id,
                instruction.trade_id,
                component.fee_type.value,
                component.authority.value,
                component.status.value,
                component.amount.amount,
                component.amount.amount,
                component.amount.currency.code,
                component.schedule_id,
                component.schedule_version,
                sequence,
            )
            self._records.append(record)
            emitted.append(record)
        self._instruction_keys.add(instruction.idempotency_key)
        return tuple(emitted)
