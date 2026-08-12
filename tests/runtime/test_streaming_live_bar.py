from dataclasses import replace
from threading import Event, Thread
from time import monotonic, sleep
from unittest.mock import Mock

import pytest

from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.identifiers import (
    OnlyDataSequence,
    OnlyDataVersion,
    OnlyMarketDataSourceId,
    OnlyMarketDataUpdateId,
)
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate
from onlyalpha.data.queue import OnlyMarketDataInboundQueue
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.runtime.streaming.live_bar import OnlyLiveBarFinalizationError, OnlyLiveBarFinalizer
from onlyalpha.runtime.streaming.semantic_lane import OnlyStreamingSemanticLane
from onlyalpha.runtime.streaming.worker import OnlyStreamingMarketDataWorker


def _update(bar, sequence: int) -> OnlyMarketDataInboundUpdate:
    updating = replace(bar, ts_event=bar.bar_start, ts_init=bar.bar_start, is_closed=False)
    stamp = OnlyTimestamp.from_datetime(updating.ts_event)
    return OnlyMarketDataInboundUpdate(
        OnlyMarketDataUpdateId(f"live-{sequence}"),
        OnlyRuntimeId("paper"),
        OnlyMarketDataSourceId("miniqmt-live"),
        OnlyDataSequence(sequence),
        OnlyDataVersion("live-v1"),
        updating.instrument_id,
        OnlyMarketDataType.BAR,
        OnlyBarUpdate(updating),
        stamp,
        stamp,
    )


def test_same_live_period_replaces_pending_and_next_period_finalizes_once(make_runtime_bar) -> None:
    finalizer = OnlyLiveBarFinalizer()
    first = _update(make_runtime_bar(0), 1)
    revised = _update(replace(make_runtime_bar(0), close=make_runtime_bar(0).high), 2)
    next_period = _update(make_runtime_bar(1), 3)

    assert finalizer.accept(first) == ()
    assert finalizer.accept(revised) == ()
    finalized = finalizer.accept(next_period)

    assert len(finalized) == 1
    closed = finalized[0].payload.bar
    assert closed.is_closed
    assert closed.close == revised.payload.bar.close
    assert closed.ts_event == closed.bar_end
    assert int(finalized[0].source_sequence) == 1
    assert finalizer.pending_count == 1


def test_repeated_raw_revisions_produce_contiguous_closed_sequences(make_runtime_bar) -> None:
    finalizer = OnlyLiveBarFinalizer()
    assert finalizer.accept(_update(make_runtime_bar(0), 11)) == ()
    assert finalizer.accept(_update(make_runtime_bar(0), 12)) == ()
    first = finalizer.accept(_update(make_runtime_bar(1), 18))
    assert finalizer.accept(_update(make_runtime_bar(1), 19)) == ()
    second = finalizer.accept(_update(make_runtime_bar(2), 25))

    assert [int(item.source_sequence) for item in first + second] == [1, 2]


def test_out_of_order_live_period_fails_closed(make_runtime_bar) -> None:
    finalizer = OnlyLiveBarFinalizer()
    assert finalizer.accept(_update(make_runtime_bar(1), 1)) == ()
    with pytest.raises(OnlyLiveBarFinalizationError, match="out-of-order"):
        finalizer.accept(_update(make_runtime_bar(0), 2))


def test_stop_does_not_fabricate_the_last_pending_bar(make_runtime_bar) -> None:
    queue = OnlyMarketDataInboundQueue(4)
    queue.put(_update(make_runtime_bar(0), 1))
    processor = Mock()
    finalizer = OnlyLiveBarFinalizer()
    worker = OnlyStreamingMarketDataWorker(
        queue,
        OnlyStreamingSemanticLane(processor),
        finalizer,
        OnlyBacktestClock(make_runtime_bar(0).bar_end),
        commit_result=lambda update, result: None,
    )

    worker.start()
    deadline = monotonic() + 1
    while finalizer.pending_count == 0 and monotonic() < deadline:
        sleep(0.01)
    worker.stop()

    assert finalizer.pending_count == 1
    processor.process.assert_not_called()


def test_worker_stop_does_not_drain_queued_updates(make_runtime_bar) -> None:
    queue = OnlyMarketDataInboundQueue(4)
    queue.put(_update(make_runtime_bar(0), 1))
    queue.put(_update(make_runtime_bar(1), 2))
    processor = Mock()
    accepting = Event()
    release = Event()

    def accept_update(update: OnlyMarketDataInboundUpdate) -> bool:
        del update
        accepting.set()
        release.wait(1)
        return True

    worker = OnlyStreamingMarketDataWorker(
        queue,
        OnlyStreamingSemanticLane(processor),
        OnlyLiveBarFinalizer(),
        OnlyBacktestClock(make_runtime_bar(1).bar_end),
        commit_result=lambda update, result: None,
        accept_update=accept_update,
    )

    worker.start()
    assert accepting.wait(1)
    releaser = Thread(target=lambda: (sleep(0.02), release.set()))
    releaser.start()
    worker.stop()
    releaser.join()

    assert len(queue) == 1
    processor.process.assert_not_called()


def test_worker_stop_prevents_processing_after_acceptance_boundary(make_runtime_bar) -> None:
    bar = make_runtime_bar(0)
    stamp = OnlyTimestamp.from_datetime(bar.ts_event)
    update = replace(
        _update(bar, 1),
        payload=OnlyBarUpdate(bar),
        ts_event=stamp,
        ts_init=stamp,
    )
    queue = OnlyMarketDataInboundQueue(4)
    queue.put(update)
    processor = Mock()
    accepting = Event()
    release = Event()

    def accept_update(item: OnlyMarketDataInboundUpdate) -> bool:
        del item
        accepting.set()
        release.wait(1)
        return True

    worker = OnlyStreamingMarketDataWorker(
        queue,
        OnlyStreamingSemanticLane(processor),
        OnlyLiveBarFinalizer(),
        OnlyBacktestClock(bar.ts_event),
        commit_result=lambda update, result: None,
        accept_update=accept_update,
    )

    worker.start()
    assert accepting.wait(1)
    releaser = Thread(target=lambda: (sleep(0.02), release.set()))
    releaser.start()
    worker.stop()
    releaser.join()

    processor.process.assert_not_called()


def test_worker_stop_interrupts_wait_for_future_bar(make_runtime_bar) -> None:
    queue = OnlyMarketDataInboundQueue(4)
    queue.put(_update(make_runtime_bar(0), 1))
    queue.put(_update(make_runtime_bar(1), 2))
    processor = Mock()
    worker = OnlyStreamingMarketDataWorker(
        queue,
        OnlyStreamingSemanticLane(processor),
        OnlyLiveBarFinalizer(),
        OnlyBacktestClock(0),
        commit_result=lambda update, result: None,
    )

    worker.start()
    deadline = monotonic() + 1
    while len(queue) and monotonic() < deadline:
        sleep(0.01)
    worker.request_stop()
    worker.stop()
    worker.stop()

    assert not worker.alive
    assert worker.failure is None
    processor.process.assert_not_called()
