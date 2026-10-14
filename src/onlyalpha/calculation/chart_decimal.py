"""Explicit legacy CONTEXT input for non-publishing SMA invocations only."""

from __future__ import annotations

from dataclasses import replace
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Protocol, runtime_checkable

from onlyalpha.calculation.decimal_execution import (
    ONLY_DECIMAL_EXECUTION_POLICY_V1,
)
from onlyalpha.calculation.definition import (
    OnlyNumericDefinition,
)


@runtime_checkable
class OnlyChartNumericBindingVerifier(Protocol):
    def require_chart_numeric_binding(self, numeric: OnlyNumericDefinition) -> None: ...


def only_chart_sma_effective_numeric(declared: OnlyNumericDefinition) -> OnlyNumericDefinition:
    if (
        declared != OnlyNumericDefinition("DECIMAL", 28, Decimal("0.000000000001"), "CONTEXT")
        or declared.output_quantum is None
        or declared.output_quantum.as_tuple() != Decimal("0.000000000001").as_tuple()
    ):
        raise ValueError("CHART_STUDY_NUMERIC_UNAVAILABLE")
    return replace(declared, rounding=ROUND_HALF_EVEN)


def only_chart_sma_numeric_binding(declared: OnlyNumericDefinition) -> dict[str, object]:
    effective = only_chart_sma_effective_numeric(declared)
    policy = ONLY_DECIMAL_EXECUTION_POLICY_V1
    return {
        "domain": "onlyalpha.chart-study.decimal-binding",
        "schema_version": 1,
        "resolution_policy": "CONTEXT_HALF_EVEN_V1",
        "declared_rounding": declared.rounding,
        "effective_rounding": effective.rounding,
        "representation": effective.representation,
        "precision": effective.precision,
        "output_quantum": format(effective.output_quantum, "f"),
        "core_policy": dict(policy.canonical_payload),
        "core_policy_fingerprint": policy.fingerprint,
    }
