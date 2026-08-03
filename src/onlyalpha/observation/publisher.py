"""Non-blocking bounded publication of canonical observation snapshots."""

from collections import deque
from collections.abc import Iterable
from threading import Condition, Thread
from typing import Protocol

from .models import OnlyMarketObservationSnapshot


class OnlyObservationSink(Protocol):
    def publish(self, snapshot: OnlyMarketObservationSnapshot) -> None: ...


class OnlyCompositeObservationSink:
    def __init__(self, sinks: Iterable[OnlyObservationSink]) -> None:
        self._sinks = tuple(sinks)

    def publish(self, snapshot: OnlyMarketObservationSnapshot) -> None:
        for sink in self._sinks:
            sink.publish(snapshot)


class OnlyObservationPublisher:
    def __init__(self, sink: OnlyObservationSink, capacity: int = 1024) -> None:
        if capacity <= 0:
            raise ValueError("observation queue capacity must be positive")
        self._sink = sink
        self._capacity = capacity
        self._queue: deque[OnlyMarketObservationSnapshot] = deque()
        self._condition = Condition()
        self._thread: Thread | None = None
        self._stopping = False
        self._drop_count = 0
        self._failure: BaseException | None = None

    @property
    def queue_size(self) -> int:
        with self._condition:
            return len(self._queue)

    @property
    def drop_count(self) -> int:
        with self._condition:
            return self._drop_count

    @property
    def failure(self) -> BaseException | None:
        return self._failure

    def start(self) -> None:
        with self._condition:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stopping = False
            self._thread = Thread(target=self._run, name="onlyalpha-observation-publisher", daemon=False)
            self._thread.start()

    def publish(self, snapshot: OnlyMarketObservationSnapshot) -> None:
        with self._condition:
            if len(self._queue) >= self._capacity:
                self._queue.popleft()
                self._drop_count += 1
            self._queue.append(snapshot)
            self._condition.notify()

    def stop(self) -> None:
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError("observation publisher did not stop")

    def _run(self) -> None:
        try:
            while True:
                with self._condition:
                    while not self._queue and not self._stopping:
                        self._condition.wait()
                    if not self._queue and self._stopping:
                        return
                    snapshot = self._queue.popleft()
                self._sink.publish(snapshot)
        except BaseException as exc:
            self._failure = exc
