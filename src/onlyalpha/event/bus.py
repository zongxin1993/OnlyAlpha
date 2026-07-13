"""Bounded, synchronous event bus for the first project phase."""

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock

from onlyalpha.core.errors import OnlyLifecycleError
from onlyalpha.event.model import OnlyEvent

type OnlyEventHandler = Callable[[OnlyEvent], None]


@dataclass(frozen=True, slots=True)
class OnlyEventFailure:
    """Captured handler failure for observation without silent swallowing."""

    event: OnlyEvent
    handler_name: str
    error: Exception


class OnlyEventBus:
    """FIFO event dispatcher with an explicit capacity and failure channel."""

    def __init__(self, capacity: int = 1024) -> None:
        if capacity <= 0:
            raise ValueError("event bus capacity must be positive")
        self._capacity = capacity
        self._queue: deque[OnlyEvent] = deque()
        self._handlers: dict[str, list[OnlyEventHandler]] = defaultdict(list)
        self._failures: list[OnlyEventFailure] = []
        self._accepting = True
        self._lock = RLock()

    @property
    def failures(self) -> tuple[OnlyEventFailure, ...]:
        return tuple(self._failures)

    def subscribe(self, event_type: str, handler: OnlyEventHandler) -> None:
        with self._lock:
            self._handlers[event_type].append(handler)

    def publish(self, event: OnlyEvent) -> None:
        with self._lock:
            if not self._accepting:
                raise OnlyLifecycleError("event bus is closed")
            if len(self._queue) >= self._capacity:
                raise OnlyLifecycleError("event bus capacity exceeded")
            self._queue.append(event)

    def drain(self) -> int:
        handled = 0
        while True:
            with self._lock:
                if not self._queue:
                    return handled
                event = self._queue.popleft()
                handlers = tuple(self._handlers.get(event.event_type, ()))
            for handler in handlers:
                try:
                    handler(event)
                except Exception as exc:
                    name = getattr(handler, "__qualname__", repr(handler))
                    self._failures.append(OnlyEventFailure(event, name, exc))
            handled += 1

    def close(self) -> None:
        with self._lock:
            self._accepting = False
        self.drain()
