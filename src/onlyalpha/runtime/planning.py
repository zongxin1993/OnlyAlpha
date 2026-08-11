"""Engine-owned Runtime grouping over the canonical environment authority."""

from __future__ import annotations

from dataclasses import dataclass, replace

from onlyalpha.config import OnlyClusterRunConfig, OnlyRuntimeAssemblyPlan
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId, OnlyRuntimeId
from onlyalpha.market.product import OnlyResolvedMarketProductBinding
from onlyalpha.runtime.environment import OnlyRuntimeEnvironmentBuilder, OnlyRuntimeEnvironmentIdentity


@dataclass(frozen=True, slots=True)
class OnlyRuntimePlan:
    runtime_id: OnlyRuntimeId
    environment: OnlyRuntimeEnvironmentIdentity
    cluster_ids: tuple[OnlyClusterId, ...]
    cluster_configs: tuple[OnlyClusterRunConfig, ...]
    assembly_plan: OnlyRuntimeAssemblyPlan
    market_product: OnlyResolvedMarketProductBinding


@dataclass(frozen=True, slots=True)
class OnlyEngineExecutionPlan:
    engine_id: OnlyEngineId
    runtime_plans: tuple[OnlyRuntimePlan, ...]

    @property
    def cluster_count(self) -> int:
        return sum(len(item.cluster_ids) for item in self.runtime_plans)


class OnlyRuntimePlanner:
    """Group configs only; environment semantics belong to the builder."""

    def __init__(self, environment_builder: OnlyRuntimeEnvironmentBuilder | None = None) -> None:
        self._environment_builder = environment_builder or OnlyRuntimeEnvironmentBuilder()

    def plan(
        self,
        engine_id: OnlyEngineId,
        configs: tuple[OnlyClusterRunConfig, ...],
        market_products: dict[OnlyClusterId, OnlyResolvedMarketProductBinding],
    ) -> OnlyEngineExecutionPlan:
        groups: dict[
            OnlyRuntimeEnvironmentIdentity, list[tuple[OnlyClusterRunConfig, OnlyResolvedMarketProductBinding]]
        ] = {}
        for config in configs:
            binding = market_products[config.cluster_id]
            environment = self._environment_builder.build(config, binding)
            groups.setdefault(environment, []).append((config, binding))
        runtime_plans = tuple(
            self._runtime_plan(
                engine_id,
                environment,
                tuple(sorted(group, key=lambda item: str(item[0].cluster_id))),
            )
            for environment, group in sorted(groups.items(), key=lambda item: item[0].fingerprint)
        )
        return OnlyEngineExecutionPlan(engine_id, runtime_plans)

    def _runtime_plan(
        self,
        engine_id: OnlyEngineId,
        environment: OnlyRuntimeEnvironmentIdentity,
        resolved: tuple[tuple[OnlyClusterRunConfig, OnlyResolvedMarketProductBinding], ...],
    ) -> OnlyRuntimePlan:
        if not resolved:
            raise RuntimeError("RUNTIME_GROUPING_INVARIANT_FAILED")
        configs = tuple(item[0] for item in resolved)
        bindings = tuple(item[1] for item in resolved)
        if any(binding.composition_identity != bindings[0].composition_identity for binding in bindings):
            raise RuntimeError("MARKET_PRODUCT_COMPOSITION_GROUPING_INVARIANT_FAILED")
        representative = configs[0]
        runtime_id = OnlyRuntimeId(f"{environment.runtime_type.lower()}-{environment.fingerprint[:16]}")
        assembly = OnlyRuntimeAssemblyPlan(
            representative.schema_version,
            replace(representative.runtime, engine_id=engine_id, runtime_id=runtime_id),
            representative.reference_data,
            representative.universes,
            representative.data_sources,
            representative.accounts,
            representative.brokers,
            representative.market,
            tuple(config.cluster for config in configs),
            representative.output,
            representative.source_path,
            representative.normalized_payload,
            tuple(contract for config in configs for contract in config.broker_fee_contract_authorities),
        )
        assembly.validate_capital_allocation()
        return OnlyRuntimePlan(
            runtime_id,
            environment,
            tuple(config.cluster_id for config in configs),
            configs,
            assembly,
            bindings[0],
        )
