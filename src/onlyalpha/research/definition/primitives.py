"""Internal RESEARCH Predicate Calculation primitives for Definition lowering."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

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
    return tuple(
        OnlyCalculationBackendRegistration(item, OnlyCalculationBackendKind.RESEARCH, backend, _Resolver(item))
        for item in definitions
    )


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
