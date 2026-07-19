"""Cluster container: exactly one Strategy and zero or more Factors."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from onlyalpha.cluster.bar_context import OnlyBarContext
from onlyalpha.cluster.pipeline import OnlyClusterExecutionPlan, OnlyClusterPipeline, OnlyClusterPipelineResult
from onlyalpha.domain.identifiers import OnlyClusterId
from onlyalpha.domain.market import OnlyBar
from onlyalpha.factor.base import OnlyFactor
from onlyalpha.factor.context import OnlyDependentFactorView, OnlyFactorContext, OnlyFactorIndicatorContext
from onlyalpha.factor.dependency import OnlyFactorDependencyGraph
from onlyalpha.factor.identifiers import OnlyFactorId
from onlyalpha.factor.registry import OnlyFactorRegistry
from onlyalpha.factor.score import OnlyFactorScore
from onlyalpha.factor.snapshot import OnlyFactorSnapshot
from onlyalpha.indicator.registry import OnlyIndicatorFactoryRegistry, OnlyIndicatorRegistry
from onlyalpha.indicator.snapshot import OnlyIndicatorSnapshot
from onlyalpha.market_data.subscriptions import OnlyBarSubscription
from onlyalpha.result.strategy import OnlyStrategyResultRecorder
from onlyalpha.runtime.context import OnlyClusterContext, OnlyTimerContext
from onlyalpha.strategy.base import OnlyNoopStrategy, OnlyStrategy
from onlyalpha.strategy.config import OnlyStrategyConfig
from onlyalpha.strategy.context import OnlyStrategyContext, OnlyStrategyFactorView, OnlyStrategyTimerContext
from onlyalpha.strategy.identifiers import OnlyStrategyId


class OnlyClusterError(Exception):
    """Base Cluster lifecycle or callback error."""


class OnlyClusterState(StrEnum):
    CREATED = "CREATED"
    LOADED = "LOADED"
    INITIALIZED = "INITIALIZED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    UNLOADED = "UNLOADED"


@dataclass(frozen=True, slots=True)
class OnlyClusterConfig:
    cluster_id: str
    subscription: OnlyBarSubscription | None = None
    values: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.cluster_id.strip():
            raise ValueError("cluster_id is required")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True, slots=True)
class OnlyClusterSnapshot:
    cluster_id: OnlyClusterId
    state: OnlyClusterState
    strategy_id: str
    factor_ids: tuple[OnlyFactorId, ...]
    required_factors_ready: bool


class OnlyCluster:
    """Runtime-bound container; it is never a concrete trading strategy."""

    def __init__(
        self,
        config: OnlyClusterConfig,
        strategy: OnlyStrategy | None = None,
        factors: tuple[OnlyFactor, ...] = (),
        indicator_factories: OnlyIndicatorFactoryRegistry | None = None,
    ) -> None:
        self.config = config
        self.strategy = strategy or OnlyNoopStrategy(OnlyStrategyConfig(OnlyStrategyId(f"{config.cluster_id}-noop")))
        self.factor_registry = OnlyFactorRegistry(factors)
        self._factor_plan = OnlyFactorDependencyGraph().build(factors)
        required = self.strategy.config.required_factor_ids
        unknown = set(required) - {item.factor_id for item in factors}
        if unknown:
            raise ValueError(f"Strategy references unknown required Factors: {sorted(unknown)}")
        if indicator_factories is None:
            from onlyalpha.indicator import only_default_indicator_factories

            indicator_factories = only_default_indicator_factories()
        if not isinstance(indicator_factories, OnlyIndicatorFactoryRegistry):
            raise TypeError("Cluster requires an OnlyIndicatorFactoryRegistry")
        self._indicator_factories = indicator_factories
        self._context: OnlyClusterContext | None = None
        self._state = OnlyClusterState.CREATED
        self._indicator_registry: OnlyIndicatorRegistry | None = None
        self._pipeline: OnlyClusterPipeline | None = None
        self._factor_snapshots: dict[OnlyFactorId, OnlyFactorSnapshot] = {}
        self._factor_scores: dict[OnlyFactorId, OnlyFactorScore] = {}
        self._last_pipeline_result: OnlyClusterPipelineResult | None = None

    @property
    def context(self) -> OnlyClusterContext | None:
        return self._context

    @property
    def state(self) -> OnlyClusterState:
        return self._state

    @property
    def factors(self) -> tuple[OnlyFactor, ...]:
        return self.factor_registry.factors

    @property
    def indicator_snapshots(self) -> tuple[OnlyIndicatorSnapshot, ...]:
        return () if self._indicator_registry is None else self._indicator_registry.all_snapshots()

    @property
    def last_pipeline_result(self) -> OnlyClusterPipelineResult | None:
        return self._last_pipeline_result

    def snapshot(self) -> OnlyClusterSnapshot:
        required = self.strategy.config.required_factor_ids
        ready = all(
            self._factor_snapshots.get(item) is not None and self._factor_snapshots[item].ready for item in required
        )
        return OnlyClusterSnapshot(
            OnlyClusterId(self.config.cluster_id),
            self.state,
            str(self.strategy.strategy_id),
            tuple(item.factor_id for item in self.factors),
            ready,
        )

    def _only_manager_bind(self, context: OnlyClusterContext) -> None:
        if self._context is not None:
            raise OnlyClusterError("Cluster Context can be bound only once")
        self._context = context

    def _only_manager_transition(self, state: OnlyClusterState) -> None:
        self._state = state

    def on_load(self) -> None:
        pass

    def on_initialize(self) -> None:
        context = self._require_context()
        indicator_registry = OnlyIndicatorRegistry(context.runtime_id, context.cluster_id, self._indicator_factories)
        dependent = OnlyDependentFactorView(self._factor_snapshots, self._factor_scores)
        for factor in self.factors:
            factor._only_cluster_bind(
                OnlyFactorContext(
                    context.clock,
                    context.market_data,
                    OnlyFactorIndicatorContext(factor.factor_id, indicator_registry),
                    dependent,
                    context.instruments,
                    context.logger,
                )
            )
            factor.on_initialize()
        strategy_context = OnlyStrategyContext(
            context,
            OnlyStrategyFactorView(self._factor_snapshots, self._factor_scores),
            OnlyStrategyResultRecorder(self.config.cluster_id, str(self.strategy.strategy_id)),
        )
        self.strategy._only_cluster_bind(strategy_context)
        self.strategy.on_initialize()
        if self.config.subscription is not None:
            context.subscriptions.subscribe_bars(self.config.subscription)
        self._indicator_registry = indicator_registry
        self._pipeline = OnlyClusterPipeline(
            indicator_registry,
            self.factor_registry,
            self.strategy,
            OnlyClusterExecutionPlan(self._factor_plan, self.strategy.config.required_factor_ids),
            self._factor_snapshots,
            self._factor_scores,
        )

    def on_start(self) -> None:
        for factor in self.factors:
            factor.on_start()
        self.strategy.on_start()

    def on_bar(self, bar: OnlyBar, context: OnlyBarContext) -> None:
        if self._pipeline is None:
            raise OnlyClusterError("Cluster Pipeline is not initialized")
        self._last_pipeline_result = self._pipeline.process_bar(bar, context)

    def on_timer(self, context: OnlyTimerContext) -> None:
        self.strategy.on_timer(OnlyStrategyTimerContext(self.strategy.context, context))

    def on_pause(self) -> None:
        self.strategy.on_pause()

    def on_resume(self) -> None:
        self.strategy.on_resume()

    def on_stop(self) -> None:
        self.strategy.on_stop()
        for factor in reversed(self.factors):
            factor.on_stop()

    def on_unload(self) -> None:
        pass

    def on_error(self, error: Exception) -> None:
        self._require_context().logger.error("cluster callback failed: %s", error)

    def _require_context(self) -> OnlyClusterContext:
        if self._context is None:
            raise OnlyClusterError("Cluster Context is unavailable")
        return self._context
