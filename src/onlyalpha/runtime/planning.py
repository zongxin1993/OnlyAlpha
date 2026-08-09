"""Engine-owned Runtime grouping over the canonical environment authority."""

from __future__ import annotations

from dataclasses import dataclass, replace

from onlyalpha.config import OnlyClusterRunConfig, OnlyRuntimeAssemblyPlan
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId, OnlyRuntimeId
from onlyalpha.runtime.environment import OnlyRuntimeEnvironmentBuilder, OnlyRuntimeEnvironmentIdentity


@dataclass(frozen=True, slots=True)
class OnlyRuntimePlan:
    runtime_id: OnlyRuntimeId
    environment: OnlyRuntimeEnvironmentIdentity
    cluster_ids: tuple[OnlyClusterId, ...]
    cluster_configs: tuple[OnlyClusterRunConfig, ...]
    assembly_plan: OnlyRuntimeAssemblyPlan


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
    ) -> OnlyEngineExecutionPlan:
        groups: dict[OnlyRuntimeEnvironmentIdentity, list[OnlyClusterRunConfig]] = {}
        for config in configs:
            environment = self._environment_builder.build(config)
            groups.setdefault(environment, []).append(config)
        runtime_plans = tuple(
            self._runtime_plan(engine_id, environment, tuple(sorted(group, key=lambda item: str(item.cluster_id))))
            for environment, group in sorted(groups.items(), key=lambda item: item[0].fingerprint)
        )
        return OnlyEngineExecutionPlan(engine_id, runtime_plans)

    def _runtime_plan(
        self,
        engine_id: OnlyEngineId,
        environment: OnlyRuntimeEnvironmentIdentity,
        configs: tuple[OnlyClusterRunConfig, ...],
    ) -> OnlyRuntimePlan:
        if not configs or any(self._environment_builder.build(config) != environment for config in configs):
            raise RuntimeError("RUNTIME_GROUPING_INVARIANT_FAILED")
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
        )
