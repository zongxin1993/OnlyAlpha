from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.core.clock import OnlyClockView, OnlyLiveClock, OnlyVirtualClock
from onlyalpha.domain.identifiers import OnlyEngineId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.event.model import OnlyEvent
from onlyalpha.indicator.base import (
    OnlyBarIndicator,
    OnlyIndicatorId,
    OnlyIndicatorRegistration,
    OnlyIndicatorRequirement,
    OnlyIndicatorValue,
)
from onlyalpha.indicator.identifiers import OnlyIndicatorTypeId
from onlyalpha.indicator.pipeline import OnlyIndicatorPipeline
from onlyalpha.indicator.snapshot import OnlyWarmupProgress
from onlyalpha.market_data.aggregation.manager import OnlyBarAggregationManager
from onlyalpha.market_data.cache import OnlyMarketDataCache
from onlyalpha.market_data.dispatcher import OnlyClusterBarSubscription, OnlyStrategyBarDispatcher
from onlyalpha.market_data.pipeline import OnlyMarketDataPipeline, OnlyMarketDataPipelineError
from onlyalpha.market_data.snapshot import OnlyMarketDataSnapshot, OnlyMarketDataSnapshotError
from onlyalpha.market_data.subscriptions import OnlyBarSubscription
from onlyalpha.strategy.base import OnlyStrategy
from onlyalpha.strategy.config import OnlyStrategyConfig
from onlyalpha.strategy.context import OnlyStrategyBarContext
from onlyalpha.strategy.identifiers import OnlyStrategyId


class OnlyRecordingStrategy(OnlyStrategy):
    def __init__(self, cluster_id: str, order: list[str] | None = None) -> None:
        super().__init__(OnlyStrategyConfig(OnlyStrategyId(f"{cluster_id}-strategy")))
        self.calls: list[tuple[OnlyBar, OnlyMarketDataSnapshot]] = []
        self._order = order

    def on_initialize(self) -> None:
        pass

    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        bar = context.primary_bar
        assert isinstance(bar, OnlyBar)
        if self._order is not None:
            self._order.append(f"strategy:{self.strategy_id}")
        assert isinstance(context.snapshot, OnlyMarketDataSnapshot)
        self.calls.append((bar, context.snapshot))


class OnlyFailingStrategy(OnlyRecordingStrategy):
    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        raise RuntimeError("strategy failed")


class OnlyRecordingCluster(OnlyCluster):
    def __init__(self, cluster_id: str, order: list[str] | None = None, *, failing: bool = False) -> None:
        strategy_type = OnlyFailingStrategy if failing else OnlyRecordingStrategy
        strategy = strategy_type(cluster_id, order)
        super().__init__(OnlyClusterConfig(cluster_id), strategy)
        self.recording_strategy = strategy

    @property
    def calls(self) -> list[tuple[OnlyBar, OnlyMarketDataSnapshot]]:
        return self.recording_strategy.calls


class OnlyCloseIndicator(OnlyBarIndicator):
    def __init__(self, indicator_id: str, bar_type: OnlyBarType, order: list[str] | None = None) -> None:
        self._indicator_id = OnlyIndicatorId(indicator_id)
        self._bar_type = bar_type
        self._order = order
        self._value = None

    @property
    def indicator_id(self) -> OnlyIndicatorId:
        return self._indicator_id

    @property
    def bar_type(self) -> OnlyBarType:
        return self._bar_type

    @property
    def indicator_type(self) -> OnlyIndicatorTypeId:
        return OnlyIndicatorTypeId("test.close")

    @property
    def ready(self) -> bool:
        return self._value is not None

    @property
    def warmup_progress(self) -> OnlyWarmupProgress:
        return OnlyWarmupProgress(int(self.ready), 1)

    def reset(self) -> None:
        self._value = None

    def snapshot(self) -> OnlyIndicatorValue:
        return self._value

    def update_bar(self, bar: OnlyBar) -> None:
        if self._order is not None:
            self._order.append(f"indicator:{self.indicator_id}")
        self._value = bar.close.value


class OnlyFailingIndicator(OnlyCloseIndicator):
    def update_bar(self, bar: OnlyBar) -> None:
        raise RuntimeError("indicator failed")


def _system(shanghai_calendar, subscriptions, registrations=()):
    clock = OnlyVirtualClock(datetime(2026, 1, 5, 7, 0, tzinfo=UTC))
    manager = OnlyBarAggregationManager(shanghai_calendar, clock)
    indicators = OnlyIndicatorPipeline()
    for registration in registrations:
        indicators.register(registration)
    pipeline = OnlyMarketDataPipeline(
        OnlyEngineId("engine"),
        OnlyRuntimeId("runtime"),
        clock,
        OnlyMarketDataCache(),
        manager,
        indicators,
    )
    dispatcher = OnlyStrategyBarDispatcher(pipeline, OnlyClockView(clock))
    for item in subscriptions:
        dispatcher.register(item)
    return pipeline, dispatcher, manager


