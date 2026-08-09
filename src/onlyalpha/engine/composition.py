"""Staged Cluster composition with a single mutation boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.engine.infrastructure import OnlyInfrastructureRegistry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContract
from onlyalpha.runtime.environment import (
    OnlyResourceClaim,
    OnlyRuntimeEnvironmentBuilder,
    OnlyRuntimeEnvironmentIdentity,
    only_canonical_fingerprint,
)

if TYPE_CHECKING:
    from onlyalpha.runtime.assembler import OnlyComponentFactoryRegistries


@dataclass(frozen=True, slots=True)
class OnlyClusterCompositionPlan:
    config: OnlyClusterRunConfig
    environment: OnlyRuntimeEnvironmentIdentity
    resource_claims: tuple[OnlyResourceClaim, ...]
    authority_installations: tuple[OnlyBrokerFeeContract, ...]
    fingerprint: str


class OnlyClusterComposition:
    """Validate all business failures before committing append-only authorities."""

    def __init__(
        self,
        infrastructure: OnlyInfrastructureRegistry,
        components: OnlyComponentFactoryRegistries,
        environment_builder: OnlyRuntimeEnvironmentBuilder | None = None,
    ) -> None:
        self._infrastructure = infrastructure
        self._components = components
        self._environment_builder = environment_builder or OnlyRuntimeEnvironmentBuilder()

    def plan(self, config: OnlyClusterRunConfig) -> OnlyClusterCompositionPlan:
        environment = self._environment_builder.build(config)
        claims = self._environment_builder.resource_claims(config)
        self._infrastructure.validate(config.cluster_id, claims)
        installations = self._new_contracts(config.broker_fee_contract_authorities)
        self._validate_selections(config, installations)
        fingerprint = only_canonical_fingerprint(
            {
                "cluster_id": str(config.cluster_id),
                "environment": environment,
                "claims": claims,
                "authorities": tuple(item.fingerprint for item in installations),
            }
        )
        return OnlyClusterCompositionPlan(config, environment, claims, installations, fingerprint)

    def commit(self, plan: OnlyClusterCompositionPlan) -> tuple[str, ...]:
        self._infrastructure.validate(plan.config.cluster_id, plan.resource_claims)
        self._components.broker_fee_contracts.validate_installations(plan.authority_installations)
        self._components.broker_fee_contracts.install_all(plan.authority_installations)
        return self._infrastructure.acquire(plan.config.cluster_id, plan.resource_claims)

    def _new_contracts(self, contracts: tuple[OnlyBrokerFeeContract, ...]) -> tuple[OnlyBrokerFeeContract, ...]:
        new = []
        for contract in contracts:
            try:
                installed = self._components.broker_fee_contracts.require(
                    contract.contract_id, contract.contract_version
                )
            except ValueError as exc:
                if str(exc) != "BROKER_FEE_CONTRACT_NOT_INSTALLED":
                    raise
                new.append(contract)
            else:
                if installed.fingerprint != contract.fingerprint:
                    raise ValueError("BROKER_FEE_CONTRACT_FINGERPRINT_CONFLICT")
        result = tuple(new)
        self._components.broker_fee_contracts.validate_installations(result)
        return result

    def _validate_selections(
        self,
        config: OnlyClusterRunConfig,
        installations: tuple[OnlyBrokerFeeContract, ...],
    ) -> None:
        staged = {(item.contract_id, item.contract_version): item for item in installations}
        market_pack = self._components.market_fee_packs.require(
            config.market.fee_pack.pack_id, config.market.fee_pack.pack_version
        )
        market_pack.validate_compatibility(config.market.profile.value)
        for source in config.data_sources:
            if source.enabled:
                self._components.data_sources.resolve(source.plugin_id)
        brokers = {str(item.gateway_id): item for item in config.brokers}
        for broker in config.brokers:
            if broker.enabled:
                self._components.brokers.resolve(broker.plugin_id)
        for account in config.accounts:
            selection = (account.broker_fee_contract.contract_id, account.broker_fee_contract.contract_version)
            contract = staged.get(selection)
            if contract is None:
                contract = self._components.broker_fee_contracts.require(*selection)
            broker = brokers[str(account.gateway_id)]
            contract.validate_compatibility(broker_id=broker.plugin_id, account_id=account.account_id)
            self._components.fee_reconciliation_policies.require(
                account.fee_reconciliation_policy.policy_id,
                account.fee_reconciliation_policy.policy_version,
                account.initial_cash.currency,
            )


__all__ = ["OnlyClusterComposition", "OnlyClusterCompositionPlan"]
