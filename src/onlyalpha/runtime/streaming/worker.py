"""Single-consumer streaming market-data worker."""

from collections.abc import Callable
from threading import Event, Thread
from time import monotonic

from onlyalpha.core.clock import OnlyClock
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate, OnlyMarketDataProcessingResult
from onlyalpha.data.processor import OnlyMarketDataProcessor
from onlyalpha.data.queue import OnlyMarketDataInboundQueue

from .live_bar import OnlyLiveBarFinalizer


class OnlyStreamingMarketDataWorker:
    _JOIN_TIMEOUT_SECONDS = 5.0

    def __init__(
        self,
        queue: OnlyMarketDataInboundQueue,
        processor: OnlyMarketDataProcessor,
        finalizer: OnlyLiveBarFinalizer,
        clock: OnlyClock,
        *,
        maximum_future_wait_seconds: float = 10.0,
        on_result: Callable[[OnlyMarketDataProcessingResult], None] | None = None,
        accept_update: Callable[[OnlyMarketDataInboundUpdate], bool] | None = None,
        accept_finalized: Callable[[OnlyMarketDataInboundUpdate], bool] | None = None,
    ) -> None:
        self._queue = queue
        self._processor = processor
        self._finalizer = finalizer
        self._clock = clock
        self._maximum_future_wait_seconds = maximum_future_wait_seconds
        self._on_result = on_result or (lambda result: None)
        self._accept_update = accept_update or (lambda update: True)
        self._accept_finalized = accept_finalized or (lambda update: True)
        self._stop = Event()
        self._thread: Thread | None = None
        self._failure: BaseException | None = None
        self._stop_attempted = False

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def failure(self) -> BaseException | None:
        return self._failure

    def start(self) -> None:
        if self._stop_attempted:
            raise RuntimeError("streaming market-data worker cannot restart after stop")
        if self.alive:
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="onlyalpha-streaming-market-data", daemon=False)
        self._thread.start()

    def stop(self) -> None:
        if self._stop_attempted:
            return
        self._stop_attempted = True
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self._JOIN_TIMEOUT_SECONDS)
            if thread.is_alive():
                raise RuntimeError(
                    "streaming market-data worker did not stop: "
                    f"operation=join timeout_seconds={self._JOIN_TIMEOUT_SECONDS}"
                )

    def _run(self) -> None:
        try:
            while not self._stop.wait(0.01):
                update = self._queue.get()
                if update is None:
                    continue
                if not self._accept_update(update):
                    continue
                for finalized in self._finalizer.accept(update):
                    if not self._accept_finalized(finalized):
                        continue
                    if not self._await_event_time(finalized):
                        continue
                    self._on_result(self._processor.process(finalized))
            while (update := self._queue.get()) is not None:
                if not self._accept_update(update):
                    continue
                for finalized in self._finalizer.accept(update):
                    if not self._accept_finalized(finalized):
                        continue
                    if not self._await_event_time(finalized):
                        continue
                    self._on_result(self._processor.process(finalized))
        except BaseException as exc:
            self._failure = exc
            self._stop.set()

    def _await_event_time(self, update: OnlyMarketDataInboundUpdate) -> bool:
        if not isinstance(update.payload, OnlyBarUpdate):
            return True
        bar = update.payload.bar
        bar_duration = (bar.bar_end - bar.bar_start).total_seconds()
        deadline = monotonic() + max(self._maximum_future_wait_seconds, bar_duration + 5.0)
        while update.ts_event.unix_nanos > self._clock.timestamp_ns():
            if self._stop.is_set():
                return False
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    "live Bar event time remains ahead of Runtime Clock: "
                    f"event_ns={update.ts_event.unix_nanos} clock_ns={self._clock.timestamp_ns()}"
                )
            self._stop.wait(min(remaining, 0.01))
        return True
