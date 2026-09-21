"""Staged Cluster composition with a single mutation boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.engine.infrastructure import OnlyInfrastructureRegistry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContract
from onlyalpha.fee.market_pack import OnlyMarketFeePack
from onlyalpha.market.product import (
    OnlyMarketProductResolutionContext,
    OnlyMarketProductResourceResolver,
    OnlyMarketReferenceAuthority,
    OnlyResolvedMarketProductBinding,
)
from onlyalpha.plugin.capabilities import OnlyBrokerPluginCapabilities, OnlyDataSourceCapabilities
from onlyalpha.runtime.broker_integration import (
    only_admit_broker_runtime_configuration,
    only_resolve_broker_runtime_factory,
)
from onlyalpha.runtime.data_source_integration import only_admit_data_source_runtime_configuration
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
    market_product: OnlyResolvedMarketProductBinding
    fingerprint: str


class _NoExternalMarketProductResources(OnlyMarketProductResourceResolver):
    """Products build their plugin-owned authorities from typed config."""

    def require_reference_authority(self, resource_id: str) -> OnlyMarketReferenceAuthority:
        raise ValueError(f"EXTERNAL_MARKET_REFERENCE_RESOURCE_NOT_CONFIGURED: {resource_id}")

    def require_market_fee_pack(self, pack_id: str, pack_version: str) -> OnlyMarketFeePack:
        raise ValueError(f"EXTERNAL_MARKET_FEE_RESOURCE_NOT_CONFIGURED: {pack_id}@{pack_version}")


class OnlyClusterComposition:
    """Validate all business failures before committing append-only authorities."""

    def __init__(
        self,
        infrastructure: OnlyInfrastructureRegistry,
        components: OnlyComponentFactoryRegistries,
        environment_builder: OnlyRuntimeEnvironmentBuilder | None = None,
        *,
        recovery: bool = False,
    ) -> None:
        self._infrastructure = infrastructure
        self._components = components
        self._environment_builder = environment_builder or OnlyRuntimeEnvironmentBuilder()
        self._recovery = recovery

    def plan(self, config: OnlyClusterRunConfig) -> OnlyClusterCompositionPlan:
        config = self._admit_integrations(config)
        market_product = self._components.market_products.resolve(
            config.market,
            OnlyMarketProductResolutionContext(
                self._components.market_product_resources or _NoExternalMarketProductResources(),
                config.reference_data.instruments,
            ),
        )
        environment = self._environment_builder.build(config, market_product)
        claims = self._environment_builder.resource_claims(config, market_product)
        self._infrastructure.validate(config.cluster_id, claims)
        installations = self._new_contracts(config.broker_fee_contract_authorities)
        self._validate_selections(config, installations)
        fingerprint = only_canonical_fingerprint(
            {
                "cluster_id": str(config.cluster_id),
                "environment": environment,
                "claims": claims,
                "authorities": tuple(item.fingerprint for item in installations),
                "market_product": market_product.composition_identity,
            }
        )
        return OnlyClusterCompositionPlan(config, environment, claims, installations, market_product, fingerprint)

    def _admit_integrations(self, config: OnlyClusterRunConfig) -> OnlyClusterRunConfig:
        required = (
            OnlyDataSourceCapabilities(historical_bars=True)
            if config.runtime_type == "BACKTEST"
            else OnlyDataSourceCapabilities(
                historical_bars=True,
                live_bars=True,
                live_reconnect=True,
            )
        )
        admitted = tuple(
            only_admit_data_source_runtime_configuration(
                source,
                self._components.integration_runtime_resolver,
                required,
                recovery=self._recovery,
            )
            if source.enabled
            else source
            for source in config.data_sources
        )
        live = config.runtime_type == "LIVE"
        required_broker_capabilities = self._required_broker_capabilities(live)
        admitted_brokers = tuple(
            only_admit_broker_runtime_configuration(
                broker,
                self._components.integration_runtime_resolver,
                required_broker_capabilities,
                recovery=self._recovery,
                require_current_revision=live,
                require_ready_probe=live,
            )
            if broker.enabled
            else broker
            for broker in config.brokers
        )
        if admitted == config.data_sources and admitted_brokers == config.brokers:
            return config
        payload = json.loads(json.dumps(dict(config.normalized_payload)))
        for raw, source in zip(payload["data_sources"], admitted, strict=True):
            if source.integration_binding is not None:
                raw["integration"] = dict(source.integration_binding)
        for raw, broker in zip(payload["brokers"], admitted_brokers, strict=True):
            if broker.integration_binding is not None:
                raw["integration"] = dict(broker.integration_binding)
        return OnlyClusterRunConfig.from_mapping(payload, source_path=config.source_path)

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
        for source in config.data_sources:
            if source.enabled:
                if source.plugin_id:
                    self._components.data_sources.resolve(source.plugin_id)
        brokers = {str(item.gateway_id): item for item in config.brokers}
        for broker in config.brokers:
            if broker.enabled and broker.plugin_id:
                self._components.brokers.resolve(broker.plugin_id)
        for account in config.accounts:
            selection = (account.broker_fee_contract.contract_id, account.broker_fee_contract.contract_version)
            contract = staged.get(selection)
            if contract is None:
                contract = self._components.broker_fee_contracts.require(*selection)
            broker = brokers[str(account.gateway_id)]
            broker_identity = broker.plugin_id
            if not broker_identity and broker.integration_binding is not None:
                factory = only_resolve_broker_runtime_factory(
                    broker,
                    self._components.brokers,
                    self._components.integration_runtime_resolver,
                    self._required_broker_capabilities(config.runtime_type == "LIVE"),
                )
                broker_identity = factory.descriptor.plugin_id
            contract.validate_compatibility(broker_id=broker_identity, account_id=account.account_id)
            self._components.fee_reconciliation_policies.require(
                account.fee_reconciliation_policy.policy_id,
                account.fee_reconciliation_policy.policy_version,
                account.initial_cash.currency,
            )

    @staticmethod
    def _required_broker_capabilities(live: bool) -> OnlyBrokerPluginCapabilities:
        return OnlyBrokerPluginCapabilities(
            submit_order=live,
            cancel_order=live,
            query_orders=live,
            query_trades=live,
            query_positions=live,
            live_execution=live,
        )


__all__ = ["OnlyClusterComposition", "OnlyClusterCompositionPlan"]
