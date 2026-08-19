"""Typed, closed and structurally canonical Boolean authoring AST."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import cast

from onlyalpha.calculation import (
    OnlyCalculationDataType,
    OnlyCalculationScalar,
    only_calculation_scalar_from_dict,
    only_calculation_scalar_to_dict,
)
from onlyalpha.canonical import only_canonical_fingerprint


class OnlyResearchComparisonOperator(StrEnum):
    EQ = "=="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="


@dataclass(frozen=True, order=True, slots=True)
class OnlyResearchDatasetFieldRef:
    field_name: str

    def __post_init__(self) -> None:
        if not self.field_name or any(char.isspace() for char in self.field_name):
            raise ValueError("Dataset field reference is invalid")

    def to_dict(self) -> Mapping[str, object]:
        return {"kind": "DATASET_FIELD", "field_name": self.field_name}


@dataclass(frozen=True, order=True, slots=True)
class OnlyResearchVariableRef:
    instance_key: str
    output_name: str

    def __post_init__(self) -> None:
        _identifier(self.instance_key, "instance_key")
        _identifier(self.output_name, "output_name")

    def to_dict(self) -> Mapping[str, object]:
        return {"kind": "VARIABLE", "instance_key": self.instance_key, "output_name": self.output_name}


@dataclass(frozen=True, slots=True)
class OnlyResearchTypedLiteral:
    data_type: OnlyCalculationDataType
    value: OnlyCalculationScalar

    def __post_init__(self) -> None:
        normalized = _normalize_literal(self.data_type, self.value)
        object.__setattr__(self, "value", normalized)

    def to_dict(self) -> Mapping[str, object]:
        return {
            "kind": "LITERAL",
            "data_type": self.data_type.value,
            "value": only_calculation_scalar_to_dict(self.value),
        }


type OnlyResearchOperand = OnlyResearchDatasetFieldRef | OnlyResearchVariableRef | OnlyResearchTypedLiteral


@dataclass(frozen=True, slots=True)
class OnlyResearchComparison:
    operator: OnlyResearchComparisonOperator
    left: OnlyResearchOperand
    right: OnlyResearchOperand

    def to_dict(self) -> Mapping[str, object]:
        return {
            "kind": "COMPARISON",
            "operator": self.operator.value,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class OnlyResearchNot:
    operand: OnlyResearchBooleanExpression

    def to_dict(self) -> Mapping[str, object]:
        return {"kind": "NOT", "operand": self.operand.to_dict()}


@dataclass(frozen=True, slots=True)
class OnlyResearchAnd:
    operands: tuple[OnlyResearchBooleanExpression, ...]

    def __post_init__(self) -> None:
        if len(self.operands) < 2:
            raise ValueError("AND requires at least two operands")

    def to_dict(self) -> Mapping[str, object]:
        return {"kind": "AND", "operands": [item.to_dict() for item in self.operands]}


@dataclass(frozen=True, slots=True)
class OnlyResearchOr:
    operands: tuple[OnlyResearchBooleanExpression, ...]

    def __post_init__(self) -> None:
        if len(self.operands) < 2:
            raise ValueError("OR requires at least two operands")

    def to_dict(self) -> Mapping[str, object]:
        return {"kind": "OR", "operands": [item.to_dict() for item in self.operands]}


type OnlyResearchBooleanExpression = OnlyResearchComparison | OnlyResearchNot | OnlyResearchAnd | OnlyResearchOr


def only_canonicalize_research_expression(expression: OnlyResearchBooleanExpression) -> OnlyResearchBooleanExpression:
    if isinstance(expression, OnlyResearchComparison):
        return expression
    if isinstance(expression, OnlyResearchNot):
        return OnlyResearchNot(only_canonicalize_research_expression(expression.operand))
    aggregate = OnlyResearchAnd if isinstance(expression, OnlyResearchAnd) else OnlyResearchOr
    flattened: list[OnlyResearchBooleanExpression] = []
    for child in expression.operands:
        canonical = only_canonicalize_research_expression(child)
        if isinstance(canonical, aggregate):
            flattened.extend(canonical.operands)
        else:
            flattened.append(canonical)
    flattened.sort(key=only_research_expression_fingerprint)
    return aggregate(tuple(flattened))


def only_research_expression_fingerprint(expression: OnlyResearchBooleanExpression) -> str:
    return only_canonical_fingerprint(only_canonicalize_research_expression(expression).to_dict())


def only_research_expression_from_dict(payload: Mapping[str, object]) -> OnlyResearchBooleanExpression:
    kind = payload.get("kind")
    if kind == "COMPARISON":
        _exact(payload, {"kind", "operator", "left", "right"})
        return OnlyResearchComparison(
            OnlyResearchComparisonOperator(_string(payload["operator"])),
            _operand(_mapping(payload["left"])),
            _operand(_mapping(payload["right"])),
        )
    if kind == "NOT":
        _exact(payload, {"kind", "operand"})
        return OnlyResearchNot(only_research_expression_from_dict(_mapping(payload["operand"])))
    if kind in {"AND", "OR"}:
        _exact(payload, {"kind", "operands"})
        values = payload["operands"]
        if not isinstance(values, list):
            raise ValueError("expression operands must be an array")
        items = tuple(only_research_expression_from_dict(_mapping(item)) for item in values)
        return OnlyResearchAnd(items) if kind == "AND" else OnlyResearchOr(items)
    raise ValueError("unknown Research expression kind")


def _operand(payload: Mapping[str, object]) -> OnlyResearchOperand:
    kind = payload.get("kind")
    if kind == "DATASET_FIELD":
        _exact(payload, {"kind", "field_name"})
        return OnlyResearchDatasetFieldRef(_string(payload["field_name"]))
    if kind == "VARIABLE":
        _exact(payload, {"kind", "instance_key", "output_name"})
        return OnlyResearchVariableRef(_string(payload["instance_key"]), _string(payload["output_name"]))
    if kind == "LITERAL":
        _exact(payload, {"kind", "data_type", "value"})
        return OnlyResearchTypedLiteral(
            OnlyCalculationDataType(_string(payload["data_type"])),
            only_calculation_scalar_from_dict(payload["value"], "Research literal"),
        )
    raise ValueError("unknown Research operand kind")


def _normalize_literal(data_type: OnlyCalculationDataType, value: object) -> OnlyCalculationScalar:
    if data_type is OnlyCalculationDataType.DECIMAL:
        if isinstance(value, bool):
            raise ValueError("DECIMAL literal is invalid")
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError("DECIMAL literal must be finite")
        return result
    if data_type is OnlyCalculationDataType.INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("INTEGER literal is invalid")
        return value
    if data_type is OnlyCalculationDataType.STRING:
        if not isinstance(value, str):
            raise ValueError("STRING literal is invalid")
        return value
    if not isinstance(value, bool):
        raise ValueError("BOOLEAN literal is invalid")
    return value


def _identifier(value: str, context: str) -> None:
    if not value or any(char.isspace() for char in value):
        raise ValueError(f"{context} is invalid")


def _exact(payload: Mapping[str, object], expected: set[str]) -> None:
    if set(payload) != expected:
        raise ValueError(
            f"expression fields are invalid; missing={sorted(expected - set(payload))}, unknown={sorted(set(payload) - expected)}"
        )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("expression member must be an object")
    return cast(Mapping[str, object], value)


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("expression scalar must be a string")
    return value


__all__ = [name for name in globals() if name.startswith(("Only", "only_"))]
