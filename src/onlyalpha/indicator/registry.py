"""Factory registry and Factor-scoped mutable indicator store."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeVar

from onlyalpha.domain.identifiers import OnlyClusterId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.factor.identifiers import OnlyFactorId
from onlyalpha.indicator.base import OnlyBarIndicator
from onlyalpha.indicator.factory import OnlyIndicatorCreateRequest, OnlyIndicatorFactory
from onlyalpha.indicator.identifiers import OnlyIndicatorId, OnlyIndicatorTypeId
from onlyalpha.indicator.score import OnlyIndicatorScore
from onlyalpha.indicator.snapshot import OnlyIndicatorSnapshot

OnlySnapshotT = TypeVar("OnlySnapshotT", bound=OnlyIndicatorSnapshot)


@dataclass(frozen=True, order=True, slots=True)
class OnlyIndicatorInstanceKey:
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId
    factor_id: OnlyFactorId
    indicator_id: OnlyIndicatorId


class OnlyIndicatorFactoryRegistry:
    def __init__(self) -> None:
        self._factories: dict[OnlyIndicatorTypeId, OnlyIndicatorFactory] = {}

    def register(self, factory: OnlyIndicatorFactory) -> None:
        key = factory.indicator_type
        if key in self._factories:
            raise ValueError(f"duplicate indicator factory: {key}")
        self._factories[key] = factory

    def create(self, request: OnlyIndicatorCreateRequest) -> OnlyBarIndicator[OnlyIndicatorSnapshot]:
        try:
            factory = self._factories[request.indicator_type]
        except KeyError as exc:
            raise ValueError(f"unknown indicator type: {request.indicator_type}") from exc
        return factory.create(request)


class OnlyIndicatorRegistry:
    """One Cluster's scoped mutable instances; mutation is exposed only to Factors."""

    def __init__(
        self,
        runtime_id: OnlyRuntimeId,
        cluster_id: OnlyClusterId,
        factories: OnlyIndicatorFactoryRegistry,
    ) -> None:
        self._runtime_id = runtime_id
        self._cluster_id = cluster_id
        self._factories = factories
        self._instances: dict[OnlyIndicatorInstanceKey, OnlyBarIndicator[OnlyIndicatorSnapshot]] = {}

    def create_for_bars(
        self,
        factor_id: OnlyFactorId,
        indicator_type: OnlyIndicatorTypeId,
        indicator_id: OnlyIndicatorId,
        bar_type: OnlyBarType,
        parameters: Mapping[str, object],
    ) -> OnlyIndicatorId:
        key = OnlyIndicatorInstanceKey(self._runtime_id, self._cluster_id, factor_id, indicator_id)
        if key in self._instances:
            raise ValueError(f"duplicate scoped indicator: {key}")
        self._instances[key] = self._factories.create(
            OnlyIndicatorCreateRequest(indicator_type, indicator_id, bar_type, parameters)
        )
        return indicator_id

    def update_bar(self, bar: OnlyBar) -> None:
        for key in sorted(self._instances):
            indicator = self._instances[key]
            if indicator.bar_type == bar.bar_type:
                indicator.update_bar(bar)

    def snapshot(self, factor_id: OnlyFactorId, indicator_id: OnlyIndicatorId) -> OnlyIndicatorSnapshot:
        return self._require(factor_id, indicator_id).snapshot()

    def require_snapshot(
        self,
        factor_id: OnlyFactorId,
        indicator_id: OnlyIndicatorId,
        snapshot_type: type[OnlySnapshotT],
    ) -> OnlySnapshotT:
        value = self.snapshot(factor_id, indicator_id)
        if not isinstance(value, snapshot_type):
            raise TypeError(f"indicator {indicator_id} snapshot is not {snapshot_type.__name__}")
        return value

    def score(self, factor_id: OnlyFactorId, indicator_id: OnlyIndicatorId) -> OnlyIndicatorScore | None:
        return self._require(factor_id, indicator_id).canonical_score()

    def all_snapshots(self) -> tuple[OnlyIndicatorSnapshot, ...]:
        return tuple(self._instances[key].snapshot() for key in sorted(self._instances))

    def _require(
        self, factor_id: OnlyFactorId, indicator_id: OnlyIndicatorId
    ) -> OnlyBarIndicator[OnlyIndicatorSnapshot]:
        key = OnlyIndicatorInstanceKey(self._runtime_id, self._cluster_id, factor_id, indicator_id)
        try:
            return self._instances[key]
        except KeyError as exc:
            raise KeyError(f"unknown scoped indicator: {key}") from exc
