"""Cluster composition through the sole immutable Strategy resolver."""

from __future__ import annotations

from pathlib import Path

from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.cluster.scenario_action_workload import OnlyScenarioActionWorkload
from onlyalpha.config import OnlyClusterImportConfig, OnlyRuntimeAssemblyPlan
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.indicator.registry import OnlyIndicatorFactoryRegistry
from onlyalpha.market_data.subscriptions import OnlyBarSubscription, only_bar_type_id
from onlyalpha.strategy.adapter import OnlyRevisionStrategyAdapter
from onlyalpha.strategy.execution import OnlyStrategyExecutionResolver
from onlyalpha.strategy.store import OnlyStrategyRevisionStore


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
            OnlyStrategyRevisionStore(semantic_root),
            self._calculations,
        ).resolve(config.strategy.fingerprint)
        revision = plan.revision
        contract = revision.market_input_contract
        bar_types = tuple(
            sorted(
                (
                    OnlyBarType(instrument_id, contract.bar_specification, contract.aggregation_source)
                    for instrument_id in revision.universe.instruments
                ),
                key=only_bar_type_id,
            )
        )
        cluster_subscription = OnlyBarSubscription(bar_types, primary_bar_type=bar_types[0])
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
            OnlyRevisionStrategyAdapter(plan),
            (),
            self._indicators,
            None if not config.scenario_actions else OnlyScenarioActionWorkload(config.scenario_actions),
        )
