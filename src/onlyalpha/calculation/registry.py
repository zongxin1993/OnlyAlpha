"""Fail-closed calculation type and backend registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast, runtime_checkable

from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDefinition,
    OnlyCalculationKind,
    OnlyCalculationTypeDefinition,
)


@runtime_checkable
class OnlyTradingCalculationBackend(Protocol):
    @property
    def definition(self) -> OnlyCalculationDefinition: ...


class OnlyTradingBackendFactory(Protocol):
    def create(self, definition: OnlyCalculationDefinition, request: object) -> object: ...


@dataclass(frozen=True, slots=True)
class OnlyCalculationBackendRegistration:
    type_definition: OnlyCalculationTypeDefinition
    backend: OnlyCalculationBackendKind
    provider: object


class OnlyCalculationRegistry:
    def __init__(self) -> None:
        self._registrations: dict[
            tuple[OnlyCalculationKind, str, str, OnlyCalculationBackendKind], OnlyCalculationBackendRegistration
        ] = {}

    def register(self, registration: OnlyCalculationBackendRegistration) -> None:
        definition = registration.type_definition
        key = (definition.kind, definition.type_id, definition.semantic_version, registration.backend)
        if key in self._registrations:
            raise ValueError(f"duplicate calculation backend registration: {key}")
        if registration.provider is None:
            raise TypeError("calculation backend provider is required")
        self._registrations[key] = registration

    def resolve(
        self,
        kind: OnlyCalculationKind,
        type_id: str,
        semantic_version: str,
        backend: OnlyCalculationBackendKind,
    ) -> OnlyCalculationBackendRegistration:
        key = (kind, type_id, semantic_version, backend)
        try:
            return self._registrations[key]
        except KeyError as exc:
            versions = {
                item[2] for item in self._registrations if item[0] is kind and item[1] == type_id and item[3] is backend
            }
            if versions:
                raise ValueError(f"unknown semantic version {semantic_version} for {type_id}") from exc
            backends = {item[3] for item in self._registrations if item[0] is kind and item[1] == type_id}
            if backends:
                raise ValueError(f"unsupported backend {backend} for {type_id}@{semantic_version}") from exc
            raise ValueError(f"unknown calculation type: {type_id}") from exc


class OnlyTradingCalculationBackendResolver:
    """Trading-only provider validation and mutable instance construction."""

    def __init__(self, registry: OnlyCalculationRegistry) -> None:
        self._registry = registry

    def create(self, definition: OnlyCalculationDefinition, request: object) -> object:
        registration = self._registry.resolve(
            definition.kind,
            definition.type_id,
            definition.semantic_version,
            OnlyCalculationBackendKind.TRADING,
        )
        provider = registration.provider
        if not callable(getattr(provider, "create", None)):
            raise TypeError("TRADING calculation backend provider must define create()")
        return cast(OnlyTradingBackendFactory, provider).create(definition, request)
