"""Runtime-level unique Aggregator graph and stable derived-Bar ordering."""

from __future__ import annotations

from onlyalpha.canonical import only_canonical_json
from onlyalpha.core.clock import OnlyClock
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.market_data.aggregation.base import OnlyBarAggregationError, OnlyBarAggregator
from onlyalpha.market_data.resolution import (
    OnlyBarConstructionAlgorithmRegistry,
    OnlyMarketDataConstructionEdge,
    OnlyMarketDataConstructionGraph,
    OnlyMarketDataConstructionLane,
    OnlyMarketDataInputType,
)
from onlyalpha.market_data.subscriptions import (
    OnlyBarSubscription,
    only_bar_type_id,
)


def _target_order(bar_type: OnlyBarType) -> tuple[int, str]:
    return (bar_type.semantic.stride_minutes if bar_type.semantic.is_fixed_duration else 0, only_bar_type_id(bar_type))


class OnlyBarAggregationManager:
    """One mutable aggregation state per construction lane in a Runtime."""

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
        self._aggregators: dict[str, OnlyBarAggregator] = {}
        self._reference_counts: dict[str, int] = {}
        self._provider_reference_counts: dict[OnlyMarketDataInputType, int] = {}
        self._dependencies: dict[str, OnlyMarketDataConstructionEdge] = {}
        self._algorithm_registry = algorithm_registry or OnlyBarConstructionAlgorithmRegistry()
        self._creation_count = 0

    @property
    def aggregator_count(self) -> int:
        return len(self._aggregators)

    @property
    def creation_count(self) -> int:
        return self._creation_count

    @property
    def graph(self) -> OnlyMarketDataConstructionGraph:
        providers = tuple(sorted(self._provider_reference_counts, key=lambda item: only_canonical_json(item.to_dict())))
        return OnlyMarketDataConstructionGraph(providers, tuple(self._dependencies.values()))

    def _lane_id(self, dependency: OnlyMarketDataConstructionEdge) -> str:
        return OnlyMarketDataConstructionLane(
            dependency.target, dependency.recipe.fingerprint, self._source_binding_identity
        ).lane_id

    def register_subscription(self, subscription: OnlyBarSubscription) -> None:
        self.register_graph(subscription.dependency_graph)

    def register_graph(self, graph: OnlyMarketDataConstructionGraph) -> None:
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
        prepared: dict[str, OnlyBarAggregator] = {}
        for dependency in sorted(dependencies, key=lambda item: _target_order(item.target)):
            lane_id = self._lane_id(dependency)
            if lane_id not in self._aggregators:
                executor = self._algorithm_registry.create_executor(dependency, self._calendar, self._clock)
                if not isinstance(executor, OnlyBarAggregator):
                    raise ValueError("CONSTRUCTION_EXECUTOR_INVALID")
                prepared[lane_id] = executor
        for provider in graph.provider_inputs:
            if any(edge.target == provider for edge in self._dependencies.values()):
                raise OnlyBarAggregationError("RUNTIME_CONSTRUCTION_LANE_CONFLICT")
        for provider in graph.provider_inputs:
            self._provider_reference_counts[provider] = self._provider_reference_counts.get(provider, 0) + 1
        if not dependencies:
            return
        for dependency in sorted(dependencies, key=lambda item: _target_order(item.target)):
            lane_id = self._lane_id(dependency)
            if lane_id not in self._aggregators:
                self._aggregators[lane_id] = prepared[lane_id]
                self._dependencies[lane_id] = dependency
                self._creation_count += 1
            self._reference_counts[lane_id] = self._reference_counts.get(lane_id, 0) + 1

    def unregister_subscription(self, subscription: OnlyBarSubscription) -> None:
        """Release one subscription reference and remove unused aggregation state."""

        self.unregister_graph(subscription.dependency_graph)

    def unregister_graph(self, graph: OnlyMarketDataConstructionGraph) -> None:
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
                self._aggregators.pop(lane_id, None)
                self._dependencies.pop(lane_id, None)
            else:
                self._reference_counts[lane_id] = count - 1

    def process(self, fact: object) -> tuple[OnlyBar, ...]:
        derived: list[OnlyBar] = []
        aggregators = sorted(
            (item for item in self._aggregators.values() if item.accepts(fact)),
            key=lambda item: _target_order(item.target_bar_type),
        )
        for aggregator in aggregators:
            result = aggregator.process(fact)
            if result is not None:
                derived.append(result)
        return tuple(derived)

    def capture_checkpoint(self) -> object:
        return {
            "schema_version": 2,
            "aggregators": [
                [lane_id, aggregator.capture_checkpoint()] for lane_id, aggregator in sorted(self._aggregators.items())
            ],
            "creation_count": self._creation_count,
            "reference_counts": [[lane_id, count] for lane_id, count in sorted(self._reference_counts.items())],
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict) or payload.get("schema_version") != 2:
            raise ValueError("BAR_AGGREGATION_CHECKPOINT_REBUILD_REQUIRED")
        states = {str(lane_id): value for lane_id, value in payload["aggregators"]}
        if set(states) != set(self._aggregators):
            raise ValueError("Bar Aggregation participant graph changed")
        expected_counts = {str(lane_id): int(count) for lane_id, count in payload["reference_counts"]}
        if expected_counts != self._reference_counts:
            raise ValueError("Bar Aggregation reference graph changed")
        for lane_id, state in states.items():
            self._aggregators[lane_id].restore_checkpoint(state)
        self._creation_count = int(payload["creation_count"])
