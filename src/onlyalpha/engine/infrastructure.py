"""Shared infrastructure compatibility and reference accounting."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from onlyalpha.config import (
    OnlyAccountRuntimeConfig,
    OnlyBrokerRuntimeConfig,
    OnlyClusterRunConfig,
    OnlyDataSourceRuntimeConfig,
)


class OnlyResourceConfigurationConflict(ValueError):
    pass


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

    @classmethod
    def from_config(cls, config: OnlyClusterRunConfig) -> OnlyRuntimeCompatibilityKey:
        run = config.run_config
        source_versions = ",".join(sorted(str(item.data_version) for item in run.data_sources))
        broker_environment = _fingerprint(tuple(_broker_projection(item) for item in run.brokers))
        account_environment = _fingerprint(tuple(_account_projection(item) for item in run.accounts))
        replay = run.runtime.extensions.get("replay", {})
        return cls(
            run.runtime.runtime_type,
            "" if run.start_time is None else run.start_time.isoformat(),
            "" if run.end_time is None else run.end_time.isoformat(),
            "HISTORICAL_REPLAY" if run.runtime.runtime_type == "BACKTEST" else "LIVE_CLOCK",
            _fingerprint(replay),
            source_versions,
            broker_environment,
            account_environment,
        )


@dataclass(slots=True)
class _OnlyResourceRecord:
    fingerprint: str
    reference_count: int


class OnlyInfrastructureRegistry:
    """Rejects conflicting IDs and releases resources only at zero references."""

    def __init__(self) -> None:
        self._records: dict[str, _OnlyResourceRecord] = {}
        self._cluster_resources: dict[str, tuple[str, ...]] = {}

    def acquire(self, config: OnlyClusterRunConfig) -> tuple[str, ...]:
        cluster_key = str(config.cluster_id)
        if cluster_key in self._cluster_resources:
            raise ValueError(f"resources already acquired for {cluster_key}")
        resources = self._resource_projections(config)
        conflicts = [
            key
            for key, projection in resources
            if key in self._records and self._records[key].fingerprint != _fingerprint(projection)
        ]
        if conflicts:
            raise OnlyResourceConfigurationConflict(f"RESOURCE_CONFIGURATION_CONFLICT: {', '.join(sorted(conflicts))}")
        keys = []
        for key, projection in resources:
            fingerprint = _fingerprint(projection)
            record = self._records.get(key)
            if record is None:
                self._records[key] = _OnlyResourceRecord(fingerprint, 1)
            else:
                record.reference_count += 1
            keys.append(key)
        self._cluster_resources[cluster_key] = tuple(keys)
        return tuple(keys)

    def release(self, cluster_id: object) -> tuple[str, ...]:
        keys = self._cluster_resources.pop(str(cluster_id), ())
        released = []
        for key in keys:
            record = self._records[key]
            record.reference_count -= 1
            if record.reference_count == 0:
                del self._records[key]
                released.append(key)
        return tuple(released)

    @property
    def reference_counts(self) -> tuple[tuple[str, int], ...]:
        return tuple((key, self._records[key].reference_count) for key in sorted(self._records))

    @staticmethod
    def _resource_projections(config: OnlyClusterRunConfig) -> tuple[tuple[str, object], ...]:
        run = config.run_config
        values: list[tuple[str, object]] = []
        values.extend((f"calendar:{item.calendar_id}", item.to_dict()) for item in run.reference_data.calendars)
        values.extend((f"instrument:{item.instrument_id}", item.to_dict()) for item in run.reference_data.instruments)
        values.extend((f"data_source:{item.source_id}", _source_projection(item)) for item in run.data_sources)
        values.extend((f"broker:{item.gateway_id}", _broker_projection(item)) for item in run.brokers)
        values.extend((f"account:{item.account_id}", _account_projection(item)) for item in run.accounts)
        return tuple(values)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _source_projection(value: OnlyDataSourceRuntimeConfig) -> object:
    return {
        "type": value.source_type,
        "version": str(value.data_version),
        "coverage": value.coverage,
        "extensions": dict(value.extensions),
    }


def _broker_projection(value: OnlyBrokerRuntimeConfig) -> object:
    return {
        "type": value.gateway_type,
        "extensions": dict(value.extensions),
    }


def _account_projection(value: OnlyAccountRuntimeConfig) -> object:
    return {
        "gateway_id": str(value.gateway_id),
        "initial_cash": value.initial_cash.to_dict(),
    }
