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


@dataclass(frozen=True, slots=True)
class OnlyFeeExecutionAuthoritySnapshot:
    """Manager-owned Fee authority for one immutable instruction."""

    instruction: OnlyFeeInstruction
    instrument_id: str
    records: tuple[OnlyFeeRecord, ...]
    version: int
    record_sequence_head: int


class OnlyFeeManager:
    """Append-only fee facts, idempotent by the resolved instruction key."""

    def __init__(self) -> None:
        self._records: list[OnlyFeeRecord] = []
        self._instruction_keys: set[str] = set()
        self._instructions_by_key: dict[str, OnlyFeeInstruction] = {}
        self._instrument_by_key: dict[str, str] = {}
        self._sequence = 0

    @property
    def records(self) -> tuple[OnlyFeeRecord, ...]:
        return tuple(self._records)

    @property
    def sequence_head(self) -> int:
        return self._sequence

    def has_instruction_key(self, idempotency_key: str) -> bool:
        return idempotency_key in self._instruction_keys

    def get_execution_authority(self, idempotency_key: str) -> OnlyFeeExecutionAuthoritySnapshot | None:
        instruction = self._instructions_by_key.get(idempotency_key)
        if instruction is None:
            return None
        records = tuple(item for item in self._records if item.idempotency_key == idempotency_key)
        return OnlyFeeExecutionAuthoritySnapshot(
            instruction,
            self._instrument_by_key[idempotency_key],
            records,
            1,
            self._sequence,
        )

    def apply(self, instruction: OnlyFeeInstruction, *, instrument_id: str) -> tuple[OnlyFeeRecord, ...]:
        current = self._instructions_by_key.get(instruction.idempotency_key)
        if current is not None:
            if current != instruction or self._instrument_by_key[instruction.idempotency_key] != instrument_id:
                raise ValueError("FEE_INSTRUCTION_AUTHORITY_CONFLICT")
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
        self._instructions_by_key[instruction.idempotency_key] = instruction
        self._instrument_by_key[instruction.idempotency_key] = instrument_id
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
        key = instruction.idempotency_key
        current_instruction = self._instructions_by_key.get(key)
        if current_instruction is not None and (
            current_instruction != instruction or self._instrument_by_key[key] != instrument_id
        ):
            raise ValueError("FEE_INSTRUCTION_AUTHORITY_CONFLICT")
        expected_records = tuple(
            OnlyFeeRecord(
                record_id,
                instruction.instruction_id,
                key,
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
            for sequence, record_id, component in zip(
                range(start, sequence_head + 1), record_ids, instruction.fee_breakdown.components, strict=True
            )
        )
        existing_by_id = {item.fee_record_id: item for item in self._records}
        existing_by_sequence = {item.sequence: item for item in self._records}
        for item in expected_records:
            if (current := existing_by_id.get(item.fee_record_id)) is not None and current != item:
                raise ValueError("Fee replay record ID conflicts with existing authority")
            if (current := existing_by_sequence.get(item.sequence)) is not None and current != item:
                raise ValueError("Fee replay record sequence conflicts with existing authority")
        records = list(self._records)
        known = set(existing_by_id)
        records.extend(item for item in expected_records if item.fee_record_id not in known)
        records.sort(key=lambda item: item.sequence)
        instructions = dict(self._instructions_by_key)
        instruments = dict(self._instrument_by_key)
        keys = set(self._instruction_keys)
        instructions[key] = instruction
        instruments[key] = instrument_id
        keys.add(key)
        self._records = records
        self._instructions_by_key = instructions
        self._instrument_by_key = instruments
        self._instruction_keys = keys
        self._sequence = sequence_head


__all__ = ["OnlyFeeExecutionAuthoritySnapshot", "OnlyFeeManager", "OnlyFeeRecord"]
