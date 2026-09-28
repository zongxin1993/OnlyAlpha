from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from onlyalpha.core.clock import OnlyVirtualClock
from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataVersion
from onlyalpha.data.models import OnlyHistoricalDataRange
from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyEngineId, OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.market import (
    OnlyBarSemantic,
    OnlyBarType,
    OnlyTickCountBarFormation,
    OnlyTradeInputType,
    OnlyTradeSemantic,
    OnlyTradeTick,
)
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.indicator.pipeline import OnlyIndicatorPipeline
from onlyalpha.market_data.aggregation.base import OnlyBarAggregationError
from onlyalpha.market_data.aggregation.manager import OnlyBarAggregationManager
from onlyalpha.market_data.cache import OnlyMarketDataCache
from onlyalpha.market_data.pipeline import OnlyMarketDataPipeline, OnlyMarketDataPipelineError
from onlyalpha.market_data.resolution import (
    OnlyBarConstructionAlgorithmRegistry,
    OnlyBarConstructionRecipe,
    OnlyMarketDataConstructionEdge,
    OnlyMarketDataConstructionGraph,
)
from onlyalpha.runtime.backtest.input_requirements import only_historical_market_data_input_plan
from onlyalpha.runtime.streaming.requirements import (
    only_compose_runtime_market_data_requirements,
    only_project_construction_provider_requirement,
    only_project_data_source_capabilities,
)


def _time_edge(source: OnlyBarType, target: OnlyBarType) -> OnlyMarketDataConstructionEdge:
    return OnlyMarketDataConstructionEdge(
        source,
        target,
        OnlyBarConstructionRecipe.derived(target.semantic, source.semantic, algorithm_id="TIME_BAR"),
    )


def _dag(bar_1m: OnlyBarType, bar_5m: OnlyBarType, bar_15m: OnlyBarType, bar_7m: OnlyBarType | None = None):
    edges = [_time_edge(bar_1m, bar_5m), _time_edge(bar_5m, bar_15m)]
    if bar_7m is not None:
        edges.append(_time_edge(bar_1m, bar_7m))
    return OnlyMarketDataConstructionGraph((bar_1m,), tuple(edges))


def _manager(shanghai_calendar, graph, *, registry=None, source="source"):
    manager = OnlyBarAggregationManager(
        shanghai_calendar,
        OnlyVirtualClock(datetime(2026, 1, 5, 7, 0, tzinfo=UTC)),
        registry,
        source_binding_identity=source,
    )
    manager.register_graph(graph)
    return manager


def test_two_level_dag_executes_to_fixpoint(shanghai_calendar, bar_1m, bar_5m, bar_15m, make_bar) -> None:
    manager = _manager(shanghai_calendar, _dag(bar_1m, bar_5m, bar_15m))
    outputs = [item for minute in range(15) for item in manager.process(make_bar(minute))]
    assert [item.bar_type for item in outputs].count(bar_5m) == 3
    assert [item.bar_type for item in outputs].count(bar_15m) == 1
    assert manager.compiled_plan.topological_levels[0] == tuple(
        lane.lane_id for lane in manager.compiled_plan.provider_input_lanes
    )
    assert tuple(len(level) for level in manager.compiled_plan.topological_levels) == (1, 1, 1)


def test_branch_dag_and_registration_order_are_deterministic(
    shanghai_calendar, bar_1m, bar_5m, bar_15m, make_bar
) -> None:
    bar_7m = OnlyBarType(bar_1m.instrument_id, OnlyBarSemantic.fixed_duration(7))
    graph = _dag(bar_1m, bar_5m, bar_15m, bar_7m)
    reversed_graph = OnlyMarketDataConstructionGraph(graph.provider_inputs, tuple(reversed(graph.derived_dependencies)))
    first = _manager(shanghai_calendar, graph)
    second = _manager(shanghai_calendar, reversed_graph)
    first_outputs = [first.process(make_bar(minute)) for minute in range(15)]
    second_outputs = [second.process(make_bar(minute)) for minute in range(15)]
    assert first_outputs == second_outputs
    assert graph.fingerprint == reversed_graph.fingerprint
    assert first.capture_checkpoint() == second.capture_checkpoint()


def test_routing_is_keyed_by_lane_not_bar_type(shanghai_calendar, bar_1m, bar_5m, bar_15m) -> None:
    manager = _manager(shanghai_calendar, _dag(bar_1m, bar_5m, bar_15m))
    provider_lane = manager.compiled_plan.provider_input_lanes[0]
    first, second = manager.compiled_plan.construction_lanes
    assert tuple(manager.compiled_plan.outgoing_by_lane) == (provider_lane.lane_id, first.lane_id)
    assert first.source_lane_id == provider_lane.lane_id
    assert second.source_lane_id == first.lane_id


