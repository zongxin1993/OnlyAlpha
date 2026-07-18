"""Cluster composition root: one Strategy, many Factors, no concrete algorithms."""

from __future__ import annotations

from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.config import OnlyClusterImportConfig, OnlyRuntimeAssemblyPlan
from onlyalpha.factor.factory import OnlyFactorCreateRequest, OnlyFactorFactory
from onlyalpha.indicator.registry import OnlyIndicatorFactoryRegistry
from onlyalpha.market_data.subscriptions import OnlyBarSubscription, only_bar_type_id
from onlyalpha.strategy.factory import OnlyStrategyCreateRequest, OnlyStrategyFactory


class OnlyClusterFactory:
    def __init__(
        self,
        strategies: OnlyStrategyFactory,
        factors: OnlyFactorFactory,
        indicators: OnlyIndicatorFactoryRegistry,
    ) -> None:
        self._strategies = strategies
        self._factors = factors
        self._indicators = indicators

    def create(self, config: OnlyClusterImportConfig, run_config: OnlyRuntimeAssemblyPlan) -> OnlyCluster:
        strategy_parameters: dict[str, object] = dict(config.strategy.extensions)
        strategy_parameters.update(
            {
                "cluster_id": config.cluster_id,
                "account_id": config.account_id,
                "instruments": run_config.reference_data.instrument_by_id,
            }
        )
        strategy = self._strategies.create(
            OnlyStrategyCreateRequest(
                config.strategy.strategy_path,
                config.strategy.config_path,
                strategy_parameters,
            )
        )
        factor_instances = []
        bar_types = []
        primary_bar_type = None
        for factor in config.factors:
            factor_bar_types = []
            for subscription in factor.subscriptions.instrument_bars:
                bar_type = subscription.bar_specification.to_bar_type(subscription.instrument_id)
                factor_bar_types.append(bar_type)
                bar_types.append(bar_type)
                if subscription.role.value == "PRIMARY":
                    if primary_bar_type is not None and primary_bar_type != bar_type:
                        raise ValueError("Cluster must resolve to exactly one PRIMARY BarType")
                    primary_bar_type = bar_type
            if factor.subscriptions.universe_bars:
                raise ValueError("first-phase Runtime cannot yet expand universe Bar subscriptions")
            parameters: dict[str, object] = dict(factor.extensions)
            parameters.update(
                {
                    "factor_id": factor.factor_id,
                    "factor_type": factor.factor_type,
                    "dependencies": factor.dependencies,
                    "required": factor.required,
                    "indicator_specs": tuple(
                        {
                            "indicator_id": item.indicator_id,
                            "indicator_type": item.indicator_type,
                            "bar_type": factor_bar_types[0],
                            "parameters": item.parameters,
                        }
                        for item in factor.indicators
                    ),
                }
            )
            factor_instances.append(
                self._factors.create(OnlyFactorCreateRequest(factor.factor_path, factor.config_path, parameters))
            )
        if primary_bar_type is None:
            raise ValueError("Cluster requires one PRIMARY Bar subscription")
        unique_bar_types = tuple(sorted(set(bar_types), key=only_bar_type_id))
        cluster_subscription = OnlyBarSubscription(unique_bar_types, primary_bar_type=primary_bar_type)
        return OnlyCluster(
            OnlyClusterConfig(
                str(config.cluster_id),
                cluster_subscription,
                {
                    "allowed_account_ids": (config.account_id,),
                    "allowed_instrument_ids": tuple(sorted({item.instrument_id for item in unique_bar_types}, key=str)),
                },
            ),
            strategy,
            tuple(factor_instances),
            self._indicators,
        )
