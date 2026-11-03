"""Pure stable calculate(api, inputs, parameters) AST and exact numerical API."""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation.decimal_execution import ONLY_DECIMAL_EXECUTION_POLICY_V1
from onlyalpha.calculation.definition import OnlyCalculationDataType, OnlyNumericDefinition, OnlyOutputDefinition
from onlyalpha.calculation.value_semantics import OnlyCanonicalValueSemanticsV1
from onlyalpha.canonical import only_canonical_fingerprint

_OPERATIONS = (
    "add",
    "and_",
    "coalesce",
    "div",
    "eq",
    "ge",
    "gt",
    "is_missing",
    "le",
    "lt",
    "max",
    "min",
    "mul",
    "ne",
    "negate",
    "not_",
    "or_",
    "sub",
    "where",
)
ONLY_PRIVATE_FACTOR_NUMERIC_V1 = OnlyNumericDefinition(
    representation="DECIMAL",
    precision=38,
    output_quantum=Decimal("0.000000000001"),
    rounding=ROUND_HALF_EVEN,
)


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorApiContractV1:
    api_version: int = 1
    contract_name: str = "ONLYALPHA_PRIVATE_FACTOR_API_V1"

    @property
    def api_contract_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "contract": self.contract_name,
                "api_version": self.api_version,
                "operations": list(_OPERATIONS),
                "values": "NONE_OR_EXACT_DECIMAL_INTEGER_BOOLEAN",
                "missing": "NONE_PROPAGATES_EXCEPT_IS_MISSING_COALESCE_AND_OR",
                "division_by_zero": "NONE",
                "condition": "TRUE_FALSE_NONE;NONE_RETURNS_NONE",
                "ordering": "DECLARED_OUTPUT_ORDER",
                "errors": "INVALID_VALUE_OR_EXECUTION_FAILED",
                "decimal_execution_policy": ONLY_DECIMAL_EXECUTION_POLICY_V1.fingerprint,
                "numeric": {
                    "representation": ONLY_PRIVATE_FACTOR_NUMERIC_V1.representation,
                    "precision": ONLY_PRIVATE_FACTOR_NUMERIC_V1.precision,
                    "output_quantum": str(ONLY_PRIVATE_FACTOR_NUMERIC_V1.output_quantum),
                    "rounding": ONLY_PRIVATE_FACTOR_NUMERIC_V1.rounding,
                },
                "determinism": "STATELESS_POINTWISE",
            }
        )


ONLY_PRIVATE_FACTOR_API_V1 = OnlyPrivateFactorApiContractV1()


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorValidationPolicyV1:
    policy_name: str = "ONLYALPHA_PRIVATE_FACTOR_VALIDATION_V1"

    @property
    def validation_policy_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "policy": self.policy_name,
                "entrypoint": "calculate(api, inputs, parameters)",
                "allowed_operations": list(_OPERATIONS),
                "imports": False,
                "helpers": False,
                "builtins": False,
                "state": False,
            }
        )


ONLY_PRIVATE_FACTOR_VALIDATION_POLICY_V1 = OnlyPrivateFactorValidationPolicyV1()


class _SourcePolicy(ast.NodeVisitor):
    _allowed = (
        ast.Module,
        ast.FunctionDef,
        ast.arguments,
        ast.arg,
        ast.Assign,
        ast.Return,
        ast.If,
        ast.While,
        ast.Expr,
        ast.Name,
        ast.Load,
        ast.Store,
        ast.Constant,
        ast.Dict,
        ast.Tuple,
        ast.List,
        ast.Subscript,
        ast.Call,
        ast.Attribute,
    )

    def generic_visit(self, node: ast.AST) -> None:
        if not isinstance(node, self._allowed):
            raise ValueError(f"PRIVATE_FACTOR_FORBIDDEN_AST:{type(node).__name__}")
        super().generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            not isinstance(node.func, ast.Attribute)
            or not isinstance(node.func.value, ast.Name)
            or node.func.value.id != "api"
            or node.func.attr not in _OPERATIONS
            or node.keywords
        ):
            raise ValueError("PRIVATE_FACTOR_FORBIDDEN_CALL")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if not isinstance(node.value, ast.Name) or node.value.id != "api" or node.attr not in _OPERATIONS:
            raise ValueError("PRIVATE_FACTOR_FORBIDDEN_ATTRIBUTE")

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("__") or node.id in {
            "eval",
            "exec",
            "compile",
            "open",
            "input",
            "globals",
            "locals",
            "vars",
            "getattr",
            "setattr",
            "delattr",
        }:
            raise ValueError("PRIVATE_FACTOR_FORBIDDEN_NAME")