class _Executor:
    def __init__(self, edge, *, accepts=True, fails=False):
        self.target_bar_type = edge.target
        self._accepts = accepts
        self._fails = fails
        self._count = 0

    def accepts(self, fact):
        return self._accepts

    def process(self, fact):
        if self._fails:
            raise RuntimeError("downstream failed")
        self._count += 1
        return (replace(fact, bar_type=self.target_bar_type),)

    def capture_checkpoint(self):
        return {"count": self._count}

    def restore_checkpoint(self, payload):
        self._count = int(payload["count"])


def _test_graph(bar_1m, bar_3m, bar_5m):
    first = OnlyMarketDataConstructionEdge(
        bar_1m,
        bar_3m,
        OnlyBarConstructionRecipe.derived(bar_3m.semantic, bar_1m.semantic, algorithm_id="TEST_PASS"),
    )
    second = OnlyMarketDataConstructionEdge(
        bar_3m,
        bar_5m,
        OnlyBarConstructionRecipe.derived(bar_5m.semantic, bar_3m.semantic, algorithm_id="TEST_FAIL"),
    )
    return OnlyMarketDataConstructionGraph((bar_1m,), (first, second))


def _test_registry(*, first_accepts=True):
    registry = OnlyBarConstructionAlgorithmRegistry()
    registry.register_factory("TEST_PASS", 1, "BAR", "BAR", lambda edge, *_: _Executor(edge, accepts=first_accepts))
    registry.register_factory("TEST_FAIL", 1, "BAR", "BAR", lambda edge, *_: _Executor(edge, fails=True))
    return registry


def test_executor_accepts_is_contract_validation(shanghai_calendar, bar_1m, bar_3m, bar_5m, make_bar) -> None:
    manager = _manager(
        shanghai_calendar,
        _test_graph(bar_1m, bar_3m, bar_5m),
        registry=_test_registry(first_accepts=False),
    )
    with pytest.raises(OnlyBarAggregationError, match="INPUT_CONTRACT_VIOLATION"):
        manager.process(make_bar(0))
    with pytest.raises(OnlyBarAggregationError, match="RECOVERY_REQUIRED"):
        manager.process(make_bar(1))


def test_downstream_failure_exposes_no_partial_pipeline_commit(
    shanghai_calendar, bar_1m, bar_3m, bar_5m, make_bar
) -> None:
    manager = _manager(
        shanghai_calendar,
        _test_graph(bar_1m, bar_3m, bar_5m),
        registry=_test_registry(),
    )
    cache = OnlyMarketDataCache()
    pipeline = OnlyMarketDataPipeline(
        OnlyEngineId("engine"),
        OnlyRuntimeId("runtime"),
        OnlyVirtualClock(datetime(2026, 1, 5, 7, 0, tzinfo=UTC)),
        cache,
        manager,
        OnlyIndicatorPipeline(),
    )
    with pytest.raises(OnlyMarketDataPipelineError, match="downstream failed"):
        pipeline.process_bar(make_bar(0))
    assert cache.latest_all() == {}
    with pytest.raises(OnlyBarAggregationError, match="RECOVERY_REQUIRED"):
        manager.process(make_bar(1))


def test_trade_construction_failure_exposes_no_partial_cache(shanghai_calendar, bar_1m) -> None:
    source = OnlyTradeInputType(bar_1m.instrument_id)
    target = OnlyBarType(bar_1m.instrument_id, OnlyBarSemantic(OnlyTickCountBarFormation(1)))
    edge = OnlyMarketDataConstructionEdge(
        source,
        target,
        OnlyBarConstructionRecipe.derived(target.semantic, OnlyTradeSemantic(), algorithm_id="TEST_FAIL"),
    )
    registry = OnlyBarConstructionAlgorithmRegistry()
    registry.register_factory("TEST_FAIL", 1, "TRADE", "BAR", lambda item, *_: _Executor(item, fails=True))
    manager = _manager(
        shanghai_calendar,
        OnlyMarketDataConstructionGraph((source,), (edge,)),
        registry=registry,
    )
    cache = OnlyMarketDataCache()
    pipeline = OnlyMarketDataPipeline(
        OnlyEngineId("engine"),
        OnlyRuntimeId("runtime"),
        OnlyVirtualClock(datetime(2026, 1, 5, 7, 0, tzinfo=UTC)),
        cache,
        manager,
        OnlyIndicatorPipeline(),
    )
    now = datetime(2026, 1, 5, 1, 30, tzinfo=UTC)
    trade = OnlyTradeTick(
        bar_1m.instrument_id,
        now,
        now,
        1,
        "TEST",
        OnlyPrice(Decimal("10"), 2),
        OnlyQuantity(Decimal("1"), 0),
        OnlyOrderSide.BUY,
        OnlyTradeId("trade-failure"),
    )

    with pytest.raises(OnlyMarketDataPipelineError, match="downstream failed"):
        pipeline.process_trade(trade)
    assert cache.latest_all() == {}
    with pytest.raises(OnlyBarAggregationError, match="RECOVERY_REQUIRED"):
        manager.process(trade)


