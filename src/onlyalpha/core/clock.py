"""Runtime-owned UTC clocks and deterministic timer scheduling."""

from __future__ import annotations

import heapq
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType

from onlyalpha.core.errors import OnlyError, OnlyValidationError
from onlyalpha.core.time import (
    only_datetime_to_unix_ns,
    only_ensure_utc_aware,
    only_unix_ns_to_datetime_utc,
)

_LOGGER = logging.getLogger(__name__)


class OnlyClockError(OnlyError):
    """Base error for Clock lifecycle, timer, and advancement failures."""


class OnlyDuplicateTimerError(OnlyClockError):
    """Raised when a timer identifier has already been used by a Clock."""


class OnlyClockState(Enum):
    """Clock lifecycle state."""

    CREATED = "CREATED"
    RUNNING = "RUNNING"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


class OnlyTimerMode(Enum):
    """Timer recurrence semantics."""

    ONE_SHOT = "ONE_SHOT"
    FIXED_RATE = "FIXED_RATE"
    FIXED_DELAY = "FIXED_DELAY"


class OnlyTimerState(Enum):
    """Timer lifecycle state."""

    SCHEDULED = "SCHEDULED"
    FIRING = "FIRING"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, order=True, slots=True)
class OnlyTimerId:
    """Validated identifier unique for the lifetime of one Clock."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized:
            raise OnlyValidationError("timer_id is required")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OnlyTimerEvent:
    """A deterministic timer firing fact passed to the callback."""

    timer_id: OnlyTimerId
    deadline_ns: int
    fired_at_ns: int
    sequence: int
    fire_count: int


OnlyTimerCallback = Callable[[OnlyTimerEvent], None]


@dataclass(slots=True)
class OnlyTimer:
    """Clock-owned mutable timer state; callers receive read-only snapshots."""

    timer_id: OnlyTimerId
    mode: OnlyTimerMode
    created_at_ns: int
    next_deadline_ns: int
    interval_ns: int | None
    sequence: int
    callback: OnlyTimerCallback = field(repr=False)
    metadata: Mapping[str, str] = field(default_factory=dict)
    state: OnlyTimerState = OnlyTimerState.SCHEDULED
    fire_count: int = 0
    monotonic_deadline_ns: int | None = None

    def __post_init__(self) -> None:
        self.metadata = MappingProxyType(dict(self.metadata))


@dataclass(frozen=True, slots=True)
class OnlyTimerSnapshot:
    """Serializable timer description that deliberately excludes callbacks."""

    timer_id: OnlyTimerId
    mode: OnlyTimerMode
    created_at_ns: int
    next_deadline_ns: int
    interval_ns: int | None
    sequence: int
    state: OnlyTimerState
    fire_count: int
    metadata: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class OnlyClockSnapshot:
    """Virtual Clock state snapshot without non-serializable callbacks."""

    current_timestamp_ns: int
    sequence: int
    active_timers: tuple[OnlyTimerSnapshot, ...]


@dataclass(frozen=True, slots=True)
class OnlyTimerFailure:
    """Structured callback failure retained by a Clock."""

    event: OnlyTimerEvent
    exception: Exception


@dataclass(frozen=True, slots=True)
class OnlyTimeAdvanceResult:
    """All observable effects of one virtual-time advancement."""

    previous_timestamp_ns: int
    current_timestamp_ns: int
    fired_events: tuple[OnlyTimerEvent, ...]
    failures: tuple[OnlyTimerFailure, ...]


class OnlyTimerHandle:
    """Capability to inspect and cancel one timer without exposing Clock control."""

    __slots__ = ("_cancel", "_snapshot", "timer_id")

    def __init__(
        self,
        timer_id: OnlyTimerId,
        cancel: Callable[[OnlyTimerId], bool],
        snapshot: Callable[[OnlyTimerId], OnlyTimerSnapshot],
    ) -> None:
        self.timer_id = timer_id
        self._cancel = cancel
        self._snapshot = snapshot

    def cancel(self) -> bool:
        return self._cancel(self.timer_id)

    @property
    def timer(self) -> OnlyTimerSnapshot:
        return self._snapshot(self.timer_id)


class OnlyClock(ABC):
    """Read-and-schedule Clock interface safe for Runtime services."""

    @abstractmethod
    def now_utc(self) -> datetime:
        """Return the current aware UTC compatibility view."""

    def now(self) -> datetime:
        """Compatibility alias for the phase-one Clock API."""
        return self.now_utc()

    @abstractmethod
    def timestamp_ns(self) -> int:
        """Return authoritative Unix nanoseconds."""

    @abstractmethod
    def monotonic_ns(self) -> int:
        """Return a duration-only monotonic reading."""

    @abstractmethod
    def schedule_at(
        self, timer_id: OnlyTimerId | str, when_ns: int, callback: OnlyTimerCallback
    ) -> OnlyTimerHandle: ...

    @abstractmethod
    def schedule_after(
        self, timer_id: OnlyTimerId | str, delay_ns: int, callback: OnlyTimerCallback
    ) -> OnlyTimerHandle: ...

    @abstractmethod
    def schedule_every(
        self,
        timer_id: OnlyTimerId | str,
        interval_ns: int,
        callback: OnlyTimerCallback,
        *,
        start_ns: int | None = None,
    ) -> OnlyTimerHandle: ...

    @abstractmethod
    def cancel_timer(self, timer_id: OnlyTimerId | str) -> bool: ...

    @abstractmethod
    def has_timer(self, timer_id: OnlyTimerId | str) -> bool: ...

    @abstractmethod
    def close(self) -> None: ...


class OnlyClockView:
    """Read-only Clock facade; scheduling is provided by a scoped TimerService."""

    def __init__(self, clock: OnlyClock) -> None:
        self.__clock = clock

    def now_utc(self) -> datetime:
        return self.__clock.now_utc()

    def timestamp_ns(self) -> int:
        return self.__clock.timestamp_ns()

    def monotonic_ns(self) -> int:
        return self.__clock.monotonic_ns()


class OnlyVirtualClock(OnlyClock):
    """Single-threaded, explicitly advanced Clock for deterministic tests."""

    def __init__(self, initial_time: datetime | int) -> None:
        self._current_ns = self._coerce_initial_time(initial_time)
        self._sequence = 0
        self._heap: list[tuple[int, int, str]] = []
        self._timers: dict[OnlyTimerId, OnlyTimer] = {}
        self._failures: list[OnlyTimerFailure] = []
        self._state = OnlyClockState.RUNNING

    @property
    def state(self) -> OnlyClockState:
        return self._state

    @property
    def failures(self) -> tuple[OnlyTimerFailure, ...]:
        return tuple(self._failures)

    def now_utc(self) -> datetime:
        return only_unix_ns_to_datetime_utc(self._current_ns, allow_truncation=True)

    def timestamp_ns(self) -> int:
        return self._current_ns

    def monotonic_ns(self) -> int:
        return self._current_ns

    def schedule_at(self, timer_id: OnlyTimerId | str, when_ns: int, callback: OnlyTimerCallback) -> OnlyTimerHandle:
        return self._schedule(timer_id, when_ns, callback, OnlyTimerMode.ONE_SHOT, None)

    def schedule_after(
        self, timer_id: OnlyTimerId | str, delay_ns: int, callback: OnlyTimerCallback
    ) -> OnlyTimerHandle:
        if delay_ns < 0:
            raise OnlyValidationError("timer delay cannot be negative")
        return self.schedule_at(timer_id, self._current_ns + delay_ns, callback)

    def schedule_every(
        self,
        timer_id: OnlyTimerId | str,
        interval_ns: int,
        callback: OnlyTimerCallback,
        *,
        start_ns: int | None = None,
    ) -> OnlyTimerHandle:
        if interval_ns <= 0:
            raise OnlyValidationError("timer interval must be positive")
        deadline = self._current_ns + interval_ns if start_ns is None else start_ns
        return self._schedule(timer_id, deadline, callback, OnlyTimerMode.FIXED_RATE, interval_ns)

    def cancel_timer(self, timer_id: OnlyTimerId | str) -> bool:
        timer = self._timers.get(self._coerce_timer_id(timer_id))
        if timer is None or timer.state not in {OnlyTimerState.SCHEDULED, OnlyTimerState.FIRING}:
            return False
        timer.state = OnlyTimerState.CANCELLED
        return True

    def has_timer(self, timer_id: OnlyTimerId | str) -> bool:
        timer = self._timers.get(self._coerce_timer_id(timer_id))
        return timer is not None and timer.state in {OnlyTimerState.SCHEDULED, OnlyTimerState.FIRING}

    def advance_to(self, timestamp: datetime | int) -> OnlyTimeAdvanceResult:
        self._require_open()
        target_ns = self._coerce_advance_time(timestamp)
        if target_ns < self._current_ns:
            raise OnlyValidationError("virtual clock cannot move backwards")
        previous_ns = self._current_ns
        fired: list[OnlyTimerEvent] = []
        failure_start = len(self._failures)
        while self._heap and self._heap[0][0] <= target_ns:
            deadline_ns, _, timer_value = heapq.heappop(self._heap)
            timer = self._timers[OnlyTimerId(timer_value)]
            if timer.state is not OnlyTimerState.SCHEDULED or timer.next_deadline_ns != deadline_ns:
                continue
            self._current_ns = deadline_ns
            event = self._fire_timer(timer)
            fired.append(event)
        self._current_ns = target_ns
        return OnlyTimeAdvanceResult(
            previous_ns,
            target_ns,
            tuple(fired),
            tuple(self._failures[failure_start:]),
        )

    def advance_by(self, delta_ns: int) -> OnlyTimeAdvanceResult:
        if delta_ns < 0:
            raise OnlyValidationError("advance delta cannot be negative")
        return self.advance_to(self._current_ns + delta_ns)

    def set_time(self, timestamp: datetime | int) -> OnlyTimeAdvanceResult:
        return self.advance_to(timestamp)

    def snapshot(self) -> OnlyClockSnapshot:
        active = tuple(
            self._snapshot_timer(timer.timer_id)
            for timer in sorted(self._timers.values(), key=lambda item: (item.next_deadline_ns, item.sequence))
            if timer.state in {OnlyTimerState.SCHEDULED, OnlyTimerState.FIRING}
        )
        return OnlyClockSnapshot(self._current_ns, self._sequence, active)

    def restore(self, snapshot: OnlyClockSnapshot) -> None:
        """Restore a time-only snapshot; callbacks intentionally cannot be restored."""
        self._require_open()
        if snapshot.active_timers or any(self.has_timer(timer_id) for timer_id in self._timers):
            raise OnlyClockError("snapshots with active callbacks cannot be restored")
        self._current_ns = snapshot.current_timestamp_ns
        self._sequence = snapshot.sequence

    def timer_snapshot(self, timer_id: OnlyTimerId | str) -> OnlyTimerSnapshot:
        return self._snapshot_timer(self._coerce_timer_id(timer_id))

    def close(self) -> None:
        if self._state is OnlyClockState.CLOSED:
            return
        self._state = OnlyClockState.CLOSING
        for timer in self._timers.values():
            if timer.state in {OnlyTimerState.SCHEDULED, OnlyTimerState.FIRING}:
                timer.state = OnlyTimerState.CANCELLED
        self._heap.clear()
        self._state = OnlyClockState.CLOSED

    def _schedule(
        self,
        timer_id: OnlyTimerId | str,
        deadline_ns: int,
        callback: OnlyTimerCallback,
        mode: OnlyTimerMode,
        interval_ns: int | None,
    ) -> OnlyTimerHandle:
        self._require_open()
        identifier = self._coerce_timer_id(timer_id)
        if identifier in self._timers:
            raise OnlyDuplicateTimerError(f"timer_id already used: {identifier}")
        if isinstance(deadline_ns, bool) or not isinstance(deadline_ns, int):
            raise OnlyValidationError("timer deadline must be Unix nanoseconds")
        if deadline_ns < self._current_ns:
            raise OnlyValidationError("timer deadline cannot precede current time")
        self._sequence += 1
        timer = OnlyTimer(
            identifier,
            mode,
            self._current_ns,
            deadline_ns,
            interval_ns,
            self._sequence,
            callback,
        )
        self._timers[identifier] = timer
        heapq.heappush(self._heap, (deadline_ns, timer.sequence, identifier.value))
        return OnlyTimerHandle(identifier, self.cancel_timer, self._snapshot_timer)

    def _fire_timer(self, timer: OnlyTimer) -> OnlyTimerEvent:
        timer.state = OnlyTimerState.FIRING
        timer.fire_count += 1
        event = OnlyTimerEvent(
            timer.timer_id,
            timer.next_deadline_ns,
            self._current_ns,
            timer.sequence,
            timer.fire_count,
        )
        try:
            timer.callback(event)
        except Exception as exc:
            timer.state = OnlyTimerState.FAILED
            self._failures.append(OnlyTimerFailure(event, exc))
            return event
        if timer.state is OnlyTimerState.CANCELLED:
            return event
        if timer.mode is OnlyTimerMode.ONE_SHOT:
            timer.state = OnlyTimerState.COMPLETED
            return event
        if timer.mode is not OnlyTimerMode.FIXED_RATE or timer.interval_ns is None:
            timer.state = OnlyTimerState.FAILED
            failure = OnlyClockError("virtual clocks do not support FIXED_DELAY")
            self._failures.append(OnlyTimerFailure(event, failure))
            return event
        timer.next_deadline_ns += timer.interval_ns
        timer.state = OnlyTimerState.SCHEDULED
        heapq.heappush(self._heap, (timer.next_deadline_ns, timer.sequence, timer.timer_id.value))
        return event

    def _snapshot_timer(self, timer_id: OnlyTimerId) -> OnlyTimerSnapshot:
        try:
            timer = self._timers[timer_id]
        except KeyError as exc:
            raise OnlyClockError(f"unknown timer_id: {timer_id}") from exc
        return OnlyTimerSnapshot(
            timer.timer_id,
            timer.mode,
            timer.created_at_ns,
            timer.next_deadline_ns,
            timer.interval_ns,
            timer.sequence,
            timer.state,
            timer.fire_count,
            MappingProxyType(dict(timer.metadata)),
        )

    def _require_open(self) -> None:
        if self._state is not OnlyClockState.RUNNING:
            raise OnlyClockError("Clock is closed")

    @staticmethod
    def _coerce_timer_id(timer_id: OnlyTimerId | str) -> OnlyTimerId:
        return timer_id if isinstance(timer_id, OnlyTimerId) else OnlyTimerId(timer_id)

    @staticmethod
    def _coerce_initial_time(value: datetime | int) -> int:
        if isinstance(value, datetime):
            normalized = only_ensure_utc_aware(value, field_name="initial_time")
            if normalized != value or value.utcoffset() != normalized.utcoffset():
                raise OnlyValidationError("initial_time must be UTC")
            return only_datetime_to_unix_ns(value)
        if isinstance(value, bool) or not isinstance(value, int):
            raise OnlyValidationError("initial_time must be UTC datetime or Unix nanoseconds")
        return value

    @classmethod
    def _coerce_advance_time(cls, value: datetime | int) -> int:
        return cls._coerce_initial_time(value)


class OnlyBacktestClock(OnlyVirtualClock):
    """History-event-driven Clock; only its owning Backtest Runtime may advance it."""


class OnlyLiveClock(OnlyClock):
    """Thread-safe system UTC Clock with one monotonic scheduler thread."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.Lock())
        self._sequence = 0
        self._heap: list[tuple[int, int, str]] = []
        self._timers: dict[OnlyTimerId, OnlyTimer] = {}
        self._failures: list[OnlyTimerFailure] = []
        self._state = OnlyClockState.RUNNING
        self._thread = threading.Thread(target=self._run_scheduler, name="onlyalpha-clock", daemon=True)
        self._thread.start()

    @property
    def state(self) -> OnlyClockState:
        with self._condition:
            return self._state

    @property
    def failures(self) -> tuple[OnlyTimerFailure, ...]:
        with self._condition:
            return tuple(self._failures)

    def now_utc(self) -> datetime:
        return only_unix_ns_to_datetime_utc(time.time_ns(), allow_truncation=True)

    def timestamp_ns(self) -> int:
        return time.time_ns()

    def monotonic_ns(self) -> int:
        return time.monotonic_ns()

    def schedule_at(self, timer_id: OnlyTimerId | str, when_ns: int, callback: OnlyTimerCallback) -> OnlyTimerHandle:
        return self._schedule(timer_id, when_ns, callback, OnlyTimerMode.ONE_SHOT, None)

    def schedule_after(
        self, timer_id: OnlyTimerId | str, delay_ns: int, callback: OnlyTimerCallback
    ) -> OnlyTimerHandle:
        if delay_ns < 0:
            raise OnlyValidationError("timer delay cannot be negative")
        return self._schedule(
            timer_id,
            self.timestamp_ns() + delay_ns,
            callback,
            OnlyTimerMode.ONE_SHOT,
            None,
            allow_elapsed=True,
        )

    def schedule_every(
        self,
        timer_id: OnlyTimerId | str,
        interval_ns: int,
        callback: OnlyTimerCallback,
        *,
        start_ns: int | None = None,
    ) -> OnlyTimerHandle:
        if interval_ns <= 0:
            raise OnlyValidationError("timer interval must be positive")
        deadline = self.timestamp_ns() + interval_ns if start_ns is None else start_ns
        return self._schedule(
            timer_id,
            deadline,
            callback,
            OnlyTimerMode.FIXED_RATE,
            interval_ns,
            allow_elapsed=start_ns is None,
        )

    def cancel_timer(self, timer_id: OnlyTimerId | str) -> bool:
        identifier = OnlyVirtualClock._coerce_timer_id(timer_id)
        with self._condition:
            timer = self._timers.get(identifier)
            if timer is None or timer.state not in {OnlyTimerState.SCHEDULED, OnlyTimerState.FIRING}:
                return False
            timer.state = OnlyTimerState.CANCELLED
            self._condition.notify()
            return True

    def has_timer(self, timer_id: OnlyTimerId | str) -> bool:
        identifier = OnlyVirtualClock._coerce_timer_id(timer_id)
        with self._condition:
            timer = self._timers.get(identifier)
            return timer is not None and timer.state in {OnlyTimerState.SCHEDULED, OnlyTimerState.FIRING}

    def timer_snapshot(self, timer_id: OnlyTimerId | str) -> OnlyTimerSnapshot:
        with self._condition:
            return self._snapshot_timer(OnlyVirtualClock._coerce_timer_id(timer_id))

    def close(self) -> None:
        with self._condition:
            if self._state is OnlyClockState.CLOSED:
                return
            self._state = OnlyClockState.CLOSING
            for timer in self._timers.values():
                if timer.state in {OnlyTimerState.SCHEDULED, OnlyTimerState.FIRING}:
                    timer.state = OnlyTimerState.CANCELLED
            self._heap.clear()
            self._condition.notify_all()
        if threading.current_thread() is not self._thread:
            self._thread.join()
        with self._condition:
            self._state = OnlyClockState.CLOSED

    def _schedule(
        self,
        timer_id: OnlyTimerId | str,
        deadline_ns: int,
        callback: OnlyTimerCallback,
        mode: OnlyTimerMode,
        interval_ns: int | None,
        *,
        allow_elapsed: bool = False,
    ) -> OnlyTimerHandle:
        identifier = OnlyVirtualClock._coerce_timer_id(timer_id)
        if isinstance(deadline_ns, bool) or not isinstance(deadline_ns, int):
            raise OnlyValidationError("timer deadline must be Unix nanoseconds")
        with self._condition:
            if self._state is not OnlyClockState.RUNNING:
                raise OnlyClockError("Clock is closed")
            if identifier in self._timers:
                raise OnlyDuplicateTimerError(f"timer_id already used: {identifier}")
            wall_now = self.timestamp_ns()
            monotonic_now = self.monotonic_ns()
            if deadline_ns < wall_now and not allow_elapsed:
                raise OnlyValidationError("timer deadline cannot precede current time")
            self._sequence += 1
            monotonic_deadline = monotonic_now + max(0, deadline_ns - wall_now)
            timer = OnlyTimer(
                identifier,
                mode,
                wall_now,
                deadline_ns,
                interval_ns,
                self._sequence,
                callback,
                monotonic_deadline_ns=monotonic_deadline,
            )
            self._timers[identifier] = timer
            heapq.heappush(self._heap, (deadline_ns, timer.sequence, identifier.value))
            self._condition.notify()
        return OnlyTimerHandle(identifier, self.cancel_timer, self.timer_snapshot)

    def _run_scheduler(self) -> None:
        while True:
            with self._condition:
                timer = self._take_due_timer_locked()
                if timer is None:
                    if self._state is not OnlyClockState.RUNNING:
                        self._state = OnlyClockState.CLOSED
                        self._condition.notify_all()
                        return
                    continue
            self._fire_live_timer(timer)

    def _take_due_timer_locked(self) -> OnlyTimer | None:
        while self._state is OnlyClockState.RUNNING:
            while self._heap:
                deadline_ns, _, timer_value = self._heap[0]
                timer = self._timers[OnlyTimerId(timer_value)]
                if timer.state is not OnlyTimerState.SCHEDULED or timer.next_deadline_ns != deadline_ns:
                    heapq.heappop(self._heap)
                    continue
                assert timer.monotonic_deadline_ns is not None
                remaining_ns = timer.monotonic_deadline_ns - self.monotonic_ns()
                if remaining_ns > 0:
                    self._condition.wait(remaining_ns / 1_000_000_000)
                    break
                heapq.heappop(self._heap)
                timer.state = OnlyTimerState.FIRING
                return timer
            else:
                self._condition.wait()
        return None

    def _fire_live_timer(self, timer: OnlyTimer) -> None:
        timer.fire_count += 1
        fired_at = self.timestamp_ns()
        event = OnlyTimerEvent(timer.timer_id, timer.next_deadline_ns, fired_at, timer.sequence, timer.fire_count)
        try:
            timer.callback(event)
        except Exception as exc:
            with self._condition:
                timer.state = OnlyTimerState.FAILED
                self._failures.append(OnlyTimerFailure(event, exc))
            _LOGGER.exception("timer callback failed: %s", timer.timer_id, exc_info=exc)
            return
        with self._condition:
            if timer.state is OnlyTimerState.CANCELLED or self._state is not OnlyClockState.RUNNING:
                timer.state = OnlyTimerState.CANCELLED
                return
            if timer.mode is OnlyTimerMode.ONE_SHOT:
                timer.state = OnlyTimerState.COMPLETED
                return
            if timer.interval_ns is None:
                timer.state = OnlyTimerState.FAILED
                return
            timer.next_deadline_ns += timer.interval_ns
            assert timer.monotonic_deadline_ns is not None
            timer.monotonic_deadline_ns += timer.interval_ns
            timer.state = OnlyTimerState.SCHEDULED
            heapq.heappush(
                self._heap,
                (timer.next_deadline_ns, timer.sequence, timer.timer_id.value),
            )
            self._condition.notify()

    def _snapshot_timer(self, timer_id: OnlyTimerId) -> OnlyTimerSnapshot:
        try:
            timer = self._timers[timer_id]
        except KeyError as exc:
            raise OnlyClockError(f"unknown timer_id: {timer_id}") from exc
        return OnlyTimerSnapshot(
            timer.timer_id,
            timer.mode,
            timer.created_at_ns,
            timer.next_deadline_ns,
            timer.interval_ns,
            timer.sequence,
            timer.state,
            timer.fire_count,
            MappingProxyType(dict(timer.metadata)),
        )