def test_default_1m_primary_calls_three_times_and_third_snapshot_is_ready(
    shanghai_calendar, bar_1m, bar_3m, make_bar
) -> None:
    cluster = OnlyRecordingCluster("cluster-a")
    subscription = OnlyBarSubscription((bar_1m, bar_3m))
    pipeline, dispatcher, _ = _system(
        shanghai_calendar,
        (OnlyClusterBarSubscription(cluster, subscription),),
    )
    updates = []
    for minute in range(3):
        update = pipeline.process_bar(make_bar(minute))
        updates.append(update)
        dispatcher.dispatch(update)
    assert len(cluster.calls) == 3
    assert updates[0].updated_bar_types == frozenset({bar_1m})
    third = cluster.calls[-1][1]
    assert third.updated_bar_types == frozenset({bar_1m, bar_3m})
    assert third.latest_closed(bar_3m).bar_end == make_bar(2).bar_end  # type: ignore[union-attr]


def test_external_daily_bar_runs_through_pipeline_and_dispatches(shanghai_calendar, bar_1m, make_bar) -> None:
    daily_bar_type = replace(
        bar_1m,
        specification=replace(bar_1m.specification, step=1440),
    )
    cluster = OnlyRecordingCluster("daily")
    pipeline, dispatcher, manager = _system(
        shanghai_calendar,
        (OnlyClusterBarSubscription(cluster, OnlyBarSubscription((daily_bar_type,))),),
    )
    minute_bar = make_bar(0)
    daily_bar = replace(
        minute_bar,
        bar_type=daily_bar_type,
        bar_end=minute_bar.bar_start + timedelta(hours=5, minutes=30),
        ts_event=minute_bar.bar_start + timedelta(hours=5, minutes=30),
        ts_init=minute_bar.bar_start + timedelta(hours=5, minutes=30),
    )

    update = pipeline.process_bar(daily_bar)
    dispatcher.dispatch(update)

    assert update.base_bar == daily_bar
    assert update.derived_bars == ()
    assert manager.aggregator_count == 0
    assert len(cluster.calls) == 1
    assert cluster.calls[0][0] == daily_bar
    assert cluster.calls[0][1].primary_bar == daily_bar


def test_explicit_3m_primary_calls_once_with_latest_1m(shanghai_calendar, bar_1m, bar_3m, make_bar) -> None:
    cluster = OnlyRecordingCluster("cluster-b")
    subscription = OnlyBarSubscription((bar_1m, bar_3m), primary_bar_type=bar_3m)
    pipeline, dispatcher, _ = _system(
        shanghai_calendar,
        (OnlyClusterBarSubscription(cluster, subscription),),
    )
    for minute in range(3):
        dispatcher.dispatch(pipeline.process_bar(make_bar(minute)))
    assert len(cluster.calls) == 1
    primary, snapshot = cluster.calls[0]
    assert primary.bar_type == bar_3m
    assert snapshot.latest_closed(bar_1m) == make_bar(2)


def test_multiple_clusters_share_aggregation_and_use_different_primary_periods(
    shanghai_calendar, bar_1m, bar_3m, make_bar
) -> None:
    cluster_a = OnlyRecordingCluster("a")
    cluster_b = OnlyRecordingCluster("b")
    pipeline, dispatcher, manager = _system(
        shanghai_calendar,
        (
            OnlyClusterBarSubscription(cluster_a, OnlyBarSubscription((bar_1m, bar_3m))),
            OnlyClusterBarSubscription(
                cluster_b,
                OnlyBarSubscription((bar_1m, bar_3m), primary_bar_type=bar_3m),
            ),
        ),
    )
    for minute in range(3):
        dispatcher.dispatch(pipeline.process_bar(make_bar(minute)))
    assert len(cluster_a.calls) == 3
    assert len(cluster_b.calls) == 1
    assert manager.creation_count == 1


