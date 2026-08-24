"""TRADING incremental backend for neutral internal Predicate semantics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDefinition,
    OnlyCalculationTypeReference,
)
from onlyalpha.calculation.implementation import (
    OnlyCalculationStateCapability,
    only_python_implementation_manifest,
    only_python_stdlib_semantic_dependency,
)
from onlyalpha.calculation.predicate import (
    PREDICATE_TYPE_PREFIX,
    OnlyPredicateDefinitionResolver,
    only_predicate_compare,
    only_predicate_type_definitions,
)
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration, OnlyCalculationRegistry


class _TradingPredicateBackendFactory:
    def create(self, definition: OnlyCalculationDefinition, request: object) -> object:
        del request
        return _TradingPredicateBackend(definition)


@dataclass(frozen=True, slots=True)
class _TradingPredicateBackend:
    definition: OnlyCalculationDefinition

    def update(self, inputs: Mapping[str, object]) -> Mapping[str, object]:
        name = self.definition.type_id.removeprefix(f"{PREDICATE_TYPE_PREFIX}.")
        if name.startswith("compare."):
            _, operator, _, layout = name.split(".")
            left = inputs["left"]
            right = inputs["right"] if layout == "refs" else self.definition.parameters["literal"]
            if layout != "refs" and bool(self.definition.parameters["literal_left"]):
                left, right = right, left
            if left is None or right is None:
                return {"value": None}
            return {"value": only_predicate_compare(operator, left, right)}
        if name == "boolean.and":
            left, right = inputs["left"], inputs["right"]
            return {"value": False if left is False or right is False else (None if None in (left, right) else True)}
        if name == "boolean.or":
            left, right = inputs["left"], inputs["right"]
            return {"value": True if left is True or right is True else (None if None in (left, right) else False)}
        if name == "boolean.not":
            value = inputs["value"]
            return {"value": None if value is None else not bool(value)}
        if name.startswith("terminal."):
            return {"value": inputs["value"]}
        raise ValueError(f"unknown internal Predicate primitive: {name}")


def only_register_trading_predicate_primitives(registry: OnlyCalculationRegistry) -> None:
    package_root = Path(__file__).resolve().parents[2]
    provider = _TradingPredicateBackendFactory()
    for definition in only_predicate_type_definitions():
        reference = OnlyCalculationTypeReference(
            definition.kind,
            definition.type_id,
            definition.semantic_version,
        )
        registration = OnlyCalculationBackendRegistration(
            definition,
            OnlyCalculationBackendKind.TRADING,
            provider,
            OnlyPredicateDefinitionResolver(definition),
            only_python_implementation_manifest(
                calculation_type_reference=reference,
                backend_kind=OnlyCalculationBackendKind.TRADING,
                entrypoint_identity=("onlyalpha.runtime.trading.predicate:_TradingPredicateBackendFactory"),
                package_root=package_root,
                resource_paths=("calculation/predicate.py", "runtime/trading/predicate.py"),
                semantic_dependencies=(only_python_stdlib_semantic_dependency("decimal"),),
            ),
            OnlyCalculationStateCapability.STATELESS,
        )
        _register_idempotently(registry, registration)


def _register_idempotently(
    registry: OnlyCalculationRegistry,
    registration: OnlyCalculationBackendRegistration,
) -> None:
    definition = registration.type_definition
    try:
        existing = registry.resolve(
            definition.kind,
            definition.type_id,
            definition.semantic_version,
            registration.backend,
        )
    except ValueError as exc:
        if "unknown calculation type" not in str(exc) and "unsupported backend" not in str(exc):
            raise
        registry.register(registration)
    else:
        if (
            existing.type_definition != registration.type_definition
            or existing.backend is not registration.backend
            or type(existing.provider) is not type(registration.provider)
            or existing.definition_resolver != registration.definition_resolver
            or existing.implementation_manifest != registration.implementation_manifest
            or existing.state_capability is not registration.state_capability
        ):
            raise ValueError(f"internal Predicate registration conflicts: {definition.type_id}")


__all__ = ["only_register_trading_predicate_primitives"]
