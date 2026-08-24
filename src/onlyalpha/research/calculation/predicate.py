"""Internal RESEARCH Predicate Calculation primitives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]

from onlyalpha.calculation import (
    PREDICATE_OPERAND_SEMANTIC_TYPE,
    OnlyCalculationBackendKind,
    OnlyCalculationDataType,
    OnlyCalculationDefinition,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCalculationTypeDefinition,
    OnlyCalculationTypeReference,
    OnlyInputDefinition,
    OnlyMissingValuePolicy,
    OnlyNumericDefinition,
    OnlyOutputDefinition,
    OnlyParameterDefinition,
    OnlyParameterSchema,
    OnlyParameterType,
    OnlyPreReadyOutput,
    OnlyTimestampSemantic,
    OnlyWarmupDefinition,
)
from onlyalpha.calculation.implementation import only_python_implementation_manifest
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration, OnlyCalculationRegistry

PREDICATE_VALUE_SEMANTIC_TYPE = "PREDICATE_VALUE"
PREDICATE_SEMANTIC_VERSION = "1"
_PREFIX = "onlyalpha.predicate.internal"
_OP_NAMES = {"==": "eq", "!=": "ne", "<": "lt", "<=": "le", ">": "gt", ">=": "ge"}


def only_research_predicate_type_reference(name: str) -> OnlyCalculationTypeReference:
    return OnlyCalculationTypeReference(OnlyCalculationKind.PREDICATE, f"{_PREFIX}.{name}", PREDICATE_SEMANTIC_VERSION)


def only_register_research_predicate_primitives(registry: OnlyCalculationRegistry) -> None:
    """Install exact internal RESEARCH registrations into the existing authority."""

    for registration in _registrations():
        definition = registration.type_definition
        try:
            existing = registry.resolve(
                definition.kind, definition.type_id, definition.semantic_version, registration.backend
            )
        except ValueError as exc:
            if "unknown calculation type" not in str(exc) and "unsupported backend" not in str(exc):
                raise
            registry.register(registration)
        else:
            if existing.type_definition != definition:
                raise ValueError(f"internal Predicate type conflicts with registry: {definition.type_id}")


@dataclass(frozen=True, slots=True)
class _Resolver:
    type_definition: OnlyCalculationTypeDefinition

    def resolve(
        self,
        parameters: Mapping[str, object],
        input_bindings: Mapping[str, OnlyCalculationReference],
    ) -> OnlyCalculationDefinition:
        return self.type_definition.resolve(
            parameters,
            input_bindings,
            OnlyWarmupDefinition(1, "predicate operands are available", OnlyPreReadyOutput.NULL, "UPSTREAM"),
        )


class _Backend:
    def execute(
        self,
        definition: OnlyCalculationDefinition,
        inputs: Mapping[str, pa.Array | pa.ChunkedArray],
    ) -> Mapping[str, pa.Array | pa.ChunkedArray]:
        name = definition.type_id.removeprefix(f"{_PREFIX}.")
        if name.startswith("compare."):
            _, operator, _, layout = name.split(".")
            function = {
                "eq": pc.equal,
                "ne": pc.not_equal,
                "lt": pc.less,
                "le": pc.less_equal,
                "gt": pc.greater,
                "ge": pc.greater_equal,
            }[operator]
            left = inputs["left"]
            if layout == "refs":
                right: pa.Array | pa.ChunkedArray | pa.Scalar = inputs["right"]
            else:
                right = pa.scalar(definition.parameters["literal"], type=left.type)
                if definition.parameters["literal_left"]:
                    return {"value": function(right, left)}
            return {"value": function(left, right)}
        if name == "boolean.and":
            return {"value": pc.and_kleene(inputs["left"], inputs["right"])}
        if name == "boolean.or":
            return {"value": pc.or_kleene(inputs["left"], inputs["right"])}
        if name == "boolean.not":
            return {"value": pc.invert(inputs["value"])}
        if name.startswith("terminal."):
            return {"value": inputs["value"]}
        raise ValueError(f"unknown internal Predicate primitive: {name}")


class _TradingBackendFactory:
    def create(self, definition: OnlyCalculationDefinition, request: object) -> object:
        del request
        return _TradingBackend(definition)


@dataclass(frozen=True, slots=True)
class _TradingBackend:
    definition: OnlyCalculationDefinition

    def update(self, inputs: Mapping[str, object]) -> Mapping[str, object]:
        name = self.definition.type_id.removeprefix(f"{_PREFIX}.")
        if name.startswith("compare."):
            _, operator, _, layout = name.split(".")
            left = inputs["left"]
            right = inputs["right"] if layout == "refs" else self.definition.parameters["literal"]
            if layout != "refs" and bool(self.definition.parameters["literal_left"]):
                left, right = right, left
            if left is None or right is None:
                return {"value": None}
            return {"value": _compare(operator, left, right)}
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


def _registrations() -> tuple[OnlyCalculationBackendRegistration, ...]:
    definitions: list[OnlyCalculationTypeDefinition] = []
    numeric = (OnlyCalculationDataType.DECIMAL, OnlyCalculationDataType.INTEGER)
    equality = (OnlyCalculationDataType.STRING, OnlyCalculationDataType.BOOLEAN)
    for data_type in (*numeric, *equality):
        operators = tuple(_OP_NAMES) if data_type in numeric else ("==", "!=")
        for operator in operators:
            op = _OP_NAMES[operator]
            definitions.append(_comparison(data_type, op, refs=True))
            definitions.append(_comparison(data_type, op, refs=False))
    boolean_input = OnlyInputDefinition(
        "value", OnlyCalculationDataType.BOOLEAN, True, semantic_type=PREDICATE_VALUE_SEMANTIC_TYPE
    )
    boolean_output = OnlyOutputDefinition(
        "value", OnlyCalculationDataType.BOOLEAN, True, semantic_type=PREDICATE_VALUE_SEMANTIC_TYPE
    )
    for name in ("and", "or"):
        definitions.append(
            _type(
                f"boolean.{name}",
                OnlyParameterSchema(),
                (
                    boolean_input.__class__(
                        "left", boolean_input.data_type, True, semantic_type=boolean_input.semantic_type
                    ),
                    boolean_input.__class__(
                        "right", boolean_input.data_type, True, semantic_type=boolean_input.semantic_type
                    ),
                ),
                (boolean_output,),
            )
        )
    definitions.append(_type("boolean.not", OnlyParameterSchema(), (boolean_input,), (boolean_output,)))
    for role in ("eligibility", "entry_signal", "exit_signal"):
        definitions.append(
            _type(
                f"terminal.{role}",
                OnlyParameterSchema(),
                (boolean_input,),
                (OnlyOutputDefinition("value", OnlyCalculationDataType.BOOLEAN, True, semantic_type=role.upper()),),
            )
        )
    backend = _Backend()
    trading = _TradingBackendFactory()
    package_root = Path(__file__).resolve().parent
    registrations: list[OnlyCalculationBackendRegistration] = []
    for item in definitions:
        reference = OnlyCalculationTypeReference(item.kind, item.type_id, item.semantic_version)
        resolver = _Resolver(item)
        registrations.extend(
            (
                OnlyCalculationBackendRegistration(
                    item,
                    OnlyCalculationBackendKind.RESEARCH,
                    backend,
                    resolver,
                    only_python_implementation_manifest(
                        calculation_type_reference=reference,
                        backend_kind=OnlyCalculationBackendKind.RESEARCH,
                        entrypoint_identity="onlyalpha.research.calculation.predicate:_Backend",
                        package_root=package_root,
                        resource_paths=("predicate.py",),
                    ),
                ),
                OnlyCalculationBackendRegistration(
                    item,
                    OnlyCalculationBackendKind.TRADING,
                    trading,
                    resolver,
                    only_python_implementation_manifest(
                        calculation_type_reference=reference,
                        backend_kind=OnlyCalculationBackendKind.TRADING,
                        entrypoint_identity="onlyalpha.research.calculation.predicate:_TradingBackendFactory",
                        package_root=package_root,
                        resource_paths=("predicate.py",),
                    ),
                ),
            )
        )
    return tuple(registrations)


def _compare(operator: str, left: object, right: object) -> bool:
    if operator == "eq":
        return left == right
    if operator == "ne":
        return left != right
    if isinstance(left, Decimal) and isinstance(right, Decimal):
        return _ordered_decimal(operator, left, right)
    if isinstance(left, int) and not isinstance(left, bool) and isinstance(right, int) and not isinstance(right, bool):
        return _ordered_int(operator, left, right)
    if isinstance(left, str) and isinstance(right, str):
        return _ordered_str(operator, left, right)
    raise TypeError("Predicate ordered operands must have the same admitted scalar type")


def _ordered_decimal(operator: str, first: Decimal, second: Decimal) -> bool:
    return _ordered(operator, first < second, first <= second, first > second, first >= second)


def _ordered_int(operator: str, first: int, second: int) -> bool:
    return _ordered(operator, first < second, first <= second, first > second, first >= second)


def _ordered_str(operator: str, first: str, second: str) -> bool:
    return _ordered(operator, first < second, first <= second, first > second, first >= second)


def _ordered(operator: str, less: bool, less_equal: bool, greater: bool, greater_equal: bool) -> bool:
    if operator == "lt":
        return less
    if operator == "le":
        return less_equal
    if operator == "gt":
        return greater
    if operator == "ge":
        return greater_equal
    raise ValueError(f"unknown comparison operator: {operator}")


def _comparison(data_type: OnlyCalculationDataType, operator: str, *, refs: bool) -> OnlyCalculationTypeDefinition:
    data_name = data_type.value.lower()

    def operand(name: str) -> OnlyInputDefinition:
        return OnlyInputDefinition(name, data_type, True, semantic_type=PREDICATE_OPERAND_SEMANTIC_TYPE)

    if refs:
        return _type(
            f"compare.{operator}.{data_name}.refs",
            OnlyParameterSchema(),
            (operand("left"), operand("right")),
            (_predicate_output(),),
        )
    parameter_type = OnlyParameterType(data_type.value)
    parameters = OnlyParameterSchema(
        (
            OnlyParameterDefinition("literal", parameter_type),
            OnlyParameterDefinition("literal_left", OnlyParameterType.BOOLEAN, False, False),
        )
    )
    return _type(f"compare.{operator}.{data_name}.literal", parameters, (operand("left"),), (_predicate_output(),))


def _predicate_output() -> OnlyOutputDefinition:
    return OnlyOutputDefinition(
        "value", OnlyCalculationDataType.BOOLEAN, True, semantic_type=PREDICATE_VALUE_SEMANTIC_TYPE
    )


def _type(
    name: str,
    parameters: OnlyParameterSchema,
    inputs: tuple[OnlyInputDefinition, ...],
    outputs: tuple[OnlyOutputDefinition, ...],
) -> OnlyCalculationTypeDefinition:
    return OnlyCalculationTypeDefinition(
        OnlyCalculationKind.PREDICATE,
        f"{_PREFIX}.{name}",
        PREDICATE_SEMANTIC_VERSION,
        parameters,
        inputs,
        outputs,
        OnlyMissingValuePolicy.PROPAGATE,
        OnlyTimestampSemantic.EVENT_TIME,
        OnlyNumericDefinition(representation="BOOLEAN", precision=1),
    )


__all__ = [
    "PREDICATE_SEMANTIC_VERSION",
    "PREDICATE_VALUE_SEMANTIC_TYPE",
    "only_register_research_predicate_primitives",
    "only_research_predicate_type_reference",
]
