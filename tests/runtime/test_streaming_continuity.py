from dataclasses import replace

import pytest

from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyDataVersion, OnlyMarketDataSourceId, OnlyMarketDataUpdateId
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.runtime.streaming.continuity import OnlyStreamingContinuityTracker

pytestmark = [pytest.mark.unit, pytest.mark.sim_recovery]


def _update(bar, sequence: int) -> OnlyMarketDataInboundUpdate:  # type: ignore[no-untyped-def]
    stamp = OnlyTimestamp.from_datetime(bar.ts_event)
    return OnlyMarketDataInboundUpdate(
        OnlyMarketDataUpdateId(f"update-{sequence}"),
        OnlyRuntimeId("runtime"),
        OnlyMarketDataSourceId("source"),
        OnlyDataSequence(sequence),
        OnlyDataVersion("version"),
        bar.instrument_id,
        OnlyMarketDataType.BAR,
        OnlyBarUpdate(bar),
        stamp,
        stamp,
        metadata=(("provider_sequence", str(100 + sequence)),),
    )


def test_continuity_frontier_is_monotonic_and_dedup_is_bounded(make_runtime_bar) -> None:
    tracker = OnlyStreamingContinuityTracker(dedup_capacity=2)
    updates = tuple(_update(make_runtime_bar(index), index + 1) for index in range(3))
    for update in updates:
        assert not tracker.contains(update)
        tracker.advance(update)

    assert len(tracker._recent) == 2  # type: ignore[attr-defined]
    assert tracker.last_closed_bar_end == OnlyTimestamp.from_datetime(updates[-1].payload.bar.bar_end)
    assert tracker.accepted_sequence(updates[-1].source_id, OnlyMarketDataType.BAR) == 3
    assert tracker.contains(updates[-1])
    with pytest.raises(ValueError, match="NOT_MONOTONIC"):
        tracker.advance(updates[-1])


def test_continuity_checkpoint_round_trip_excludes_partial_bar(make_runtime_bar) -> None:
    original = OnlyStreamingContinuityTracker(dedup_capacity=3)
    closed = _update(make_runtime_bar(0), 1)
    partial_bar = replace(make_runtime_bar(1), is_closed=False, ts_event=make_runtime_bar(1).bar_start)
    partial = _update(partial_bar, 2)
    original.advance(closed)
    with pytest.raises(ValueError, match="closed Bars"):
        original.advance(partial)

    restored = OnlyStreamingContinuityTracker()
    restored.restore_checkpoint(original.capture_checkpoint())
    assert restored.frontiers == original.frontiers
    assert restored.capture_checkpoint() == original.capture_checkpoint()
    assert "pending" not in str(original.capture_checkpoint()).lower()