def test_all_derived_bars_and_required_indicator_finish_before_one_callback(
    shanghai_calendar, bar_1m, bar_3m, bar_5m, bar_15m, make_bar
) -> None:
    order: list[str] = []
    cluster = OnlyRecordingCluster("cluster", order)
    indicator = OnlyCloseIndicator("close-15m", bar_15m, order)
    registration = OnlyIndicatorRegistration(indicator, OnlyIndicatorRequirement.REQUIRED)
    subscription = OnlyBarSubscription((bar_1m, bar_3m, bar_5m, bar_15m))
    pipeline, dispatcher, _ = _system(
        shanghai_calendar,
        (OnlyClusterBarSubscription(cluster, subscription),),
        (registration,),
    )
    final_update = None
    for minute in range(15):
        final_update = pipeline.process_bar(make_bar(minute))
        dispatcher.dispatch(final_update)
    assert final_update is not None
    assert final_update.updated_bar_types == frozenset({bar_1m, bar_3m, bar_5m, bar_15m})
    assert order[-2:] == ["indicator:close-15m", "strategy:cluster-strategy"]
    assert final_update.updated_indicator_ids == (indicator.indicator_id,)
    assert cluster.calls[-1][1].indicator_values == {}
    assert len(cluster.calls) == 15


def test_required_indicator_failure_blocks_dispatch(shanghai_calendar, bar_1m, make_bar) -> None:
    cluster = OnlyRecordingCluster("required")
    indicator = OnlyFailingIndicator("required-fail", bar_1m)
    pipeline, dispatcher, _ = _system(
        shanghai_calendar,
        (OnlyClusterBarSubscription(cluster, OnlyBarSubscription((bar_1m,))),),
        (OnlyIndicatorRegistration(indicator, OnlyIndicatorRequirement.REQUIRED),),
    )
    with pytest.raises(OnlyMarketDataPipelineError, match="required indicator"):
        pipeline.process_bar(make_bar(0))
    assert cluster.calls == []
    assert len(pipeline.failure_facts) == 1
    _ = dispatcher


def test_optional_indicator_failure_is_flagged_but_dispatch_continues(shanghai_calendar, bar_1m, make_bar) -> None:
    cluster = OnlyRecordingCluster("optional")
    indicator = OnlyFailingIndicator("optional-fail", bar_1m)
    pipeline, dispatcher, _ = _system(
        shanghai_calendar,
        (OnlyClusterBarSubscription(cluster, OnlyBarSubscription((bar_1m,))),),
        (OnlyIndicatorRegistration(indicator, OnlyIndicatorRequirement.OPTIONAL),),
    )
    update = pipeline.process_bar(make_bar(0))
    dispatcher.dispatch(update)
    assert len(cluster.calls) == 1
    assert update.snapshot.quality_flags == ("OPTIONAL_INDICATOR_MISSING:optional-fail",)


def test_snapshot_is_immutable_closed_only_and_same_time_is_explicit(
    shanghai_calendar, bar_1m, bar_3m, make_bar
) -> None:
    cluster = OnlyRecordingCluster("snapshot")
    pipeline, dispatcher, _ = _system(
        shanghai_calendar,
        (OnlyClusterBarSubscription(cluster, OnlyBarSubscription((bar_1m, bar_3m))),),
    )
    first = pipeline.process_bar(make_bar(0))
    dispatcher.dispatch(first)
    snapshot = cluster.calls[0][1]
    assert snapshot.current_partial(bar_3m) is None
    assert snapshot.latest_closed(bar_3m) is None
    with pytest.raises(OnlyMarketDataSnapshotError, match="no closed"):
        snapshot.require_same_event_time(bar_3m)
    with pytest.raises(TypeError):
        snapshot.bars.latest_closed_bars[bar_1m] = make_bar(1)  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        snapshot.primary_bar = make_bar(1)  # type: ignore[misc]


def test_duplicate_and_late_bars_are_rejected(shanghai_calendar, bar_1m, make_bar) -> None:
    cluster = OnlyRecordingCluster("sequence")
    pipeline, _, _ = _system(
        shanghai_calendar,
        (OnlyClusterBarSubscription(cluster, OnlyBarSubscription((bar_1m,))),),
    )
    pipeline.process_bar(make_bar(1))
    with pytest.raises(OnlyMarketDataPipelineError, match="duplicate"):
        pipeline.process_bar(make_bar(1))
    with pytest.raises(OnlyMarketDataPipelineError, match="late"):
        pipeline.process_bar(make_bar(0))


