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
        self._sequence = 0

    @property
    def records(self) -> tuple[OnlyFeeRecord, ...]:
        return tuple(self._records)

    @property
    def sequence_head(self) -> int:
        return self._sequence

    def has_instruction_key(self, idempotency_key: str) -> bool:
        return idempotency_key in self._instruction_keys

    def apply(self, instruction: OnlyFeeInstruction, *, instrument_id: str) -> tuple[OnlyFeeRecord, ...]:
        if instruction.idempotency_key in self._instruction_keys:
            return ()
        emitted: list[OnlyFeeRecord] = []
        for component in instruction.fee_breakdown.components:
            sequence = self._sequence + 1
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
            self._sequence = sequence
            emitted.append(record)
        self._instruction_keys.add(instruction.idempotency_key)
        return tuple(emitted)

    def restore_execution_authority(
        self,
        instruction: OnlyFeeInstruction,
        *,
        instrument_id: str,
        record_ids: tuple[str, ...],
        sequence_head: int,
    ) -> None:
        if len(record_ids) != len(instruction.fee_breakdown.components):
            raise ValueError("Fee replay record/component count mismatch")
        start = sequence_head - len(record_ids) + 1
        if start < 1:
            raise ValueError("Fee replay sequence head is invalid")
        if sequence_head < self._sequence:
            raise ValueError("Fee replay sequence cannot regress")
        existing = {item.fee_record_id for item in self._records}
        for sequence, record_id, component in zip(
            range(start, sequence_head + 1), record_ids, instruction.fee_breakdown.components, strict=True
        ):
            if record_id in existing:
                continue
            self._records.append(
                OnlyFeeRecord(
                    record_id,
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
            )
        self._records.sort(key=lambda item: item.sequence)
        self._instruction_keys.add(instruction.idempotency_key)
        self._sequence = sequence_head
