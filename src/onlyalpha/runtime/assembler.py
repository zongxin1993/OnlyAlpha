"""Runtime-agnostic assembly boundary; concrete selection is delegated to registries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.cluster.factory import OnlyClusterFactory
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.fee.schedules import OnlyBrokerFeeScheduleRegistry, OnlyMarketFeeScheduleRegistry
from onlyalpha.market.registry import OnlyMarketProfileRegistry
from onlyalpha.market.runtime_rules import OnlyMarketRuleCompiler
from onlyalpha.runtime.factory import OnlyRuntimeBuildRequest, OnlyRuntimeBuildResult, OnlyRuntimeFactoryRegistry
from onlyalpha.runtime.planning import OnlyRuntimePlan


@dataclass(frozen=True, slots=True)
class OnlyComponentFactoryRegistries:
    data_sources: OnlyDataSourceFactoryRegistry
    brokers: OnlyBrokerFactoryRegistry
    clusters: OnlyClusterFactory
    market_profiles: OnlyMarketProfileRegistry
    market_rule_compiler: OnlyMarketRuleCompiler
    market_fee_schedules: OnlyMarketFeeScheduleRegistry
    broker_fee_schedules: OnlyBrokerFeeScheduleRegistry


class OnlyEngineRunAssembler:
    def __init__(
        self,
        runtime_factories: OnlyRuntimeFactoryRegistry,
        component_factories: OnlyComponentFactoryRegistries,
    ) -> None:
        self._runtime_factories = runtime_factories
        self._component_factories = component_factories

    def build(self, plan: OnlyRuntimePlan, user_data_root: Path | None = None) -> OnlyRuntimeBuildResult:
        try:
            factory = self._runtime_factories.require(plan.compatibility_key.runtime_type)
        except ValueError as exc:
            return OnlyRuntimeBuildResult(
                failure_code="RUNTIME_FACTORY_NOT_AVAILABLE",
                failure_message=str(exc),
            )
        return factory.create(OnlyRuntimeBuildRequest(plan, self._component_factories, user_data_root))

    def validate(self, plan: OnlyRuntimePlan) -> OnlyRuntimeBuildResult:
        """Validate factory availability without constructing Runtime objects."""

        try:
            factory = self._runtime_factories.require(plan.compatibility_key.runtime_type)
        except ValueError as exc:
            return OnlyRuntimeBuildResult(
                failure_code="RUNTIME_FACTORY_NOT_AVAILABLE",
                failure_message=str(exc),
            )
        validate = getattr(factory, "validate", None)
        if callable(validate):
            return cast(OnlyRuntimeBuildResult, validate(OnlyRuntimeBuildRequest(plan, self._component_factories)))
        return OnlyRuntimeBuildResult()
