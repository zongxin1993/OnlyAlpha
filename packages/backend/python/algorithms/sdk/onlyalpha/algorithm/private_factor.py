"""Pure stable calculate(api, inputs, parameters) AST and exact numerical API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.calculation.decimal_execution import ONLY_DECIMAL_EXECUTION_POLICY_V1
from onlyalpha.calculation.definition import OnlyCalculationDataType, OnlyNumericDefinition, OnlyOutputDefinition
from onlyalpha.canonical import only_canonical_fingerprint

_OPERATIONS = (
    "abs",
    "add",
    "and_",
    "coalesce",
    "decay_linear",
    "decimal",
    "delay",
    "delta",
    "div",
    "eq",
    "ge",
    "gt",
    "is_missing",
    "le",
    "log",
    "lt",
    "max",
    "min",
    "mul",
    "ne",
    "negate",
    "not_",
    "or_",
    "rolling_max",
    "rolling_mean",
    "rolling_min",
    "rolling_std",
    "rolling_sum",
    "rolling_var",
    "sign",
    "sub",
    "ts_rank",
    "where",
)

ONLY_PRIVATE_FACTOR_NUMERIC_V1 = OnlyNumericDefinition(
    representation="DECIMAL",
    precision=28,
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
                "determinism": "SHARED_BATCH_EVENT_WITH_BOUNDED_INSTANCE_WINDOWS",
                "program_format": "TYPED_FACTOR_PROGRAM_V1",
                "numeric_policy": "DECIMAL28_HALF_EVEN_Q12_V1",
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
                "state": "DECLARED_BOUNDED_WINDOWS",
            }
        )


ONLY_PRIVATE_FACTOR_VALIDATION_POLICY_V1 = OnlyPrivateFactorValidationPolicyV1()


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
