"""Cluster composition through the sole immutable Strategy resolver."""

from __future__ import annotations

from pathlib import Path

from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_json
from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.cluster.scenario_action_workload import OnlyScenarioActionWorkload
from onlyalpha.config import OnlyClusterImportConfig, OnlyRuntimeAssemblyPlan
from onlyalpha.domain.market import OnlyBarSemantic, OnlyBarType, OnlyTradeInputType, OnlyTradeSemantic
from onlyalpha.indicator.registry import OnlyIndicatorFactoryRegistry
from onlyalpha.market_data.resolution import (
    OnlyBarConstructionKind,
    OnlyBarConstructionRequirementKind,
    OnlyMarketDataConstructionEdge,
    OnlyMarketDataConstructionGraph,
)
from onlyalpha.market_data.subscriptions import OnlyBarSubscription, only_bar_type_id
from onlyalpha.strategy.execution import OnlyStrategyExecutionResolver
from onlyalpha.strategy.revision import OnlyStrategyRevision
from onlyalpha.strategy.store import OnlyFrozenStrategyRevisionStore


def only_strategy_market_data_graph(revision: OnlyStrategyRevision) -> OnlyMarketDataConstructionGraph:
    contract = revision.market_input_contract
    if contract.construction_requirement.kind is not OnlyBarConstructionRequirementKind.EXACT_RECIPE:
        raise ValueError("STRATEGY_EXACT_BAR_CONSTRUCTION_REQUIRED")
    recipe = contract.construction_requirement.recipe
    assert recipe is not None
    providers: list[OnlyBarType | OnlyTradeInputType] = []
    edges: list[OnlyMarketDataConstructionEdge] = []
    for instrument_id in revision.universe.instruments:
        target = OnlyBarType(instrument_id, contract.bar_semantic)
        if recipe.kind is OnlyBarConstructionKind.PROVIDER_NATIVE:
            providers.append(target)
        else:
            base = recipe.base_semantic
            source: OnlyBarType | OnlyTradeInputType
            if isinstance(base, OnlyBarSemantic):
                source = OnlyBarType(instrument_id, base)
            elif isinstance(base, OnlyTradeSemantic):
                source = OnlyTradeInputType(instrument_id)
            else:
                raise ValueError("CONSTRUCTION_ALGORITHM_UNAVAILABLE")
            providers.append(source)
            edges.append(OnlyMarketDataConstructionEdge(source, target, recipe))
    provider_inputs = tuple(sorted(providers, key=lambda item: only_canonical_json(item.to_dict())))
    return OnlyMarketDataConstructionGraph(provider_inputs, tuple(edges))


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
        graph = only_strategy_market_data_graph(revision)
        bar_types = tuple(
            sorted(
                {
                    *(item for item in graph.provider_inputs if isinstance(item, OnlyBarType)),
                    *(edge.target for edge in graph.derived_dependencies),
                },
                key=only_bar_type_id,
            )
        )
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
