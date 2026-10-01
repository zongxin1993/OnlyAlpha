"""Deterministic dequeue ownership cuts; watchdogs only bound deadlock failures."""

from threading import Event, Thread
from unittest.mock import Mock

import pytest

from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.enums import OnlyMarketDataBackpressurePolicy
from onlyalpha.data.queue import OnlyMarketDataInboundQueue, OnlyMarketDataQueueFullError
from onlyalpha.runtime.streaming.live_bar import OnlyLiveBarFinalizer
from onlyalpha.runtime.streaming.semantic_lane import OnlyStreamingSemanticLane
from onlyalpha.runtime.streaming.worker import OnlyStreamingMarketDataWorker
from tests.runtime.test_streaming_live_bar import _update


def _worker(queue, make_runtime_bar):
    return OnlyStreamingMarketDataWorker(
        queue,
        OnlyStreamingSemanticLane(Mock()),
        OnlyLiveBarFinalizer(),
        OnlyBacktestClock(make_runtime_bar(2).bar_end),
        commit_result=lambda update, result: None,
        shutdown_timeout_seconds=2,
    )


def test_external_owner_acknowledges_inflight_boundary_and_resumes_exactly_once(make_runtime_bar, monkeypatch):
    queue = OnlyMarketDataInboundQueue(4)
    first, second = (_update(make_runtime_bar(i), i + 1) for i in range(2))
    queue.put(first)
    worker = _worker(queue, make_runtime_bar)
    entered, finish, owned, release, processed = (Event() for _ in range(5))
    applied = []
    errors = []

    def process(update):
        if update == first:
            entered.set()
            assert finish.wait(2)
        applied.append(update)
        if update == second:
            processed.set()

    def recover():
        try:
            assert worker.acquire_recovery_ingress()
            assert applied == [first]
            owned.set()
            assert release.wait(2)
            worker.release_recovery_ingress(resume_live=True)
        except BaseException as exc:
            errors.append(exc)
            owned.set()

    monkeypatch.setattr(worker, "_process_update", process)
    thread = Thread(target=recover)
    worker.start()
    try:
        assert entered.wait(2)
        thread.start()
        with worker._ingress:
            assert worker._ingress.wait_for(lambda: worker._ingress_owner is not None, timeout=2)
            assert not owned.is_set()
        finish.set()
        assert owned.wait(2)
        assert errors == []
        assert worker.recovery_ingress_owned
        queue.put(second)
        assert len(queue) == 1
        assert applied == [first]
        release.set()
        assert processed.wait(2)
        thread.join(2)
        assert not thread.is_alive()
        assert errors == []
        assert applied == [first, second]
        assert len(queue) == 0
    finally:
        finish.set()
        release.set()
        worker.stop()
        if thread.ident is not None:
            thread.join(2)


def test_worker_idle_owner_is_reentrant_and_terminal_release_preserves_queue(make_runtime_bar, monkeypatch):
    queue = OnlyMarketDataInboundQueue(4)
    suffix = _update(make_runtime_bar(1), 2)
    worker = _worker(queue, make_runtime_bar)
    finished = Event()

    def idle():
        assert worker.acquire_recovery_ingress()
        assert worker.acquire_recovery_ingress()
        assert worker.recovery_ingress_owned
        queue.put(suffix)
        worker.release_recovery_ingress(resume_live=True)
        assert worker.recovery_ingress_owned
        worker.release_recovery_ingress(resume_live=False)
        finished.set()

    monkeypatch.setattr(worker, "_on_idle", idle)
    worker.start()
    try:
        assert finished.wait(2)
        assert worker.recovery_ingress_failed
        assert worker.alive
        assert not worker.stop_requested
        assert len(queue) == 1
        assert not worker.acquire_recovery_ingress()
    finally:
        worker.stop()
    assert worker.failure is None
    assert not worker.alive
    assert queue.get() == suffix


def test_stop_interrupts_acknowledgment_wait_without_consuming_suffix(make_runtime_bar, monkeypatch):
    queue = OnlyMarketDataInboundQueue(4)
    first, suffix = (_update(make_runtime_bar(i), i + 1) for i in range(2))
    queue.put(first)
    queue.put(suffix)
    worker = _worker(queue, make_runtime_bar)
    entered, finish, stopped = Event(), Event(), Event()
    results = []

    def process(update):
        assert update == first
        entered.set()
        assert finish.wait(2)

    def acquire():
        results.append(worker.acquire_recovery_ingress())
        stopped.set()

    monkeypatch.setattr(worker, "_process_update", process)
    thread = Thread(target=acquire)
    worker.start()
    try:
        assert entered.wait(2)
        thread.start()
        with worker._ingress:
            assert worker._ingress.wait_for(lambda: worker._ingress_owner is not None, timeout=2)
        worker.request_stop()
        assert stopped.wait(2)
        assert results == [False]
        assert not worker.recovery_ingress_owned
    finally:
        finish.set()
        worker.stop()
        if thread.ident is not None:
            thread.join(2)
    assert not thread.is_alive()
    assert queue.get() == suffix


@pytest.mark.parametrize(
    "policy", [OnlyMarketDataBackpressurePolicy.REJECT_NEW, OnlyMarketDataBackpressurePolicy.FAIL_RUNTIME]
)
def test_quiesced_queue_keeps_lossless_backpressure_and_stop_unblocks_waiter(make_runtime_bar, policy):
    queue = OnlyMarketDataInboundQueue(1, policy)
    suffix = _update(make_runtime_bar(1), 2)
    worker = _worker(queue, make_runtime_bar)
    assert worker.acquire_recovery_ingress()
    worker.start()
    queue.put(suffix)
    with pytest.raises(OnlyMarketDataQueueFullError, match="no data was dropped"):
        queue.put(_update(make_runtime_bar(2), 3))
    entered, done = Event(), Event()
    results = []

    def wait_owner():
        entered.set()
        results.append(worker.acquire_recovery_ingress())
        done.set()

    thread = Thread(target=wait_owner)
    thread.start()
    try:
        assert entered.wait(2)
        worker.stop()
        assert done.wait(2)
        thread.join(2)
        assert not thread.is_alive()
        assert results == [False]
        assert not worker.alive
        assert queue.get() == suffix
    finally:
        worker.request_stop()
        worker.release_recovery_ingress(resume_live=False)
        thread.join(2)
