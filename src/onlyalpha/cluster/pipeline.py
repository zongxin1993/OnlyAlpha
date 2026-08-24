"""Explicit Indicator -> Factor -> Strategy execution pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.cluster.bar_context import OnlyBarContext
from onlyalpha.domain.market import OnlyBar
from onlyalpha.factor.base import OnlyCrossSectionFactor, OnlyTimeSeriesFactor
from onlyalpha.factor.context import OnlyCrossSectionFactorContext, OnlyFactorBarContext
from onlyalpha.factor.dependency import OnlyFactorExecutionPlan
from onlyalpha.factor.identifiers import OnlyFactorId
from onlyalpha.factor.registry import OnlyFactorRegistry
from onlyalpha.factor.score import OnlyFactorScore
from onlyalpha.factor.snapshot import OnlyFactorSnapshot
from onlyalpha.indicator.registry import OnlyIndicatorRegistry
from onlyalpha.strategy.adapter import OnlyRevisionStrategyAdapter
from onlyalpha.strategy.execution import OnlyStrategyDecision


@dataclass(frozen=True, slots=True)
class OnlyClusterExecutionPlan:
    factor_plan: OnlyFactorExecutionPlan
    required_factor_ids: tuple[OnlyFactorId, ...]


@dataclass(frozen=True, slots=True)
class OnlyClusterPipelineResult:
    strategy_called: bool
    strategy_decision: OnlyStrategyDecision | None
    factor_snapshots: tuple[OnlyFactorSnapshot, ...]
    factor_scores: tuple[OnlyFactorScore, ...]


class OnlyClusterPipeline:
    def __init__(
        self,
        indicators: OnlyIndicatorRegistry,
        factors: OnlyFactorRegistry,
        strategy: OnlyRevisionStrategyAdapter | None,
        plan: OnlyClusterExecutionPlan,
        snapshots: dict[OnlyFactorId, OnlyFactorSnapshot],
        scores: dict[OnlyFactorId, OnlyFactorScore],
    ) -> None:
        self._indicators = indicators
        self._factors = factors
        self._strategy = strategy
        self._plan = plan
        self._snapshots = snapshots
        self._scores = scores

    def process_bar(self, bar: OnlyBar, context: OnlyBarContext) -> OnlyClusterPipelineResult:
        self._indicators.update_bar(bar)
        for factor_id in self._plan.factor_plan.ordered_factor_ids:
            factor = self._factors.require(factor_id)
            if any(
                dependency not in self._snapshots or not self._snapshots[dependency].ready
                for dependency in factor.config.dependencies
            ):
                continue
            if isinstance(factor, OnlyTimeSeriesFactor):
                factor.on_bar(OnlyFactorBarContext(bar, factor.context))
            elif isinstance(factor, OnlyCrossSectionFactor):
                bars = {
                    str(item.instrument_id): item
                    for item in context.snapshot.latest_closed_bars.values()
                    if item.bar_end == bar.bar_end
                }
                factor.on_cross_section(OnlyCrossSectionFactorContext(bars, factor.context))
            self._snapshots[factor_id] = factor.snapshot()
            self._scores[factor_id] = factor.score()
        ready = all(
            self._snapshots.get(factor_id) is not None and self._snapshots[factor_id].ready
            for factor_id in self._plan.required_factor_ids
        )
        decision = None if not ready or self._strategy is None else self._strategy.on_bar(bar)
        return OnlyClusterPipelineResult(
            decision is not None,
            decision,
            tuple(self._snapshots[key] for key in sorted(self._snapshots)),
            tuple(self._scores[key] for key in sorted(self._scores)),
        )
