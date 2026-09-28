"""Cluster composition through the sole immutable Strategy resolver."""

from __future__ import annotations

from pathlib import Path

from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.cluster.scenario_action_workload import OnlyScenarioActionWorkload
from onlyalpha.config import OnlyClusterImportConfig, OnlyRuntimeAssemblyPlan
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.indicator.registry import OnlyIndicatorFactoryRegistry
from onlyalpha.market_data.resolution import (
    OnlyBarConstructionKind,
    OnlyBarConstructionRequirementKind,
    OnlyBarDependencyGraph,
    OnlyBarDerivedDependency,
)
from onlyalpha.market_data.subscriptions import OnlyBarSubscription, only_bar_type_id
from onlyalpha.strategy.execution import OnlyStrategyExecutionResolver
from onlyalpha.strategy.store import OnlyFrozenStrategyRevisionStore


class OnlyClusterFactory:
    def __init__(
        self,
        calculations: OnlyCalculationRegistry,
        indicators: OnlyIndicatorFactoryRegistry,
    ) -> None:
        self._calculations = calculations
        self._indicators = indicators

    def create(
        self,
        config: OnlyClusterImportConfig,
        run_config: OnlyRuntimeAssemblyPlan,
        semantic_root: Path,
    ) -> OnlyCluster:
        del run_config
        if config.factors:
            raise ValueError("LEGACY_FACTOR_PIPELINE_CONFIGURATION_UNSUPPORTED")
        plan = OnlyStrategyExecutionResolver(
            OnlyFrozenStrategyRevisionStore(semantic_root),
            self._calculations,
        ).resolve(config.strategy.fingerprint)
        revision = plan.revision
        contract = revision.market_input_contract
        if contract.construction_requirement.kind is not OnlyBarConstructionRequirementKind.EXACT_RECIPE:
            raise ValueError("STRATEGY_EXACT_BAR_CONSTRUCTION_REQUIRED")
        recipe = contract.construction_requirement.recipe
        assert recipe is not None
        providers: list[OnlyBarType] = []
        targets: list[OnlyBarType] = []
        edges: list[OnlyBarDerivedDependency] = []
        for instrument_id in revision.universe.instruments:
            target = OnlyBarType(instrument_id, contract.bar_semantic)
            targets.append(target)
            if recipe.kind is OnlyBarConstructionKind.PROVIDER_NATIVE:
                providers.append(target)
            else:
                assert recipe.base_semantic is not None
                source = OnlyBarType(instrument_id, recipe.base_semantic)
                providers.append(source)
                edges.append(OnlyBarDerivedDependency(source, target, recipe))
        bar_types = tuple(sorted(set((*providers, *targets)), key=only_bar_type_id))
        graph = OnlyBarDependencyGraph(tuple(sorted(providers, key=only_bar_type_id)), tuple(edges))
        cluster_subscription = OnlyBarSubscription(
            bar_types, graph, primary_bar_type=OnlyBarType(revision.universe.instruments[0], contract.bar_semantic)
        )
        return OnlyCluster(
            OnlyClusterConfig(
                str(config.cluster_id),
                cluster_subscription,
                {
                    "strategy_fingerprint": str(revision.strategy_fingerprint),
                    "allowed_account_ids": (config.account_id,),
                    "allowed_instrument_ids": revision.universe.instruments,
                },
            ),
            plan,
            (),
            self._indicators,
            None if not config.scenario_actions else OnlyScenarioActionWorkload(config.scenario_actions),
        )
