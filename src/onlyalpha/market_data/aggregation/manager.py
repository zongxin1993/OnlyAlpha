"""Runtime-level unique Aggregator graph and stable derived-Bar ordering."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.core.clock import OnlyClock
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.enums import OnlyAggregationSource, OnlyBarAggregation
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.market_data.aggregation.time_bar import OnlyBarAggregationError, OnlyTimeBarAggregator
from onlyalpha.market_data.subscriptions import (
    OnlyBarDependency,
    OnlyBarSubscription,
    OnlyIncompleteBarPolicy,
    OnlyMissingBarPolicy,
    only_bar_type_id,
)


@dataclass(frozen=True, slots=True)
class OnlyAggregationDependency:
    source: OnlyBarType
    target: OnlyBarType


@dataclass(frozen=True, slots=True)
class OnlyBarAggregationGraph:
    dependencies: tuple[OnlyAggregationDependency, ...]

    def __post_init__(self) -> None:
        adjacency: dict[OnlyBarType, tuple[OnlyBarType, ...]] = {}
        for dependency in self.dependencies:
            current = adjacency.get(dependency.source, ())
            adjacency[dependency.source] = current + (dependency.target,)
        visiting: set[OnlyBarType] = set()
        visited: set[OnlyBarType] = set()

        def visit(node: OnlyBarType) -> None:
            if node in visiting:
                raise OnlyBarAggregationError("Bar aggregation graph contains a cycle")
            if node in visited:
                return
            visiting.add(node)
            for target in adjacency.get(node, ()):
                visit(target)
            visiting.remove(node)
            visited.add(node)

        for node in adjacency:
            visit(node)


class OnlyBarAggregationManager:
    """One mutable aggregation state per derived BarType in a Runtime."""

    def __init__(
        self,
        calendar: OnlyTradingCalendar,
        clock: OnlyClock,
        *,
        incomplete_policy: OnlyIncompleteBarPolicy = OnlyIncompleteBarPolicy.DROP,
        missing_policy: OnlyMissingBarPolicy = OnlyMissingBarPolicy.REJECT,
    ) -> None:
        self._calendar = calendar
        self._clock = clock
        self._incomplete_policy = incomplete_policy
        self._missing_policy = missing_policy
        self._aggregators: dict[OnlyBarType, OnlyTimeBarAggregator] = {}
        self._reference_counts: dict[OnlyBarType, int] = {}
        self._creation_count = 0

    @property
    def aggregator_count(self) -> int:
        return len(self._aggregators)

    @property
    def creation_count(self) -> int:
        return self._creation_count

    @property
    def graph(self) -> OnlyBarAggregationGraph:
        return OnlyBarAggregationGraph(
            tuple(
                OnlyAggregationDependency(item.source_bar_type, item.target_bar_type)
                for item in self._aggregators.values()
            )
        )

    def register_subscription(self, subscription: OnlyBarSubscription) -> None:
        sources = [
            item
            for item in subscription.bar_types
            if item.specification.aggregation is OnlyBarAggregation.TIME
            and item.specification.step == 1
            and item.aggregation_source is OnlyAggregationSource.EXTERNAL
        ]
        targets = [item for item in subscription.bar_types if item.aggregation_source is OnlyAggregationSource.INTERNAL]
        if targets and len(sources) != 1:
            raise OnlyBarAggregationError("derived time Bars require one external 1m source in the subscription")
        if not targets:
            return
        source = sources[0]
        for target in sorted(targets, key=lambda item: (item.specification.step, only_bar_type_id(item))):
            OnlyBarDependency(source, target)
            if target not in self._aggregators:
                self._aggregators[target] = OnlyTimeBarAggregator(
                    source,
                    target,
                    self._calendar,
                    self._clock,
                    incomplete_policy=self._incomplete_policy,
                    missing_policy=self._missing_policy,
                )
                self._creation_count += 1
            self._reference_counts[target] = self._reference_counts.get(target, 0) + 1
        _ = self.graph

    def unregister_subscription(self, subscription: OnlyBarSubscription) -> None:
        """Release one subscription reference and remove unused aggregation state."""

        targets = [item for item in subscription.bar_types if item.aggregation_source is OnlyAggregationSource.INTERNAL]
        for target in targets:
            count = self._reference_counts.get(target, 0)
            if count <= 1:
                self._reference_counts.pop(target, None)
                self._aggregators.pop(target, None)
            else:
                self._reference_counts[target] = count - 1

    def process(self, base_bar: OnlyBar) -> tuple[OnlyBar, ...]:
        derived: list[OnlyBar] = []
        aggregators = sorted(
            (item for item in self._aggregators.values() if item.source_bar_type == base_bar.bar_type),
            key=lambda item: (item.target_bar_type.specification.step, only_bar_type_id(item.target_bar_type)),
        )
        for aggregator in aggregators:
            result = aggregator.process(base_bar)
            if result is not None:
                derived.append(result)
        return tuple(derived)
