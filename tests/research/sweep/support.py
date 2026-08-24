from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from onlyalpha_plugin_factors.registration import registrations as factor_registrations
from onlyalpha_plugin_indicators.registration import TYPES
from onlyalpha_plugin_indicators.registration import registrations as indicator_registrations

from onlyalpha.calculation import (
    OnlyCalculationKind,
    OnlyCalculationRegistry,
    OnlyCalculationTypeReference,
)
from onlyalpha.research import (
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyResearchCalculationBackendResolver,
    OnlyResearchCalculationExecutionEvidenceStore,
    OnlyResearchCalculationExecutor,
    OnlyResearchGraphTemplate,
    OnlyResearchGraphTemplateNode,
    OnlyResearchSweepDefinition,
    OnlyResearchSweepParameterDimension,
    OnlyResearchSweepParameterTarget,
    OnlyResearchTemplateInputBinding,
    OnlyResearchTemplateReference,
)
from tests.research.calculation.support import snapshot


def registry() -> OnlyCalculationRegistry:
    result = OnlyCalculationRegistry()
    for registration in (*indicator_registrations(), *factor_registrations()):
        result.register(registration)
    return result


def reference(kind: OnlyCalculationKind, type_id: str, version: str = "1") -> OnlyCalculationTypeReference:
    return OnlyCalculationTypeReference(kind, type_id, version)


def factor_template(*, alias: str | None = None) -> OnlyResearchGraphTemplate:
    rolling = next(item for item in TYPES if item.type_id == "onlyalpha.indicator.rolling_return")
    return OnlyResearchGraphTemplate(
        (
            OnlyResearchGraphTemplateNode(
                "short", reference(OnlyCalculationKind.INDICATOR, rolling.type_id), {"period": 1}
            ),
            OnlyResearchGraphTemplateNode(
                "long", reference(OnlyCalculationKind.INDICATOR, rolling.type_id), {"period": 2}
            ),
            OnlyResearchGraphTemplateNode(
                "momentum",
                reference(OnlyCalculationKind.FACTOR, "onlyalpha.factor.momentum"),
                {"short_weight": Decimal("0.5"), "long_weight": Decimal("0.5")},
                (
                    OnlyResearchTemplateInputBinding("return_short", OnlyResearchTemplateReference("short", "value")),
                    OnlyResearchTemplateInputBinding("return_long", OnlyResearchTemplateReference("long", "value")),
                ),
                alias,
            ),
            OnlyResearchGraphTemplateNode(
                "score",
                reference(OnlyCalculationKind.FACTOR, "onlyalpha.factor.cross_section_percentile"),
                {"direction": "HIGHER_IS_BETTER"},
                (
                    OnlyResearchTemplateInputBinding(
                        "factor_value", OnlyResearchTemplateReference("momentum", "factor_value")
                    ),
                ),
            ),
        )
    )


def definition(
    dataset_fingerprint: str = "a" * 64,
    *,
    candidates: tuple[object, ...] = (3, 1),
    template: OnlyResearchGraphTemplate | None = None,
) -> OnlyResearchSweepDefinition:
    return OnlyResearchSweepDefinition(
        dataset_fingerprint,
        template or factor_template(),
        (OnlyResearchSweepParameterDimension(OnlyResearchSweepParameterTarget("short", "period"), candidates),),
    )


def execution_case(root: Path):
    dataset_store = OnlyParquetResearchDatasetSnapshotStore(root / "datasets")
    candidate, partitions = snapshot()
    committed = dataset_store.commit(candidate, partitions)
    calculation = OnlyResearchCalculationExecutor(dataset_store, OnlyResearchCalculationBackendResolver(registry()))
    result_store = OnlyParquetResearchCalculationResultStore(
        root / "results", dataset_store, audit_time=lambda: datetime(2026, 8, 14, tzinfo=UTC)
    )
    result_store._test_execution_evidence_store = OnlyResearchCalculationExecutionEvidenceStore(root / "semantic")
    return committed, calculation, result_store