def test_checkpoint_restart_equals_uninterrupted(shanghai_calendar, bar_1m, bar_5m, bar_15m, make_bar) -> None:
    graph = _dag(bar_1m, bar_5m, bar_15m)
    uninterrupted = _manager(shanghai_calendar, graph)
    expected = [item for minute in range(15) for item in uninterrupted.process(make_bar(minute))]

    first = _manager(shanghai_calendar, graph)
    actual = [item for minute in range(8) for item in first.process(make_bar(minute))]
    checkpoint = first.capture_checkpoint()
    resumed = _manager(shanghai_calendar, graph)
    resumed.restore_checkpoint(checkpoint)
    actual.extend(item for minute in range(8, 15) for item in resumed.process(make_bar(minute)))
    assert actual == expected
    assert resumed.capture_checkpoint() == uninterrupted.capture_checkpoint()
    with pytest.raises(ValueError, match="REBUILD_REQUIRED"):
        resumed.restore_checkpoint({"schema_version": 2})


def test_trade_provider_root_executes_registered_executor(shanghai_calendar, bar_1m, make_bar) -> None:
    source = OnlyTradeInputType(bar_1m.instrument_id)
    target = OnlyBarType(bar_1m.instrument_id, OnlyBarSemantic(OnlyTickCountBarFormation(1)))
    edge = OnlyMarketDataConstructionEdge(
        source,
        target,
        OnlyBarConstructionRecipe.derived(target.semantic, OnlyTradeSemantic(), algorithm_id="TICK_BAR"),
    )

    class TickExecutor(_Executor):
        def process(self, fact):
            self._count += 1
            return (replace(make_bar(0), bar_type=target),)

    registry = OnlyBarConstructionAlgorithmRegistry()
    registry.register_factory("TICK_BAR", 1, "TRADE", "BAR", lambda compiled_edge, *_: TickExecutor(compiled_edge))
    manager = _manager(
        shanghai_calendar,
        OnlyMarketDataConstructionGraph((source,), (edge,)),
        registry=registry,
    )
    now = datetime(2026, 1, 5, 1, 30, tzinfo=UTC)
    trade = OnlyTradeTick(
        bar_1m.instrument_id,
        now,
        now,
        1,
        "TEST",
        OnlyPrice(Decimal("10"), 2),
        OnlyQuantity(Decimal("1"), 0),
        OnlyOrderSide.BUY,
        OnlyTradeId("trade-1"),
    )
    assert tuple(item.bar_type for item in manager.process(trade)) == (target,)


def test_bar_and_trade_provider_inputs_project_to_sim_and_backtest_requests(bar_1m) -> None:
    trade = OnlyTradeInputType(bar_1m.instrument_id)
    graph = OnlyMarketDataConstructionGraph((bar_1m, trade), ())
    realtime = only_project_construction_provider_requirement(graph)
    assert realtime.data_types == frozenset({OnlyMarketDataType.BAR, OnlyMarketDataType.TRADE})
    assert realtime.bar_types == frozenset({bar_1m})
    capabilities = only_project_data_source_capabilities(
        only_compose_runtime_market_data_requirements(realtime), historical=True
    )
    assert capabilities.historical_bars and capabilities.historical_ticks

    plan = only_historical_market_data_input_plan(
        OnlyRuntimeId("runtime"),
        graph,
        OnlyHistoricalDataRange(datetime(2026, 1, 5, tzinfo=UTC), datetime(2026, 1, 6, tzinfo=UTC)),
        OnlyDataVersion("v1"),
        batch_size=10,
    )
    assert plan.bar_requests[0].bar_types == frozenset({bar_1m})
    assert plan.trade_requests[0].instrument_ids == frozenset({bar_1m.instrument_id})
