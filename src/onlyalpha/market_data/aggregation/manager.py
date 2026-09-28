"""Lane-aware deterministic execution of a Runtime construction DAG."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from onlyalpha.canonical import only_canonical_json
from onlyalpha.core.clock import OnlyClock
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.market import OnlyBar, OnlyTradeInputType, OnlyTradeTick
from onlyalpha.market_data.aggregation.base import (
    OnlyBarAggregationError,
    OnlyMarketDataConstructionExecutor,
)
from onlyalpha.market_data.aggregation.compiler import (
    OnlyCompiledConstructionPlan,
    OnlyConstructionGraphCompiler,
)
from onlyalpha.market_data.resolution import (
    OnlyBarConstructionAlgorithmRegistry,
    OnlyMarketDataConstructionEdge,
    OnlyMarketDataConstructionGraph,
    OnlyMarketDataConstructionLane,
    OnlyMarketDataInputType,
)
from onlyalpha.market_data.subscriptions import OnlyBarSubscription


@dataclass(frozen=True, slots=True)
class _OnlyConstructionWorkItem:
    source_lane_id: str
    fact: object


class OnlyBarAggregationManager:
    """One mutable executor state per construction lane in a Runtime."""

    def __init__(
        self,
        calendar: OnlyTradingCalendar,
        clock: OnlyClock,
        algorithm_registry: OnlyBarConstructionAlgorithmRegistry | None = None,
        source_binding_identity: str = "LOCAL_RUNTIME_SOURCE",
    ) -> None:
        self._calendar = calendar
        self._clock = clock
        self._source_binding_identity = source_binding_identity
        self._executors: dict[str, OnlyMarketDataConstructionExecutor] = {}
        self._reference_counts: dict[str, int] = {}
        self._provider_reference_counts: dict[OnlyMarketDataInputType, int] = {}
        self._dependencies: dict[str, OnlyMarketDataConstructionEdge] = {}
        self._algorithm_registry = algorithm_registry or OnlyBarConstructionAlgorithmRegistry()
        self._compiler = OnlyConstructionGraphCompiler(source_binding_identity)
        self._plan = self._compiler.compile(OnlyMarketDataConstructionGraph((), ()), {})
        self._creation_count = 0
        self._failed = False
        self._processing = False

    @property
    def aggregator_count(self) -> int:
        return len(self._executors)

    @property
    def creation_count(self) -> int:
        return self._creation_count

    @property
    def graph(self) -> OnlyMarketDataConstructionGraph:
        providers = tuple(sorted(self._provider_reference_counts, key=lambda item: only_canonical_json(item.to_dict())))
        dependencies = tuple(
            sorted(
                self._dependencies.values(),
                key=lambda edge: only_canonical_json(
                    {
                        "source": edge.source.to_dict(),
                        "target": edge.target.to_dict(),
                        "recipe": edge.recipe.to_dict(),
                    }
                ),
            )
        )
        return OnlyMarketDataConstructionGraph(providers, dependencies)

    @property
    def compiled_plan(self) -> OnlyCompiledConstructionPlan:
        return self._plan

    def _lane_id(self, dependency: OnlyMarketDataConstructionEdge) -> str:
        return OnlyMarketDataConstructionLane(
            dependency.target, dependency.recipe.fingerprint, self._source_binding_identity
        ).lane_id

    def register_subscription(self, subscription: OnlyBarSubscription) -> None:
        self.register_graph(subscription.dependency_graph)

    def register_graph(self, graph: OnlyMarketDataConstructionGraph) -> None:
        self._require_available()
        dependencies = graph.derived_dependencies
        for dependency in dependencies:
            self._algorithm_registry.require(dependency.recipe)
            if any(
                existing.target == dependency.target and existing != dependency
                for existing in self._dependencies.values()
            ):
                raise OnlyBarAggregationError("RUNTIME_CONSTRUCTION_LANE_CONFLICT")
            if dependency.target in self._provider_reference_counts:
                raise OnlyBarAggregationError("RUNTIME_CONSTRUCTION_LANE_CONFLICT")
        for provider in graph.provider_inputs:
            if any(edge.target == provider for edge in self._dependencies.values()):
                raise OnlyBarAggregationError("RUNTIME_CONSTRUCTION_LANE_CONFLICT")

        prepared: dict[str, OnlyMarketDataConstructionExecutor] = {}
        for dependency in dependencies:
            lane_id = self._lane_id(dependency)
            if lane_id in self._executors:
                continue
            executor = self._algorithm_registry.create_executor(dependency, self._calendar, self._clock)
            if not isinstance(executor, OnlyMarketDataConstructionExecutor):
                raise ValueError("CONSTRUCTION_EXECUTOR_INVALID")
            prepared[lane_id] = executor

        candidate_executors = {**self._executors, **prepared}
        candidate_dependencies = dict(self._dependencies)
        candidate_dependencies.update({self._lane_id(edge): edge for edge in dependencies})
        candidate_providers = dict(self._provider_reference_counts)
        for provider in graph.provider_inputs:
            candidate_providers[provider] = candidate_providers.get(provider, 0) + 1
        candidate_graph = OnlyMarketDataConstructionGraph(
            tuple(candidate_providers), tuple(candidate_dependencies.values())
        )
        plan = self._compiler.compile(candidate_graph, candidate_executors)

        self._executors = candidate_executors
        self._dependencies = candidate_dependencies
        self._provider_reference_counts = candidate_providers
        for dependency in dependencies:
            lane_id = self._lane_id(dependency)
            self._reference_counts[lane_id] = self._reference_counts.get(lane_id, 0) + 1
        self._creation_count += len(prepared)
        self._plan = plan

    def unregister_subscription(self, subscription: OnlyBarSubscription) -> None:
        self.unregister_graph(subscription.dependency_graph)

    def unregister_graph(self, graph: OnlyMarketDataConstructionGraph) -> None:
        self._require_available()
        for provider in graph.provider_inputs:
            count = self._provider_reference_counts.get(provider, 0)
            if count <= 1:
                self._provider_reference_counts.pop(provider, None)
            else:
                self._provider_reference_counts[provider] = count - 1
        for dependency in graph.derived_dependencies:
            lane_id = self._lane_id(dependency)
            count = self._reference_counts.get(lane_id, 0)
            if count <= 1:
                self._reference_counts.pop(lane_id, None)
                self._executors.pop(lane_id, None)
                self._dependencies.pop(lane_id, None)
            else:
                self._reference_counts[lane_id] = count - 1
        self._plan = self._compiler.compile(self.graph, self._executors)

    def process(self, fact: object) -> tuple[OnlyBar, ...]:
        self._require_available()
        provider_lanes = tuple(
            lane for lane in self._plan.provider_input_lanes if self._matches_provider_input(fact, lane.input_type)
        )
        if not provider_lanes:
            return ()
        if len(provider_lanes) != 1:
            self._failed = True
            raise OnlyBarAggregationError("CONSTRUCTION_PROVIDER_LANE_AMBIGUOUS")

        self._processing = True
        queue = deque((_OnlyConstructionWorkItem(provider_lanes[0].lane_id, fact),))
        outputs: list[OnlyBar] = []
        try:
            while queue:
                current = queue.popleft()
                for lane in self._plan.outgoing_by_lane.get(current.source_lane_id, ()):
                    if not lane.executor.accepts(current.fact):
                        raise OnlyBarAggregationError("CONSTRUCTION_EXECUTOR_INPUT_CONTRACT_VIOLATION")
                    produced = lane.executor.process(current.fact)
                    if not isinstance(produced, tuple):
                        raise OnlyBarAggregationError("CONSTRUCTION_EXECUTOR_RESULT_CONTRACT_VIOLATION")
                    for output in produced:
                        if not isinstance(output, OnlyBar) or output.bar_type != lane.edge.target:
                            raise OnlyBarAggregationError("CONSTRUCTION_EXECUTOR_OUTPUT_CONTRACT_VIOLATION")
                        outputs.append(output)
                        queue.append(_OnlyConstructionWorkItem(lane.lane_id, output))
        except Exception:
            self._failed = True
            raise
        finally:
            self._processing = False
        return tuple(outputs)

    def capture_checkpoint(self) -> object:
        self._require_available()
        if self._processing:
            raise ValueError("CONSTRUCTION_CHECKPOINT_WORK_QUEUE_NOT_EMPTY")
        return self._checkpoint_payload()

    def _checkpoint_payload(self) -> dict[str, object]:
        lanes = []
        compiled_by_id = {lane.lane_id: lane for lane in self._plan.construction_lanes}
        for lane_id, executor in sorted(self._executors.items()):
            lane = compiled_by_id[lane_id]
            lanes.append(
                {
                    "lane_id": lane_id,
                    "source_lane_id": lane.source_lane_id,
                    "topological_level": lane.topological_level,
                    "recipe_fingerprint": lane.edge.recipe.fingerprint,
                    "executor_state": executor.capture_checkpoint(),
                    "reference_count": self._reference_counts[lane_id],
                }
            )
        return {
            "schema_version": 3,
            "construction_graph_fingerprint": self._plan.graph_fingerprint,
            "source_binding_identity": self._source_binding_identity,
            "lanes": lanes,
            "provider_reference_counts": [
                [provider.to_dict(), count]
                for provider, count in sorted(
                    self._provider_reference_counts.items(), key=lambda item: only_canonical_json(item[0].to_dict())
                )
            ],
            "creation_count": self._creation_count,
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict) or payload.get("schema_version") != 3:
            raise ValueError("CONSTRUCTION_CHECKPOINT_REBUILD_REQUIRED")
        expected = self._checkpoint_payload()
        for key in (
            "construction_graph_fingerprint",
            "source_binding_identity",
            "provider_reference_counts",
        ):
            if payload.get(key) != expected[key]:
                raise ValueError("CONSTRUCTION_CHECKPOINT_REBUILD_REQUIRED")
        raw_lanes = payload.get("lanes")
        if not isinstance(raw_lanes, list):
            raise ValueError("CONSTRUCTION_CHECKPOINT_REBUILD_REQUIRED")
        states = {str(item["lane_id"]): item for item in raw_lanes if isinstance(item, dict)}
        expected_raw_lanes = expected["lanes"]
        assert isinstance(expected_raw_lanes, list)
        expected_lanes = {str(item["lane_id"]): item for item in expected_raw_lanes}
        if set(states) != set(expected_lanes):
            raise ValueError("CONSTRUCTION_CHECKPOINT_REBUILD_REQUIRED")
        for lane_id, item in states.items():
            expected_item = expected_lanes[lane_id]
            for key in ("source_lane_id", "topological_level", "recipe_fingerprint", "reference_count"):
                if item.get(key) != expected_item[key]:
                    raise ValueError("CONSTRUCTION_CHECKPOINT_REBUILD_REQUIRED")
        try:
            for lane_id, item in states.items():
                self._executors[lane_id].restore_checkpoint(item["executor_state"])
            self._creation_count = int(payload["creation_count"])
            self._failed = False
        except Exception:
            self._failed = True
            raise

    def _require_available(self) -> None:
        if self._failed:
            raise OnlyBarAggregationError("CONSTRUCTION_RUNTIME_RECOVERY_REQUIRED")

    @staticmethod
    def _matches_provider_input(fact: object, input_type: OnlyMarketDataInputType) -> bool:
        if isinstance(input_type, OnlyTradeInputType):
            return isinstance(fact, OnlyTradeTick) and fact.instrument_id == input_type.instrument_id
        return isinstance(fact, OnlyBar) and fact.bar_type == input_type
