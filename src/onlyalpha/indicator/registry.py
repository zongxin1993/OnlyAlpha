"""Factory registry and Factor-scoped mutable indicator store."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeVar

from onlyalpha.calculation.definition import OnlyCalculationBackendKind, OnlyCalculationKind
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition, OnlyCalculationNodeDefinition
from onlyalpha.calculation.registry import (
    OnlyCalculationBackendRegistration,
    OnlyCalculationRegistry,
    OnlyTradingCalculationBackendResolver,
)
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.factor.identifiers import OnlyFactorId
from onlyalpha.indicator.base import OnlyBarIndicator
from onlyalpha.indicator.factory import OnlyIndicatorCreateRequest
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
    def __init__(self, calculations: OnlyCalculationRegistry | None = None) -> None:
        self._calculations = calculations or OnlyCalculationRegistry()
        self._trading = OnlyTradingCalculationBackendResolver(self._calculations)
        self._factories: dict[OnlyIndicatorTypeId, OnlyCalculationBackendRegistration] = {}

    def register(self, registration: OnlyCalculationBackendRegistration) -> None:
        if registration.backend is not OnlyCalculationBackendKind.TRADING:
            self._calculations.register(registration)
            return
        factory = registration.provider
        key = getattr(factory, "indicator_type", None)
        if not isinstance(key, OnlyIndicatorTypeId):
            if not callable(getattr(factory, "create", None)):
                raise TypeError("Indicator backend factory must expose indicator_type or create()")
            self._calculations.register(registration)
            return
        if key in self._factories and registration.type_definition.semantic_version == "1":
            raise ValueError(f"duplicate indicator factory: {key}")
        if registration.type_definition.kind is not OnlyCalculationKind.INDICATOR:
            raise TypeError("Indicator registry accepts Indicator definitions only")
        self._calculations.register(registration)
        if registration.type_definition.semantic_version == "1":
            self._factories[key] = registration

    def create(self, request: OnlyIndicatorCreateRequest) -> OnlyBarIndicator[OnlyIndicatorSnapshot]:
        reference = request.calculation_reference
        registration = self._calculations.resolve(
            reference.kind, reference.type_id, reference.semantic_version, OnlyCalculationBackendKind.TRADING
        )
        factory = registration.provider
        resolve_definition = getattr(factory, "resolve_definition", None)
        if not callable(resolve_definition):
            raise TypeError("Indicator backend factory must define resolve_definition()")
        definition = resolve_definition(request.parameters)
        if (definition.kind, definition.type_id, definition.semantic_version) != (
            reference.kind,
            reference.type_id,
            reference.semantic_version,
        ):
            raise ValueError("Indicator backend resolved a definition that does not match the exact reference")
        OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition),))
        indicator = self._trading.create(definition, request)
        if not isinstance(indicator, OnlyBarIndicator):
            raise TypeError("Indicator backend factory returned an invalid trading backend")
        return indicator


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

    @property
    def checkpoint_instances(
        self,
    ) -> tuple[tuple[OnlyIndicatorInstanceKey, OnlyBarIndicator[OnlyIndicatorSnapshot]], ...]:
        return tuple((key, self._instances[key]) for key in sorted(self._instances))

    def _require(
        self, factor_id: OnlyFactorId, indicator_id: OnlyIndicatorId
    ) -> OnlyBarIndicator[OnlyIndicatorSnapshot]:
        key = OnlyIndicatorInstanceKey(self._runtime_id, self._cluster_id, factor_id, indicator_id)
        try:
            return self._instances[key]
        except KeyError as exc:
            raise KeyError(f"unknown scoped indicator: {key}") from exc