class _PrivateFactorAstInterpreter:
    def __init__(
        self,
        function: ast.FunctionDef,
        api: OnlyCanonicalValueSemanticsV1,
        inputs: dict[str, object],
        parameters: dict[str, object],
    ) -> None:
        self._function = function
        self._values: dict[str, object] = {"api": api, "inputs": inputs, "parameters": parameters}

    def run(self) -> object:
        returned, result = self._execute_block(self._function.body)
        return result if returned else None

    def _execute_block(self, statements: Sequence[ast.stmt]) -> tuple[bool, object]:
        for statement in statements:
            returned, result = self._execute_statement(statement)
            if returned:
                return True, result
        return False, None

    def _execute_statement(self, statement: ast.stmt) -> tuple[bool, object]:
        if isinstance(statement, ast.Assign):
            value = self._evaluate(statement.value)
            for target in statement.targets:
                self._assign(target, value)
            return False, None
        if isinstance(statement, ast.Return):
            return True, None if statement.value is None else self._evaluate(statement.value)
        if isinstance(statement, ast.Expr):
            self._evaluate(statement.value)
            return False, None
        if isinstance(statement, ast.If):
            branch = statement.body if self._evaluate(statement.test) else statement.orelse
            return self._execute_block(branch)
        if isinstance(statement, ast.While):
            while self._evaluate(statement.test):
                returned, result = self._execute_block(statement.body)
                if returned:
                    return True, result
            return self._execute_block(statement.orelse)
        raise ValueError(f"PRIVATE_FACTOR_FORBIDDEN_AST:{type(statement).__name__}")

    def _assign(self, target: ast.expr, value: object) -> None:
        if isinstance(target, ast.Name):
            self._values[target.id] = value
            return
        if isinstance(target, ast.Subscript):
            container = self._evaluate(target.value)
            key = self._evaluate(target.slice)
            cast(Any, container)[key] = value
            return
        raise ValueError(f"PRIVATE_FACTOR_FORBIDDEN_AST:{type(target).__name__}")

    def _evaluate(self, expression: ast.expr) -> object:
        if isinstance(expression, ast.Name):
            return self._values[expression.id]
        if isinstance(expression, ast.Constant):
            return expression.value
        if isinstance(expression, ast.Dict):
            if any(key is None for key in expression.keys):
                raise ValueError("PRIVATE_FACTOR_FORBIDDEN_AST:DictUnpack")
            return {
                self._evaluate(cast(ast.expr, key)): self._evaluate(value)
                for key, value in zip(expression.keys, expression.values, strict=True)
            }
        if isinstance(expression, ast.Tuple):
            return tuple(self._evaluate(item) for item in expression.elts)
        if isinstance(expression, ast.List):
            return [self._evaluate(item) for item in expression.elts]
        if isinstance(expression, ast.Subscript):
            return cast(Any, self._evaluate(expression.value))[self._evaluate(expression.slice)]
        if isinstance(expression, ast.Attribute):
            if (
                not isinstance(expression.value, ast.Name)
                or expression.value.id != "api"
                or expression.attr not in _OPERATIONS
            ):
                raise ValueError("PRIVATE_FACTOR_FORBIDDEN_ATTRIBUTE")
            return getattr(self._values["api"], expression.attr)
        if isinstance(expression, ast.Call):
            if not isinstance(expression.func, ast.Attribute) or expression.keywords:
                raise ValueError("PRIVATE_FACTOR_FORBIDDEN_CALL")
            function = self._evaluate(expression.func)
            return cast(Any, function)(*(self._evaluate(argument) for argument in expression.args))
        raise ValueError(f"PRIVATE_FACTOR_FORBIDDEN_AST:{type(expression).__name__}")


def _arrow_type(value: OnlyCalculationDataType) -> pa.DataType:
    return {
        OnlyCalculationDataType.DECIMAL: pa.decimal128(38, 12),
        OnlyCalculationDataType.INTEGER: pa.int64(),
        OnlyCalculationDataType.BOOLEAN: pa.bool_(),
        OnlyCalculationDataType.STRING: pa.string(),
    }[value]


def _normalize_output(values: Mapping[str, object], outputs: tuple[OnlyOutputDefinition, ...]) -> Mapping[str, object]:
    expected = {item.name: item for item in outputs}
    if set(values) != set(expected):
        raise ValueError("PRIVATE_FACTOR_OUTPUT_MISMATCH")
    try:
        normalized = {
            name: pa.scalar(values[name], type=_arrow_type(item.data_type)).as_py() for name, item in expected.items()
        }
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("PRIVATE_FACTOR_OUTPUT_MISMATCH") from exc
    if any(normalized[item.name] is None and not item.nullable for item in outputs):
        raise ValueError("PRIVATE_FACTOR_OUTPUT_MISMATCH")
    return normalized
