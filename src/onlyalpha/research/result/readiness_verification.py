"""Result V4 composition closure through the explicitly selected Calculation V2 authority."""

from __future__ import annotations

from collections.abc import Mapping

from onlyalpha.research.calculation.result_v2 import (
    OnlyResearchCalculationResultManifestV2,
    OnlyResearchCalculationResultV2,
)

from .identity import RESEARCH_RESULT_CALCULATION_READINESS_SCHEMA_VERSION
from .plan import OnlyResearchResultPlan


def only_verify_readiness_composition(
    plan: OnlyResearchResultPlan,
    calculations: Mapping[str, OnlyResearchCalculationResultV2],
) -> None:
    if (
        type(plan) is not OnlyResearchResultPlan
        or plan.schema_version != RESEARCH_RESULT_CALCULATION_READINESS_SCHEMA_VERSION
    ):
        raise ValueError("exact readiness Result Plan V4 required")
    if OnlyResearchResultPlan.from_dict(plan.to_dict()) != plan:
        raise ValueError("Result Plan canonical shape differs")
    if set(calculations) != {item.calculation_fingerprint for item in plan.calculations}:
        raise ValueError("Result V4 Calculation membership differs")
    for member in plan.calculations:
        result = calculations[member.calculation_fingerprint]
        if (
            type(result) is not OnlyResearchCalculationResultV2
            or type(result.manifest) is not OnlyResearchCalculationResultManifestV2
        ):
            raise ValueError("Result V4 requires exact Calculation Result V2")
        manifest = OnlyResearchCalculationResultManifestV2.from_dict(result.manifest.to_dict())
        if (
            manifest != result.manifest
            or manifest.calculation_fingerprint != member.calculation_fingerprint
            or manifest.dataset_snapshot_fingerprint != plan.dataset_snapshot_fingerprint
            or manifest.calculation_graph_fingerprint != member.graph_fingerprint
        ):
            raise ValueError("Result V4 Snapshot/Calculation/Graph linkage differs")
    for series in plan.published_series:
        graph = calculations[series.calculation_fingerprint].manifest.calculation_graph
        node = next((item for item in graph.nodes if item.fingerprint == series.node_fingerprint), None)
        if node is None or series.output_name not in {item.name for item in node.definition.outputs}:
            raise ValueError("Result V4 published node/output linkage differs")
