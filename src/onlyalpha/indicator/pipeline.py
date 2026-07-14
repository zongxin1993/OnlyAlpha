"""Synchronous indicator update barrier and Runtime-owned value cache."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.indicator.base import (
    OnlyIndicatorId,
    OnlyIndicatorRegistration,
    OnlyIndicatorRequirement,
    OnlyIndicatorValue,
)


class OnlyIndicatorPipelineError(Exception):
    """Required indicator could not be prepared for strategy execution."""


@dataclass(frozen=True, slots=True)
class OnlyIndicatorFailure:
    indicator_id: OnlyIndicatorId
    requirement: OnlyIndicatorRequirement
    error: Exception


@dataclass(frozen=True, slots=True)
class OnlyIndicatorUpdateResult:
    updated_indicator_ids: tuple[OnlyIndicatorId, ...]
    failures: tuple[OnlyIndicatorFailure, ...]


class OnlyIndicatorPipeline:
    """Runtime-level shared indicators, updated before Snapshot construction."""

    def __init__(self) -> None:
        self._registrations: dict[OnlyIndicatorId, OnlyIndicatorRegistration] = {}
        self._values: dict[OnlyIndicatorId, OnlyIndicatorValue] = {}
        self._versions: dict[OnlyIndicatorId, int] = {}

    def register(self, registration: OnlyIndicatorRegistration) -> None:
        indicator_id = registration.indicator.indicator_id
        existing = self._registrations.get(indicator_id)
        if existing is not None and existing != registration:
            raise ValueError(f"indicator_id already registered: {indicator_id}")
        self._registrations[indicator_id] = registration

    @property
    def registrations(self) -> tuple[OnlyIndicatorRegistration, ...]:
        return tuple(self._registrations[key] for key in sorted(self._registrations))

    def update(
        self,
        updated_bars: dict[OnlyBarType, OnlyBar],
        histories: dict[OnlyBarType, tuple[OnlyBar, ...]],
    ) -> OnlyIndicatorUpdateResult:
        updated: list[OnlyIndicatorId] = []
        failures: list[OnlyIndicatorFailure] = []
        for registration in self.registrations:
            indicator = registration.indicator
            bar = updated_bars.get(indicator.bar_type)
            if bar is None:
                continue
            try:
                value = indicator.update(bar, histories[indicator.bar_type])
                self._values[indicator.indicator_id] = value
                self._versions[indicator.indicator_id] = self._versions.get(indicator.indicator_id, 0) + 1
                updated.append(indicator.indicator_id)
            except Exception as exc:
                failure = OnlyIndicatorFailure(indicator.indicator_id, registration.requirement, exc)
                failures.append(failure)
                if registration.requirement is OnlyIndicatorRequirement.REQUIRED:
                    raise OnlyIndicatorPipelineError(f"required indicator failed: {indicator.indicator_id}") from exc
                self._values.pop(indicator.indicator_id, None)
        return OnlyIndicatorUpdateResult(tuple(updated), tuple(failures))

    def values(self) -> MappingProxyType[OnlyIndicatorId, OnlyIndicatorValue]:
        return MappingProxyType(dict(self._values))

    def versions(self) -> MappingProxyType[OnlyIndicatorId, int]:
        return MappingProxyType(dict(self._versions))
