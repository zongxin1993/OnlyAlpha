"""Pure execution-local event production buffer."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.event.model import OnlyEvent


@dataclass(frozen=True, slots=True)
class OnlyExecutionEventBatch:
    """Immutable events produced by one Execution processing attempt."""

    events: tuple[OnlyEvent, ...]

    @property
    def empty(self) -> bool:
        return not self.events


class OnlyExecutionEventBuffer:
    """Collect events only while an explicit processing scope is active."""

    def __init__(self) -> None:
        self._active = False
        self._buffer: list[OnlyEvent] = []

    def begin(self) -> None:
        if self._active:
            raise RuntimeError("nested Execution event buffer is not supported")
        self._buffer = []
        self._active = True

    def add(self, event: OnlyEvent) -> None:
        self._require_active()
        self._buffer.append(event)

    def extend(self, events: tuple[OnlyEvent, ...]) -> None:
        self._require_active()
        self._buffer.extend(events)

    def seal(self) -> OnlyExecutionEventBatch:
        self._require_active()
        batch = OnlyExecutionEventBatch(tuple(self._buffer))
        self._buffer = []
        self._active = False
        return batch

    def abort(self) -> OnlyExecutionEventBatch:
        self._require_active()
        batch = OnlyExecutionEventBatch(tuple(self._buffer))
        self._buffer = []
        self._active = False
        return batch

    def _require_active(self) -> None:
        if not self._active:
            raise RuntimeError("Execution event buffer is not active")


__all__ = ["OnlyExecutionEventBatch", "OnlyExecutionEventBuffer"]
