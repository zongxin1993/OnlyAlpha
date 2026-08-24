"""Backend-neutral internal Predicate semantic definitions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.calculation.definition import (
    PREDICATE_OPERAND_SEMANTIC_TYPE,
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

PREDICATE_VALUE_SEMANTIC_TYPE = "PREDICATE_VALUE"
PREDICATE_SEMANTIC_VERSION = "1"
PREDICATE_TYPE_PREFIX = "onlyalpha.predicate.internal"
_OP_NAMES = {"==": "eq", "!=": "ne", "<": "lt", "<=": "le", ">": "gt", ">=": "ge"}


def only_predicate_type_reference(name: str) -> OnlyCalculationTypeReference:
    return OnlyCalculationTypeReference(
        OnlyCalculationKind.PREDICATE,
        f"{PREDICATE_TYPE_PREFIX}.{name}",
        PREDICATE_SEMANTIC_VERSION,
    )


@dataclass(frozen=True, slots=True)
class OnlyPredicateDefinitionResolver:
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


def only_predicate_type_definitions() -> tuple[OnlyCalculationTypeDefinition, ...]:
    definitions: list[OnlyCalculationTypeDefinition] = []
    numeric = (OnlyCalculationDataType.DECIMAL, OnlyCalculationDataType.INTEGER)
    equality = (OnlyCalculationDataType.STRING, OnlyCalculationDataType.BOOLEAN)
    for data_type in (*numeric, *equality):
        operators = tuple(_OP_NAMES) if data_type in numeric else ("==", "!=")
        for operator in operators:
            name = _OP_NAMES[operator]
            definitions.append(_comparison(data_type, name, refs=True))
            definitions.append(_comparison(data_type, name, refs=False))
    boolean_input = OnlyInputDefinition(
        "value",
        OnlyCalculationDataType.BOOLEAN,
        True,
        semantic_type=PREDICATE_VALUE_SEMANTIC_TYPE,
    )
    boolean_output = OnlyOutputDefinition(
        "value",
        OnlyCalculationDataType.BOOLEAN,
        True,
        semantic_type=PREDICATE_VALUE_SEMANTIC_TYPE,
    )
    for name in ("and", "or"):
        definitions.append(
            _type(
                f"boolean.{name}",
                OnlyParameterSchema(),
                (
                    OnlyInputDefinition(
                        "left",
                        boolean_input.data_type,
                        True,
                        semantic_type=boolean_input.semantic_type,
                    ),
                    OnlyInputDefinition(
                        "right",
                        boolean_input.data_type,
                        True,
                        semantic_type=boolean_input.semantic_type,
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
                (
                    OnlyOutputDefinition(
                        "value",
                        OnlyCalculationDataType.BOOLEAN,
                        True,
                        semantic_type=role.upper(),
                    ),
                ),
            )
        )
    return tuple(definitions)


def only_predicate_compare(operator: str, left: object, right: object) -> bool:
    if operator == "eq":
        return left == right
    if operator == "ne":
        return left != right
    if isinstance(left, Decimal) and isinstance(right, Decimal):
        return _ordered(operator, left < right, left <= right, left > right, left >= right)
    if isinstance(left, int) and not isinstance(left, bool) and isinstance(right, int) and not isinstance(right, bool):
        return _ordered(operator, left < right, left <= right, left > right, left >= right)
    if isinstance(left, str) and isinstance(right, str):
        return _ordered(operator, left < right, left <= right, left > right, left >= right)
    raise TypeError("Predicate ordered operands must have the same admitted scalar type")


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


def _comparison(
    data_type: OnlyCalculationDataType,
    operator: str,
    *,
    refs: bool,
) -> OnlyCalculationTypeDefinition:
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
    return _type(
        f"compare.{operator}.{data_name}.literal",
        OnlyParameterSchema(
            (
                OnlyParameterDefinition("literal", OnlyParameterType(data_type.value)),
                OnlyParameterDefinition("literal_left", OnlyParameterType.BOOLEAN, False, False),
            )
        ),
        (operand("left"),),
        (_predicate_output(),),
    )


def _predicate_output() -> OnlyOutputDefinition:
    return OnlyOutputDefinition(
        "value",
        OnlyCalculationDataType.BOOLEAN,
        True,
        semantic_type=PREDICATE_VALUE_SEMANTIC_TYPE,
    )


def _type(
    name: str,
    parameters: OnlyParameterSchema,
    inputs: tuple[OnlyInputDefinition, ...],
    outputs: tuple[OnlyOutputDefinition, ...],
) -> OnlyCalculationTypeDefinition:
    return OnlyCalculationTypeDefinition(
        OnlyCalculationKind.PREDICATE,
        f"{PREDICATE_TYPE_PREFIX}.{name}",
        PREDICATE_SEMANTIC_VERSION,
        parameters,
        inputs,
        outputs,
        OnlyMissingValuePolicy.PROPAGATE,
        OnlyTimestampSemantic.EVENT_TIME,
        OnlyNumericDefinition(representation="BOOLEAN", precision=1),
    )


__all__ = [name for name in globals() if name.startswith(("Only", "only_", "PREDICATE_"))]
