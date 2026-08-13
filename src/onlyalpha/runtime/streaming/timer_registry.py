"""Logical Streaming Timer authority separated from wall-clock scheduling."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum

from onlyalpha.core.clock import OnlyClock, OnlyTimerEvent, OnlyTimerHandle, OnlyTimerId, OnlyTimerMode
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.runtime.persistence.timer_journal import (
    OnlyRuntimeTimerOccurrence,
    OnlyRuntimeTimerOccurrenceJournal,
)


class OnlyRuntimeTimerLogicalState(StrEnum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    MISSED = "MISSED"


@dataclass(frozen=True, slots=True)
class OnlyRuntimeTimerDefinition:
    timer_id: OnlyTimerId
    cluster_id: OnlyClusterId
    mode: OnlyTimerMode
    next_deadline_ns: int
    interval_ns: int | None
    logical_sequence: int
    fire_count: int
    state: OnlyRuntimeTimerLogicalState


class OnlyRuntimeTimerRegistry:
    """Own logical Timer definitions; Clock remains a wake-up driver only."""

    checkpoint_schema_version = 1

    def __init__(
        self,
        runtime_id: OnlyRuntimeId,
        clock: OnlyClock,
        journal: OnlyRuntimeTimerOccurrenceJournal,
        execute_occurrence: Callable[
            [
                OnlyRuntimeTimerOccurrence,
                OnlyTimerEvent,
                Callable[[OnlyTimerEvent], None],
                Callable[[], None],
            ],
            None,
        ],
    ) -> None:
        self._runtime_id = runtime_id
        self._clock = clock
        self._journal = journal
        self._execute_occurrence = execute_occurrence
        self._definitions: dict[OnlyTimerId, OnlyRuntimeTimerDefinition] = {}
        self._handles: dict[OnlyTimerId, OnlyTimerHandle] = {}
        self._callbacks: dict[OnlyTimerId, Callable[[OnlyTimerEvent], None]] = {}
        self._sequence = 0

    def schedule_at(
        self,
        timer_id: OnlyTimerId,
        cluster_id: OnlyClusterId,
        when_ns: int,
        callback: Callable[[OnlyTimerEvent], None],
    ) -> OnlyTimerHandle:
        return self._schedule(timer_id, cluster_id, OnlyTimerMode.ONE_SHOT, when_ns, None, callback)

    def schedule_after(
        self,
        timer_id: OnlyTimerId,
        cluster_id: OnlyClusterId,
        delay_ns: int,
        callback: Callable[[OnlyTimerEvent], None],
    ) -> OnlyTimerHandle:
        return self.schedule_at(timer_id, cluster_id, self._clock.timestamp_ns() + delay_ns, callback)

    def schedule_every(
        self,
        timer_id: OnlyTimerId,
        cluster_id: OnlyClusterId,
        interval_ns: int,
        callback: Callable[[OnlyTimerEvent], None],
        *,
        start_ns: int | None = None,
    ) -> OnlyTimerHandle:
        deadline = self._clock.timestamp_ns() + interval_ns if start_ns is None else start_ns
        return self._schedule(timer_id, cluster_id, OnlyTimerMode.FIXED_RATE, deadline, interval_ns, callback)

    def cancel(self, timer_id: OnlyTimerId) -> bool:
        definition = self._definitions.get(timer_id)
        if definition is None or definition.state is not OnlyRuntimeTimerLogicalState.SCHEDULED:
            return False
        self._definitions[timer_id] = replace(definition, state=OnlyRuntimeTimerLogicalState.CANCELLED)
        handle = self._handles.get(timer_id)
        return False if handle is None else handle.cancel()

    @property
    def definitions(self) -> tuple[OnlyRuntimeTimerDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions, key=str))

    @property
    def callbacks(self) -> Mapping[OnlyTimerId, Callable[[OnlyTimerEvent], None]]:
        return dict(self._callbacks)

    def recover_occurrence(
        self,
        occurrence: OnlyRuntimeTimerOccurrence,
        callback: Callable[[OnlyTimerEvent], None],
    ) -> None:
        definition = self._definitions.get(occurrence.timer_id)
        if definition is None or definition.cluster_id != occurrence.cluster_id:
            raise RuntimeError(f"STREAMING_TIMER_AUTHORITY_MISSING: {occurrence.timer_id}")
        event = OnlyTimerEvent(
            occurrence.timer_id,
            occurrence.deadline_ns,
            occurrence.admitted_at.unix_nanos,
            occurrence.occurrence_sequence,
            occurrence.fire_count,
        )
        self._execute_occurrence(occurrence, event, callback, lambda: self.complete_occurrence(occurrence))

    def complete_occurrence(self, occurrence: OnlyRuntimeTimerOccurrence) -> None:
        definition = self._definitions.get(occurrence.timer_id)
        if definition is None or definition.cluster_id != occurrence.cluster_id:
            raise RuntimeError(f"STREAMING_TIMER_AUTHORITY_MISSING: {occurrence.timer_id}")
        next_deadline = definition.next_deadline_ns
        state = OnlyRuntimeTimerLogicalState.COMPLETED
        if definition.mode is not OnlyTimerMode.ONE_SHOT:
            if definition.interval_ns is None:
                raise RuntimeError("STREAMING_TIMER_INTERVAL_MISSING")
            next_deadline += definition.interval_ns
            state = OnlyRuntimeTimerLogicalState.SCHEDULED
        self._definitions[definition.timer_id] = replace(
            definition,
            next_deadline_ns=next_deadline,
            fire_count=max(definition.fire_count, occurrence.fire_count + 1),
            state=state,
        )

    def capture_checkpoint(self) -> object:
        return {
            "logical_sequence": self._sequence,
            "timers": [
                {
                    "cluster_id": str(item.cluster_id),
                    "fire_count": item.fire_count,
                    "interval_ns": item.interval_ns,
                    "logical_sequence": item.logical_sequence,
                    "mode": item.mode.value,
                    "next_deadline_ns": item.next_deadline_ns,
                    "state": item.state.value,
                    "timer_id": str(item.timer_id),
                }
                for item in self.definitions
            ],
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, Mapping) or not isinstance(payload["timers"], list):
            raise ValueError("Streaming Timer checkpoint must be an object with timers")
        for handle in self._handles.values():
            handle.cancel()
        self._handles.clear()
        self._sequence = int(payload["logical_sequence"])
        restored: dict[OnlyTimerId, OnlyRuntimeTimerDefinition] = {}
        for raw in payload["timers"]:
            if not isinstance(raw, Mapping):
                raise ValueError("Streaming Timer checkpoint entry must be an object")
            timer_id = OnlyTimerId(str(raw["timer_id"]))
            restored[timer_id] = OnlyRuntimeTimerDefinition(
                timer_id,
                OnlyClusterId(str(raw["cluster_id"])),
                OnlyTimerMode(str(raw["mode"])),
                int(raw["next_deadline_ns"]),
                None if raw["interval_ns"] is None else int(raw["interval_ns"]),
                int(raw["logical_sequence"]),
                int(raw["fire_count"]),
                OnlyRuntimeTimerLogicalState(str(raw["state"])),
            )
        self._definitions = restored

    def rearm_after_restore(self, callbacks: Mapping[OnlyTimerId, Callable[[OnlyTimerEvent], None]]) -> None:
        now = self._clock.timestamp_ns()
        for definition in self.definitions:
            callback = callbacks.get(definition.timer_id)
            if callback is None:
                raise RuntimeError(f"STREAMING_TIMER_CALLBACK_MISSING: {definition.timer_id}")
            self._callbacks[definition.timer_id] = callback
            if definition.state is not OnlyRuntimeTimerLogicalState.SCHEDULED:
                continue
            deadline = definition.next_deadline_ns
            if deadline <= now:
                if definition.mode is OnlyTimerMode.ONE_SHOT:
                    self._definitions[definition.timer_id] = replace(
                        definition, state=OnlyRuntimeTimerLogicalState.MISSED
                    )
                    continue
                if definition.interval_ns is None:
                    raise RuntimeError("STREAMING_TIMER_INTERVAL_MISSING")
                missed = ((now - deadline) // definition.interval_ns) + 1
                deadline += missed * definition.interval_ns
                self._definitions[definition.timer_id] = replace(definition, next_deadline_ns=deadline)
            self._arm(self._definitions[definition.timer_id], callback)

    def _schedule(
        self,
        timer_id: OnlyTimerId,
        cluster_id: OnlyClusterId,
        mode: OnlyTimerMode,
        deadline_ns: int,
        interval_ns: int | None,
        callback: Callable[[OnlyTimerEvent], None],
    ) -> OnlyTimerHandle:
        if timer_id in self._definitions:
            raise ValueError(f"duplicate Runtime Timer: {timer_id}")
        self._sequence += 1
        definition = OnlyRuntimeTimerDefinition(
            timer_id,
            cluster_id,
            mode,
            deadline_ns,
            interval_ns,
            self._sequence,
            0,
            OnlyRuntimeTimerLogicalState.SCHEDULED,
        )
        self._definitions[timer_id] = definition
        self._callbacks[timer_id] = callback
        return self._arm(definition, callback)

    def _arm(
        self, definition: OnlyRuntimeTimerDefinition, callback: Callable[[OnlyTimerEvent], None]
    ) -> OnlyTimerHandle:
        def admitted(event: OnlyTimerEvent) -> None:
            occurrence = self._journal.admit(
                self._runtime_id,
                definition.timer_id,
                definition.cluster_id,
                event,
                OnlyTimestamp.from_unix_nanos(self._clock.timestamp_ns()),
            )
            self._execute_occurrence(occurrence, event, callback, lambda: self.complete_occurrence(occurrence))

        if definition.mode is OnlyTimerMode.ONE_SHOT:
            handle = self._clock.schedule_at(definition.timer_id, definition.next_deadline_ns, admitted)
        else:
            if definition.interval_ns is None:
                raise RuntimeError("STREAMING_TIMER_INTERVAL_MISSING")
            handle = self._clock.schedule_every(
                definition.timer_id,
                definition.interval_ns,
                admitted,
                start_ns=definition.next_deadline_ns,
            )
        self._handles[definition.timer_id] = handle
        return handle


__all__ = [
    "OnlyRuntimeTimerDefinition",
    "OnlyRuntimeTimerLogicalState",
    "OnlyRuntimeTimerRegistry",
]
