"""Runtime-agnostic assembly boundary; concrete selection is delegated to registries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.cluster.factory import OnlyClusterFactory
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.fee.basis import OnlyFeeBasisProviderRegistry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContractRegistry
from onlyalpha.fee.reconciliation_policy import OnlyFeeReconciliationPolicyRegistry
from onlyalpha.market.product import OnlyMarketProductFactoryRegistry
from onlyalpha.runtime.factory import OnlyRuntimeBuildRequest, OnlyRuntimeBuildResult, OnlyRuntimeFactoryRegistry
from onlyalpha.runtime.persistence.factory import OnlyRuntimePersistenceStoreFactory
from onlyalpha.runtime.planning import OnlyRuntimePlan


@dataclass(frozen=True, slots=True)
class OnlyComponentFactoryRegistries:
    data_sources: OnlyDataSourceFactoryRegistry
    brokers: OnlyBrokerFactoryRegistry
    market_products: OnlyMarketProductFactoryRegistry
    clusters: OnlyClusterFactory
    broker_fee_contracts: OnlyBrokerFeeContractRegistry
    fee_basis_providers: OnlyFeeBasisProviderRegistry
    fee_reconciliation_policies: OnlyFeeReconciliationPolicyRegistry
    runtime_persistence_stores: OnlyRuntimePersistenceStoreFactory


class OnlyEngineRunAssembler:
    def __init__(
        self,
        runtime_factories: OnlyRuntimeFactoryRegistry,
        component_factories: OnlyComponentFactoryRegistries,
    ) -> None:
        self._runtime_factories = runtime_factories
        self.components = component_factories

    def build(self, plan: OnlyRuntimePlan, user_data_root: Path | None = None) -> OnlyRuntimeBuildResult:
        try:
            factory = self._runtime_factories.require(plan.environment.runtime_type)
        except ValueError as exc:
            return OnlyRuntimeBuildResult(
                failure_code="RUNTIME_FACTORY_NOT_AVAILABLE",
                failure_message=str(exc),
            )
        return factory.create(OnlyRuntimeBuildRequest(plan, self.components, user_data_root))

    def validate(self, plan: OnlyRuntimePlan) -> OnlyRuntimeBuildResult:
        """Validate factory availability without constructing Runtime objects."""

        try:
            factory = self._runtime_factories.require(plan.environment.runtime_type)
        except ValueError as exc:
            return OnlyRuntimeBuildResult(
                failure_code="RUNTIME_FACTORY_NOT_AVAILABLE",
                failure_message=str(exc),
            )
        validate = getattr(factory, "validate", None)
        if callable(validate):
            return cast(OnlyRuntimeBuildResult, validate(OnlyRuntimeBuildRequest(plan, self.components)))
        return OnlyRuntimeBuildResult()
