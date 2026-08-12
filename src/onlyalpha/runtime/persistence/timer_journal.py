"""Runtime-neutral durable admission journal contract for logical Timer occurrences."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.core.clock import OnlyTimerEvent, OnlyTimerId
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp


@dataclass(frozen=True, slots=True)
class OnlyRuntimeTimerOccurrence:
    runtime_id: OnlyRuntimeId
    occurrence_sequence: int
    timer_id: OnlyTimerId
    cluster_id: OnlyClusterId
    deadline_ns: int
    fire_count: int
    admitted_at: OnlyTimestamp
    covered_checkpoint_sequence: int | None = None


class OnlyRuntimeTimerOccurrenceJournal(Protocol):
    def admit(
        self,
        runtime_id: OnlyRuntimeId,
        timer_id: OnlyTimerId,
        cluster_id: OnlyClusterId,
        event: OnlyTimerEvent,
        admitted_at: OnlyTimestamp,
    ) -> OnlyRuntimeTimerOccurrence: ...

    def unresolved(self, runtime_id: OnlyRuntimeId) -> tuple[OnlyRuntimeTimerOccurrence, ...]: ...

    def cover(self, runtime_id: OnlyRuntimeId, checkpoint_sequence: int) -> None: ...


__all__ = ["OnlyRuntimeTimerOccurrence", "OnlyRuntimeTimerOccurrenceJournal"]
