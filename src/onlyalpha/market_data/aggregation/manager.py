"""Runtime-level unique Aggregator graph and stable derived-Bar ordering."""

from __future__ import annotations

from onlyalpha.core.clock import OnlyClock
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.market_data.aggregation.time_bar import OnlyBarAggregationError, OnlyTimeBarAggregator
from onlyalpha.market_data.resolution import (
    OnlyBarConstructionAlgorithmRegistry,
    OnlyBarDependencyGraph,
    OnlyBarDerivedDependency,
)
from onlyalpha.market_data.subscriptions import (
    OnlyBarSubscription,
    OnlyIncompleteBarPolicy,
    OnlyMissingBarPolicy,
    only_bar_type_id,
)


class OnlyBarAggregationManager:
    """One mutable aggregation state per derived BarType in a Runtime."""

    def __init__(
        self,
        calendar: OnlyTradingCalendar,
        clock: OnlyClock,
    ) -> None:
        self._calendar = calendar
        self._clock = clock
        self._aggregators: dict[OnlyBarType, OnlyTimeBarAggregator] = {}
        self._reference_counts: dict[OnlyBarType, int] = {}
        self._provider_reference_counts: dict[OnlyBarType, int] = {}
        self._dependencies: dict[OnlyBarType, OnlyBarDerivedDependency] = {}
        self._algorithm_registry = OnlyBarConstructionAlgorithmRegistry()
        self._creation_count = 0

    @property
    def aggregator_count(self) -> int:
        return len(self._aggregators)

    @property
    def creation_count(self) -> int:
        return self._creation_count

    @property
    def graph(self) -> OnlyBarDependencyGraph:
        providers = tuple(sorted(self._provider_reference_counts, key=only_bar_type_id))
        return OnlyBarDependencyGraph(providers, tuple(self._dependencies.values()))

    def register_subscription(self, subscription: OnlyBarSubscription) -> None:
        dependencies = subscription.dependency_graph.derived_dependencies
        for dependency in dependencies:
            self._algorithm_registry.require(dependency.recipe)
            existing = self._dependencies.get(dependency.target)
            if existing is not None and existing != dependency:
                raise OnlyBarAggregationError("derived Bar target has conflicting construction recipes")
        for provider in subscription.dependency_graph.provider_inputs:
            self._provider_reference_counts[provider] = self._provider_reference_counts.get(provider, 0) + 1
        if not dependencies:
            return
        for dependency in sorted(
            dependencies, key=lambda item: (item.target.semantic.stride_minutes, only_bar_type_id(item.target))
        ):
            source, target = dependency.source, dependency.target
            assert dependency.recipe.incomplete_policy is not None
            assert dependency.recipe.missing_policy is not None
            if target not in self._aggregators:
                self._aggregators[target] = OnlyTimeBarAggregator(
                    source,
                    target,
                    self._calendar,
                    self._clock,
                    incomplete_policy=OnlyIncompleteBarPolicy(dependency.recipe.incomplete_policy.value),
                    missing_policy=OnlyMissingBarPolicy(dependency.recipe.missing_policy.value),
                )
                self._dependencies[target] = dependency
                self._creation_count += 1
            self._reference_counts[target] = self._reference_counts.get(target, 0) + 1

    def unregister_subscription(self, subscription: OnlyBarSubscription) -> None:
        """Release one subscription reference and remove unused aggregation state."""

        for provider in subscription.dependency_graph.provider_inputs:
            count = self._provider_reference_counts.get(provider, 0)
            if count <= 1:
                self._provider_reference_counts.pop(provider, None)
            else:
                self._provider_reference_counts[provider] = count - 1
        targets = [item.target for item in subscription.dependency_graph.derived_dependencies]
        for target in targets:
            count = self._reference_counts.get(target, 0)
            if count <= 1:
                self._reference_counts.pop(target, None)
                self._aggregators.pop(target, None)
                self._dependencies.pop(target, None)
            else:
                self._reference_counts[target] = count - 1

    def process(self, base_bar: OnlyBar) -> tuple[OnlyBar, ...]:
        derived: list[OnlyBar] = []
        aggregators = sorted(
            (item for item in self._aggregators.values() if item.source_bar_type == base_bar.bar_type),
            key=lambda item: (item.target_bar_type.semantic.stride_minutes, only_bar_type_id(item.target_bar_type)),
        )
        for aggregator in aggregators:
            result = aggregator.process(base_bar)
            if result is not None:
                derived.append(result)
        return tuple(derived)

    def capture_checkpoint(self) -> object:
        return {
            "aggregators": [
                [target.to_json(), aggregator.capture_checkpoint()]
                for target, aggregator in sorted(self._aggregators.items(), key=lambda item: item[0].to_json())
            ],
            "creation_count": self._creation_count,
            "reference_counts": [
                [target.to_json(), count]
                for target, count in sorted(self._reference_counts.items(), key=lambda item: item[0].to_json())
            ],
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Bar Aggregation checkpoint must be an object")
        states = {OnlyBarType.from_json(str(target)): value for target, value in payload["aggregators"]}
        if set(states) != set(self._aggregators):
            raise ValueError("Bar Aggregation participant graph changed")
        for target, state in states.items():
            self._aggregators[target].restore_checkpoint(state)
        expected_counts = {
            OnlyBarType.from_json(str(target)): int(count) for target, count in payload["reference_counts"]
        }
        if expected_counts != self._reference_counts:
            raise ValueError("Bar Aggregation reference graph changed")
        self._creation_count = int(payload["creation_count"])
