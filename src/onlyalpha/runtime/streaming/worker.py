"""Single-consumer streaming market-data worker."""

from collections.abc import Callable
from threading import Condition, Event, Thread, get_ident
from time import monotonic

from onlyalpha.core.clock import OnlyClock
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate, OnlyMarketDataProcessingResult
from onlyalpha.data.queue import OnlyMarketDataInboundQueue

from .live_bar import OnlyLiveBarFinalizer
from .semantic_lane import OnlyStreamingProcessingCommit, OnlyStreamingSemanticLane


class OnlyStreamingMarketDataWorker:
    def __init__(
        self,
        queue: OnlyMarketDataInboundQueue,
        processing_lane: OnlyStreamingSemanticLane,
        finalizer: OnlyLiveBarFinalizer,
        clock: OnlyClock,
        *,
        maximum_future_wait_seconds: float = 10.0,
        shutdown_timeout_seconds: float = 35.0,
        commit_result: OnlyStreamingProcessingCommit,
        on_processed: Callable[[OnlyMarketDataInboundUpdate, OnlyMarketDataProcessingResult], None] | None = None,
        on_idle: Callable[[], None] | None = None,
        accept_update: Callable[[OnlyMarketDataInboundUpdate], bool] | None = None,
        accept_finalized: Callable[[OnlyMarketDataInboundUpdate], bool] | None = None,
    ) -> None:
        self._queue = queue
        self._processing_lane = processing_lane
        self._finalizer = finalizer
        self._clock = clock
        self._maximum_future_wait_seconds = maximum_future_wait_seconds
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._commit_result = commit_result
        self._on_processed = on_processed or (lambda update, result: None)
        self._on_idle = on_idle or (lambda: None)
        self._accept_update = accept_update or (lambda update: True)
        self._accept_finalized = accept_finalized or (lambda update: True)
        self._stop = Event()
        self._thread: Thread | None = None
        self._failure: BaseException | None = None
        self._stop_attempted = False
        self._ingress = Condition()
        self._ingress_owner: int | None = None
        self._ownership_depth = 0
        self._dequeue_active = False
        self._recovery_ingress_failed = False

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def failure(self) -> BaseException | None:
        return self._failure

    def start(self) -> None:
        if self._stop_attempted or self._recovery_ingress_failed:
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
        self.request_stop()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self._shutdown_timeout_seconds)
            if thread.is_alive():
                raise RuntimeError(
                    "streaming market-data worker did not stop: "
                    f"operation=join timeout_seconds={self._shutdown_timeout_seconds}"
                )

    def request_stop(self) -> None:
        with self._ingress:
            self._stop.set()
            self._ingress.notify_all()

    def acquire_recovery_ingress(self) -> bool:
        """Acknowledge the complete current update/callback before transferring dequeue."""
        caller = get_ident()
        worker_caller = self._thread is not None and self._thread.ident == caller
        deadline = monotonic() + self._shutdown_timeout_seconds
        with self._ingress:
            if self._ingress_owner == caller:
                self._ownership_depth += 1
                return True
            while self._ingress_owner is not None:
                # An external caller is waiting for this callback to finish.
                # The worker must defer its own recovery, never wait on itself.
                if worker_caller or self._stop.is_set():
                    return False
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise RuntimeError("streaming recovery ingress ownership watchdog expired")
                self._ingress.wait(remaining)
            if self._stop.is_set() or self._recovery_ingress_failed:
                return False
            self._ingress_owner = caller
            self._ownership_depth = 1
            self._ingress.notify_all()
            while self._dequeue_active and not worker_caller:
                if self._stop.is_set():
                    self._ingress_owner = None
                    self._ownership_depth = 0
                    self._ingress.notify_all()
                    return False
                remaining = deadline - monotonic()
                if remaining <= 0:
                    self.request_stop()
                    self._ingress_owner = None
                    self._ownership_depth = 0
                    raise RuntimeError("streaming recovery ingress quiescence watchdog expired")
                self._ingress.wait(remaining)
            return True

    def release_recovery_ingress(self, *, resume_live: bool) -> None:
        with self._ingress:
            if self._ingress_owner != get_ident():
                raise RuntimeError("streaming recovery ingress released by non-owner")
            if not resume_live:
                self._recovery_ingress_failed = True
            self._ownership_depth -= 1
            if self._ownership_depth == 0:
                self._ingress_owner = None
            self._ingress.notify_all()

    @property
    def recovery_ingress_owned(self) -> bool:
        with self._ingress:
            return self._ingress_owner is not None and (
                not self._dequeue_active or (self._thread is not None and self._thread.ident == self._ingress_owner)
            )

    @property
    def recovery_ingress_failed(self) -> bool:
        with self._ingress:
            return self._recovery_ingress_failed

    def _run(self) -> None:
        try:
            while not self._stop.wait(0.01):
                with self._ingress:
                    while (
                        self._ingress_owner is not None or self._recovery_ingress_failed
                    ) and not self._stop.is_set():
                        self._ingress.wait()
                    if self._stop.is_set():
                        return
                    self._dequeue_active = True
                try:
                    update = self._queue.get()
                    if update is None:
                        self._on_idle()
                    else:
                        self._process_update(update)
                finally:
                    with self._ingress:
                        self._dequeue_active = False
                        self._ingress.notify_all()
        except BaseException as exc:
            self._failure = exc
            self.request_stop()

    def _process_update(self, update: OnlyMarketDataInboundUpdate) -> None:
        if self._stop.is_set() or not self._accept_update(update) or self._stop.is_set():
            return
        for finalized in self._finalizer.accept(update):
            if self._stop.is_set():
                return
            if not self._accept_finalized(finalized):
                continue
            if self._stop.is_set() or not self._await_event_time(finalized):
                return
            outcome = self._processing_lane.process(finalized, self._commit_result)
            if not outcome.started or outcome.result is None:
                return
            self._on_processed(finalized, outcome.result)

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()

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
