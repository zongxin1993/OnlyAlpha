"""Engine-owned Runtime compatibility planning models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace

from onlyalpha.config import OnlyClusterRunConfig, OnlyRuntimeAssemblyPlan
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId, OnlyRuntimeId


@dataclass(frozen=True, slots=True)
class OnlyRuntimeCompatibilityKey:
    runtime_type: str
    start_time: str
    end_time: str
    clock_policy: str
    replay_policy: str
    data_version: str
    broker_environment: str
    account_environment: str
    market_environment: str

    @classmethod
    def from_config(cls, config: OnlyClusterRunConfig) -> OnlyRuntimeCompatibilityKey:
        source_versions = ",".join(sorted(str(item.data_version) for item in config.data_sources))
        broker_environment = _fingerprint(
            tuple(
                {
                    "gateway_id": str(item.gateway_id),
                    "plugin": item.plugin_id,
                    "enabled": item.enabled,
                    "extensions": dict(item.extensions),
                }
                for item in config.brokers
            )
        )
        account_environment = _fingerprint(
            tuple(
                {
                    "account_id": str(item.account_id),
                    "gateway_id": str(item.gateway_id),
                    "initial_cash": item.initial_cash.to_dict(),
                }
                for item in config.accounts
            )
        )
        replay = config.runtime.extensions.get("replay", {})
        return cls(
            config.runtime_type,
            "" if config.start_time is None else config.start_time.isoformat(),
            "" if config.end_time is None else config.end_time.isoformat(),
            "HISTORICAL_REPLAY" if config.runtime_type == "BACKTEST" else "LIVE_CLOCK",
            _fingerprint(replay),
            source_versions,
            broker_environment,
            account_environment,
            _fingerprint(
                {
                    "profile": config.market.profile.value,
                    "version": config.market.version,
                    "overrides": dict(config.market.overrides),
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class OnlyRuntimePlan:
    runtime_id: OnlyRuntimeId
    compatibility_key: OnlyRuntimeCompatibilityKey
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
    """Groups compatible Cluster definitions and creates assembly plans."""

    def plan(
        self,
        engine_id: OnlyEngineId,
        configs: tuple[OnlyClusterRunConfig, ...],
    ) -> OnlyEngineExecutionPlan:
        groups: dict[OnlyRuntimeCompatibilityKey, list[OnlyClusterRunConfig]] = {}
        for config in configs:
            groups.setdefault(OnlyRuntimeCompatibilityKey.from_config(config), []).append(config)
        runtime_plans = tuple(
            self._runtime_plan(engine_id, key, tuple(sorted(group, key=lambda item: str(item.cluster_id))))
            for key, group in sorted(groups.items(), key=lambda item: _fingerprint(item[0]))
        )
        return OnlyEngineExecutionPlan(engine_id, runtime_plans)

    @staticmethod
    def _runtime_plan(
        engine_id: OnlyEngineId,
        key: OnlyRuntimeCompatibilityKey,
        configs: tuple[OnlyClusterRunConfig, ...],
    ) -> OnlyRuntimePlan:
        first = configs[0]
        runtime_id = OnlyRuntimeId(f"{key.runtime_type.lower()}-{_fingerprint(key)[:16]}")
        assembly = OnlyRuntimeAssemblyPlan(
            first.schema_version,
            replace(first.runtime, engine_id=engine_id, runtime_id=runtime_id),
            first.reference_data,
            first.universes,
            first.data_sources,
            first.accounts,
            first.brokers,
            first.market,
            tuple(config.cluster for config in configs),
            first.output,
            first.source_path,
            first.normalized_payload,
        )
        assembly.validate_capital_allocation()
        return OnlyRuntimePlan(
            runtime_id,
            key,
            tuple(config.cluster_id for config in configs),
            configs,
            assembly,
        )


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
