"""Projection-application identity and idempotency authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.domain.base import OnlyDomainModel

from .committed import OnlyCommittedExecutionFact
from .projection import OnlyExecutionProjection, OnlyExecutionProjectionComponent
from .terminal_fact import OnlyCommittedTerminalExecutionFact


def _require_digest(value: str, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class OnlyExecutionProjectionApplyContext(OnlyDomainModel):
    transaction_id: str
    execution_sequence: int
    fact: OnlyCommittedExecutionFact | OnlyCommittedTerminalExecutionFact
    projection: OnlyExecutionProjection

    def __post_init__(self) -> None:
        if not self.transaction_id.strip():
            raise ValueError("Projection apply context requires transaction_id")
        if self.execution_sequence < 1:
            raise ValueError("Projection apply context requires positive execution_sequence")
        if self.fact.execution_sequence != self.execution_sequence:
            raise ValueError("Projection apply context execution sequence disagrees with Fact")


@dataclass(frozen=True, slots=True)
class OnlyAppliedProjectionRecord(OnlyDomainModel):
    transaction_id: str
    execution_sequence: int
    component: OnlyExecutionProjectionComponent
    entity_key: str
    payload_hash: str
    result_state_hash: str

    def __post_init__(self) -> None:
        if not self.transaction_id.strip() or not self.entity_key.strip() or self.execution_sequence < 1:
            raise ValueError("Applied Projection record requires identity and positive sequence")
        _require_digest(self.payload_hash, "Applied Projection payload_hash")
        _require_digest(self.result_state_hash, "Applied Projection result_state_hash")


class OnlyAppliedProjectionLedger(Protocol):
    def get(
        self, execution_sequence: int, component: OnlyExecutionProjectionComponent
    ) -> OnlyAppliedProjectionRecord | None: ...

    def record(self, record: OnlyAppliedProjectionRecord) -> None: ...


class OnlyInMemoryAppliedProjectionLedger:
    def __init__(self) -> None:
        self._records: dict[tuple[int, OnlyExecutionProjectionComponent], OnlyAppliedProjectionRecord] = {}

    def get(
        self, execution_sequence: int, component: OnlyExecutionProjectionComponent
    ) -> OnlyAppliedProjectionRecord | None:
        return self._records.get((execution_sequence, component))

    def record(self, record: OnlyAppliedProjectionRecord) -> None:
        key = (record.execution_sequence, record.component)
        existing = self._records.get(key)
        if existing is not None and existing != record:
            raise ValueError("Applied Projection sequence/component already has different authority")
        self._records.setdefault(key, record)

    def records(self) -> tuple[OnlyAppliedProjectionRecord, ...]:
        keys = sorted(self._records, key=lambda item: (item[0], item[1].value))
        return tuple(self._records[key] for key in keys)


__all__ = [
    "OnlyAppliedProjectionLedger",
    "OnlyAppliedProjectionRecord",
    "OnlyExecutionProjectionApplyContext",
    "OnlyInMemoryAppliedProjectionLedger",
]
