"""Fail-closed calculation type and backend registry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol, cast, runtime_checkable

from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDefinition,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCalculationTypeDefinition,
    OnlyCalculationTypeReference,
)
from onlyalpha.calculation.implementation import (
    OnlyCalculationImplementationManifest,
    OnlyCalculationStateCapability,
)


@runtime_checkable
class OnlyTradingCalculationBackend(Protocol):
    @property
    def definition(self) -> OnlyCalculationDefinition: ...


class OnlyTradingBackendFactory(Protocol):
    def create(self, definition: OnlyCalculationDefinition, request: object) -> object: ...


@runtime_checkable
class OnlyCalculationDefinitionResolver(Protocol):
    """Backend-neutral full semantic Definition re-materialization contract."""

    @property
    def type_definition(self) -> OnlyCalculationTypeDefinition: ...

    def resolve(
        self,
        parameters: Mapping[str, object],
        input_bindings: Mapping[str, OnlyCalculationReference],
    ) -> OnlyCalculationDefinition: ...


@dataclass(frozen=True, slots=True)
class OnlyCalculationBackendRegistration:
    type_definition: OnlyCalculationTypeDefinition
    backend: OnlyCalculationBackendKind
    provider: object
    definition_resolver: OnlyCalculationDefinitionResolver | None = None
    implementation_manifest: OnlyCalculationImplementationManifest | None = None
    state_capability: OnlyCalculationStateCapability | None = None
    checkpoint_schema_version: int | None = None

    def __post_init__(self) -> None:
        if self.backend is not OnlyCalculationBackendKind.TRADING:
            if self.state_capability is not None or self.checkpoint_schema_version is not None:
                raise ValueError("state capability belongs only to a TRADING Calculation registration")
            return
        if self.state_capability is OnlyCalculationStateCapability.STATELESS:
            if self.checkpoint_schema_version is not None:
                raise ValueError("STATELESS Calculation cannot declare a checkpoint schema")
        elif self.state_capability is OnlyCalculationStateCapability.CHECKPOINTABLE:
            if (
                not isinstance(self.checkpoint_schema_version, int)
                or isinstance(self.checkpoint_schema_version, bool)
                or self.checkpoint_schema_version < 1
            ):
                raise ValueError("CHECKPOINTABLE Calculation requires a positive checkpoint schema version")
        elif self.checkpoint_schema_version is not None:
            raise ValueError("unknown Calculation state capability cannot declare a checkpoint schema")


class OnlyCalculationRegistry:
    def __init__(self) -> None:
        self._registrations: dict[
            tuple[OnlyCalculationKind, str, str, OnlyCalculationBackendKind], OnlyCalculationBackendRegistration
        ] = {}
        self._definition_resolvers: dict[tuple[OnlyCalculationKind, str, str], OnlyCalculationDefinitionResolver] = {}

    def register(self, registration: OnlyCalculationBackendRegistration) -> None:
        definition = registration.type_definition
        key = (definition.kind, definition.type_id, definition.semantic_version, registration.backend)
        if key in self._registrations:
            raise ValueError(f"duplicate calculation backend registration: {key}")
        semantic_key = key[:3]
        existing = tuple(
            item.type_definition
            for registered_key, item in self._registrations.items()
            if registered_key[:3] == semantic_key
        )
        if existing and any(item != definition for item in existing):
            raise ValueError(f"calculation type definition differs across backends: {semantic_key}")
        if registration.provider is None:
            raise TypeError("calculation backend provider is required")
        manifest = registration.implementation_manifest
        if manifest is not None:
            reference = manifest.calculation_type_reference
            if (
                reference.kind is not definition.kind
                or reference.type_id != definition.type_id
                or reference.semantic_version != definition.semantic_version
                or manifest.backend_kind is not registration.backend
            ):
                raise ValueError(f"calculation implementation manifest mismatch: {key}")
        resolver = registration.definition_resolver
        if resolver is not None:
            if not isinstance(resolver, OnlyCalculationDefinitionResolver):
                raise TypeError("calculation Definition resolver contract is invalid")
            if resolver.type_definition != definition:
                raise ValueError(f"calculation Definition resolver type mismatch: {semantic_key}")
            existing_resolver = self._definition_resolvers.get(semantic_key)
            if existing_resolver is not None and existing_resolver != resolver:
                raise ValueError(f"calculation Definition resolver differs across backends: {semantic_key}")
            self._definition_resolvers[semantic_key] = resolver
        self._registrations[key] = registration

    def type_definitions(self) -> tuple[OnlyCalculationTypeDefinition, ...]:
        """List canonical type contracts once in stable semantic-key order."""

        definitions = {
            (
                item.type_definition.kind,
                item.type_definition.type_id,
                item.type_definition.semantic_version,
            ): item.type_definition
            for item in self._registrations.values()
        }
        return tuple(
            definitions[key] for key in sorted(definitions, key=lambda item: tuple(str(part) for part in item))
        )

    def descriptors(self) -> tuple[MappingProxyType[str, object], ...]:
        """Return stable read-only descriptors without provider identity."""

        return cast(
            tuple[MappingProxyType[str, object], ...],
            tuple(
                definition.descriptor()
                for definition in self.type_definitions()
                if definition.kind is not OnlyCalculationKind.PREDICATE
            ),
        )

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

    def resolve_type(self, reference: OnlyCalculationTypeReference) -> OnlyCalculationTypeDefinition:
        """Resolve one exact semantic type without selecting an execution backend."""

        key = (reference.kind, reference.type_id, reference.semantic_version)
        definitions = tuple(
            registration.type_definition
            for registered_key, registration in self._registrations.items()
            if registered_key[:3] == key
        )
        if definitions:
            return next(iter(definitions))
        versions = {item[2] for item in self._registrations if item[:2] == key[:2]}
        if versions:
            raise ValueError(f"unknown semantic version {reference.semantic_version} for {reference.type_id}")
        raise ValueError(f"unknown calculation type: {reference.type_id}")

    def rematerialize_definition(
        self,
        reference: OnlyCalculationTypeReference,
        parameters: Mapping[str, object],
        input_bindings: Mapping[str, OnlyCalculationReference],
    ) -> OnlyCalculationDefinition:
        """Rebuild all parameter-derived semantics through the exact type-owned resolver."""

        definition = self.resolve_type(reference)
        key = (reference.kind, reference.type_id, reference.semantic_version)
        try:
            resolver = self._definition_resolvers[key]
        except KeyError as exc:
            raise ValueError(
                f"calculation Definition resolver is unavailable: {reference.type_id}@{reference.semantic_version}"
            ) from exc
        resolved = resolver.resolve(parameters, input_bindings)
        if (
            resolved.kind is not definition.kind
            or resolved.type_id != definition.type_id
            or resolved.semantic_version != definition.semantic_version
        ):
            raise ValueError("calculation Definition resolver returned a different semantic type")
        return resolved


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