def test_snapshot_update_result_and_input_events_replay_deterministically(
    shanghai_calendar, bar_1m, bar_3m, make_bar
) -> None:
    serialized_events = [
        OnlyEvent(
            "BAR_RECEIVED",
            make_bar(minute).bar_end,
            "engine",
            "runtime",
            "fixture",
            minute,
            payload=make_bar(minute),
            ts_init=datetime(2026, 1, 5, 7, 0, tzinfo=UTC),
        ).to_dict()
        for minute in range(3)
    ]

    def replay() -> tuple[list[dict[str, object]], int]:
        cluster = OnlyRecordingCluster("replay")
        pipeline, dispatcher, _ = _system(
            shanghai_calendar,
            (OnlyClusterBarSubscription(cluster, OnlyBarSubscription((bar_1m, bar_3m))),),
        )
        snapshots = []
        for payload in serialized_events:
            event = OnlyEvent.from_dict(payload)
            assert isinstance(event.payload, OnlyBar)
            update = pipeline.process_bar(event.payload)
            dispatcher.dispatch(update)
            snapshots.append(update.snapshot.to_dict())
            assert type(update).from_dict(update.to_dict()).to_dict() == update.to_dict()
        return snapshots, len(cluster.calls)

    assert replay() == replay()


def test_cluster_failure_is_isolated_from_other_cluster(shanghai_calendar, bar_1m, make_bar) -> None:
    failing = OnlyRecordingCluster("a-failing", failing=True)
    healthy = OnlyRecordingCluster("b-healthy")
    subscription = OnlyBarSubscription((bar_1m,))
    pipeline, dispatcher, _ = _system(
        shanghai_calendar,
        (
            OnlyClusterBarSubscription(failing, subscription),
            OnlyClusterBarSubscription(healthy, subscription),
        ),
    )
    results = dispatcher.dispatch(pipeline.process_bar(make_bar(0)))
    assert [(str(item.cluster_id), item.succeeded) for item in results] == [
        ("a-failing", False),
        ("b-healthy", True),
    ]
    assert len(healthy.calls) == 1


def test_same_cluster_cannot_dispatch_same_time_slice_twice(shanghai_calendar, bar_1m, make_bar) -> None:
    cluster = OnlyRecordingCluster("once")
    pipeline, dispatcher, _ = _system(
        shanghai_calendar,
        (OnlyClusterBarSubscription(cluster, OnlyBarSubscription((bar_1m,))),),
    )
    update = pipeline.process_bar(make_bar(0))
    dispatcher.dispatch(update)
    with pytest.raises(ValueError, match="already handled"):
        dispatcher.dispatch(update)


def test_runtime_pipeline_instances_do_not_share_mutable_aggregation(
    shanghai_calendar, bar_1m, bar_3m, make_bar
) -> None:
    cluster_a = OnlyRecordingCluster("a")
    cluster_b = OnlyRecordingCluster("b")
    subscription = OnlyBarSubscription((bar_1m, bar_3m), primary_bar_type=bar_3m)
    pipeline_a, dispatcher_a, manager_a = _system(
        shanghai_calendar,
        (OnlyClusterBarSubscription(cluster_a, subscription),),
    )
    pipeline_b, dispatcher_b, manager_b = _system(
        shanghai_calendar,
        (OnlyClusterBarSubscription(cluster_b, subscription),),
    )
    assert manager_a is not manager_b
    for minute in range(3):
        dispatcher_a.dispatch(pipeline_a.process_bar(make_bar(minute)))
    assert len(cluster_a.calls) == 1
    assert cluster_b.calls == []
    for minute in range(3):
        dispatcher_b.dispatch(pipeline_b.process_bar(make_bar(minute)))
    assert cluster_a.calls[0][0] == cluster_b.calls[0][0]


def test_live_and_backtest_clocks_use_same_data_preparation_semantics(
    shanghai_calendar, bar_1m, bar_3m, make_bar
) -> None:
    def execute(clock) -> tuple[list[tuple[str, ...]], int]:
        manager = OnlyBarAggregationManager(shanghai_calendar, clock)
        pipeline = OnlyMarketDataPipeline(
            OnlyEngineId("engine"),
            OnlyRuntimeId("runtime"),
            clock,
            OnlyMarketDataCache(),
            manager,
            OnlyIndicatorPipeline(),
        )
        cluster = OnlyRecordingCluster("cluster")
        dispatcher = OnlyStrategyBarDispatcher(pipeline, OnlyClockView(clock))
        dispatcher.register(OnlyClusterBarSubscription(cluster, OnlyBarSubscription((bar_1m, bar_3m))))
        updated = []
        for minute in range(3):
            result = pipeline.process_bar(make_bar(minute))
            updated.append(tuple(sorted(str(item.specification.step) for item in result.updated_bar_types)))
            dispatcher.dispatch(result)
        return updated, len(cluster.calls)

    backtest_semantics = execute(OnlyVirtualClock(datetime(2026, 1, 5, 7, 0, tzinfo=UTC)))
    live_clock = OnlyLiveClock()
    try:
        live_semantics = execute(live_clock)
    finally:
        live_clock.close()
    assert live_semantics == backtest_semantics
