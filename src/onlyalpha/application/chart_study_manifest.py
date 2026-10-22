"""Python service invocation provenance during the native Product cutover."""

from __future__ import annotations

from pathlib import Path

from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationKind,
    OnlyCalculationTypeReference,
)
from onlyalpha.calculation.implementation import (
    OnlyCalculationImplementationManifest,
    OnlyCalculationSemanticDependency,
    only_chart_study_numeric_dependency,
    only_python_implementation_manifest,
)


def only_chart_study_invocation_manifest() -> OnlyCalculationImplementationManifest:
    """Explicit resource closure of the registered non-publishing Chart adapter."""
    from onlyalpha.calculation.decimal_execution import only_decimal_execution_semantic_dependency

    return only_python_implementation_manifest(
        calculation_type_reference=OnlyCalculationTypeReference(
            OnlyCalculationKind.INDICATOR, "onlyalpha.chart-study.invocation", "2"
        ),
        backend_kind=OnlyCalculationBackendKind.RESEARCH,
        entrypoint_identity="onlyalpha.application.chart_study_numeric:OnlyChartStudyInvocation",
        package_root=Path(__file__).resolve().parents[1],
        resource_paths=(
            "application/chart_study_numeric.py",
            "application/chart_study_manifest.py",
            "algorithm/batch.py",
            "application/chart_study_input.py",
            "application/market_data_stream.py",
            "calculation/chart_study.py",
            "application/source_read_access.py",
            "calculation/chart_decimal.py",
            "calculation/decimal_execution.py",
            "calculation/definition.py",
            "calculation/implementation.py",
            "calculation/registry.py",
            "canonical.py",
            "quant_assets/installed_implementation.py",
            "quant_assets/catalog.py",
            "research/calculation/backend.py",
            "research/calculation/output_validation.py",
            "research/calculation/readiness.py",
        ),
        semantic_dependencies=(only_decimal_execution_semantic_dependency(), only_chart_study_numeric_dependency()),
    )


def only_chart_study_invocation_dependency() -> OnlyCalculationSemanticDependency:
    return OnlyCalculationSemanticDependency(
        "onlyalpha.chart-study.invocation", "2", only_chart_study_invocation_manifest().implementation_fingerprint
    )
