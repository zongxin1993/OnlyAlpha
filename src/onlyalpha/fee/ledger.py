"""Runtime-owned append-only Fee Application ledger."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyTradeId,
)
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.fee.application import OnlyFeeApplicationInstruction
from onlyalpha.fee.models import OnlyFeeComponentIdentity, OnlyLocalFeeFinality


@dataclass(frozen=True, slots=True)
class OnlyFeeApplicationRecord(OnlyDomainModel):
    record_id: str
    application_id: str
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId
    order_id: OnlyOrderId
    trade_id: OnlyTradeId
    component_identity: OnlyFeeComponentIdentity
    fill_raw_amount: OnlyMoney
    cumulative_raw_after: OnlyMoney
    cumulative_target_after: OnlyMoney
    cumulative_applied_before: OnlyMoney
    incremental_amount: OnlyMoney
    cumulative_applied_after: OnlyMoney
    local_finality: OnlyLocalFeeFinality
    sequence: int


@dataclass(frozen=True, slots=True)
class OnlyFeeApplicationAuthoritySnapshot:
    instruction: OnlyFeeApplicationInstruction
    instrument_id: OnlyInstrumentId
    records: tuple[OnlyFeeApplicationRecord, ...]
    version: int
    record_sequence_head: int


class OnlyFeeApplicationLedger:
    def __init__(self) -> None:
        self._records: list[OnlyFeeApplicationRecord] = []
        self._instructions: dict[str, OnlyFeeApplicationInstruction] = {}
        self._instruments: dict[str, OnlyInstrumentId] = {}
        self._sequence = 0

    @property
    def records(self) -> tuple[OnlyFeeApplicationRecord, ...]:
        return tuple(self._records)

    @property
    def sequence_head(self) -> int:
        return self._sequence

    def get(self, idempotency_key: str) -> OnlyFeeApplicationAuthoritySnapshot | None:
        instruction = self._instructions.get(idempotency_key)
        if instruction is None:
            return None
        return OnlyFeeApplicationAuthoritySnapshot(
            instruction,
            self._instruments[idempotency_key],
            tuple(item for item in self._records if item.application_id == instruction.application_id),
            1,
            self._sequence,
        )

    def apply(
        self, instruction: OnlyFeeApplicationInstruction, *, instrument_id: OnlyInstrumentId
    ) -> tuple[OnlyFeeApplicationRecord, ...]:
        key = instruction.idempotency_key
        current = self._instructions.get(key)
        if current is not None:
            if current != instruction or self._instruments[key] != instrument_id:
                raise ValueError("FEE_APPLICATION_AUTHORITY_CONFLICT")
            return ()
        emitted = []
        for component in instruction.components:
            self._sequence += 1
            emitted.append(
                OnlyFeeApplicationRecord(
                    f"FEEAPP-{instruction.application_id}-{self._sequence:08d}",
                    instruction.application_id,
                    instruction.subject.runtime_id,
                    instruction.subject.account_id,
                    instruction.subject.cluster_id,
                    instrument_id,
                    instruction.subject.order_id,
                    instruction.trade_id,
                    component.identity,
                    component.fill_raw_amount,
                    component.cumulative_raw_after,
                    component.cumulative_target_after,
                    component.cumulative_applied_before,
                    component.amount,
                    component.cumulative_applied_after,
                    instruction.local_finality,
                    self._sequence,
                )
            )
        self._records.extend(emitted)
        self._instructions[key] = instruction
        self._instruments[key] = instrument_id
        return tuple(emitted)

    def restore_authority(
        self,
        instruction: OnlyFeeApplicationInstruction,
        *,
        instrument_id: OnlyInstrumentId,
        records: tuple[OnlyFeeApplicationRecord, ...],
        sequence_head: int,
    ) -> None:
        if sequence_head < 0 or sequence_head < max((item.sequence for item in records), default=0):
            raise ValueError("Fee Application replay sequence head is invalid")
        key = instruction.idempotency_key
        current = self._instructions.get(key)
        if current is not None and (current != instruction or self._instruments[key] != instrument_id):
            raise ValueError("FEE_APPLICATION_AUTHORITY_CONFLICT")
        if any(item.application_id != instruction.application_id for item in records):
            raise ValueError("Fee Application replay record scope mismatch")
        existing_ids = {item.record_id: item for item in self._records}
        existing_sequences = {item.sequence: item for item in self._records}
        for item in records:
            if item.record_id in existing_ids and existing_ids[item.record_id] != item:
                raise ValueError("Fee Application replay record identity conflict")
            if item.sequence in existing_sequences and existing_sequences[item.sequence] != item:
                raise ValueError("Fee Application replay record sequence conflict")
        merged = list(self._records)
        merged.extend(item for item in records if item.record_id not in existing_ids)
        merged.sort(key=lambda item: item.sequence)
        self._records = merged
        self._instructions[key] = instruction
        self._instruments[key] = instrument_id
        self._sequence = max(self._sequence, sequence_head)

    def capture_checkpoint(self) -> object:
        return {
            "schema_version": 3,
            "authorities": [
                {
                    "instruction": instruction.to_json(),
                    "instrument_id": str(self._instruments[key]),
                    "records": [
                        item.to_json() for item in self._records if item.application_id == instruction.application_id
                    ],
                }
                for key, instruction in sorted(self._instructions.items())
            ],
            "sequence": self._sequence,
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict) or payload.get("schema_version") != 3:
            raise ValueError("UNSUPPORTED_FEE_CHECKPOINT_SCHEMA")
        authorities = payload.get("authorities")
        if not isinstance(authorities, list):
            raise ValueError("Fee Application checkpoint authorities must be an array")
        restored = OnlyFeeApplicationLedger()
        for item in authorities:
            if not isinstance(item, dict) or not isinstance(item.get("records"), list):
                raise ValueError("Fee Application checkpoint authority is invalid")
            records = tuple(OnlyFeeApplicationRecord.from_json(str(value)) for value in item["records"])
            restored.restore_authority(
                OnlyFeeApplicationInstruction.from_json(str(item["instruction"])),
                instrument_id=OnlyInstrumentId.parse(str(item["instrument_id"])),
                records=records,
                sequence_head=max((record.sequence for record in records), default=0),
            )
        expected_sequence = int(payload.get("sequence", -1))
        if restored.sequence_head != expected_sequence:
            raise ValueError("Fee Application checkpoint sequence mismatch")
        self._records = list(restored._records)
        self._instructions = dict(restored._instructions)
        self._instruments = dict(restored._instruments)
        self._sequence = restored._sequence


__all__ = ["OnlyFeeApplicationAuthoritySnapshot", "OnlyFeeApplicationLedger", "OnlyFeeApplicationRecord"]
