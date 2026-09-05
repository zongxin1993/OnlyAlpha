"""Typed Research Summary Statistics authority."""
# ruff: noqa: F401

from .definition import (
    OnlyResearchCoverageSemantics,
    OnlyResearchCoverageSummaryDefinition,
    OnlyResearchEffectSummaryDefinition,
    OnlyResearchSummaryInformationRatio,
    OnlyResearchSummarySignRule,
    OnlyResearchSummarySourceStatusPolicy,
    OnlyResearchSummaryStandardDeviation,
    OnlyResearchTemporalIntervalAssignment,
    OnlyResearchTemporalStabilityDefinition,
)
from .execution import (
    OnlyResearchCoverageSummaryExecution,
    OnlyResearchCoverageSummaryExecutor,
    OnlyResearchEffectSummaryExecution,
    OnlyResearchEffectSummaryExecutor,
    OnlyResearchSummaryExecution,
    OnlyResearchTemporalStabilityExecution,
    OnlyResearchTemporalStabilityExecutor,
    only_compute_research_coverage_summary,
    only_compute_research_effect_summary,
    only_compute_research_temporal_stability,
)
from .family import OnlyResearchStatisticsFamily, only_research_statistics_family
from .identity import (
    RESEARCH_SUMMARY_STATISTICS_DOMAIN,
    only_research_coverage_summary_fingerprint,
    only_research_effect_summary_fingerprint,
    only_research_summary_result_content_fingerprint,
    only_research_summary_result_fingerprint,
    only_research_temporal_stability_fingerprint,
)
from .metric import (
    ONLY_RESEARCH_SUMMARY_METRICS,
    OnlyResearchSummaryKind,
    OnlyResearchSummaryMetricDescriptor,
    OnlyResearchSummaryValueKind,
    only_research_coverage_metric,
    only_research_effect_metric,
    only_research_stability_metric,
    only_research_summary_metric,
)
from .plan import (
    OnlyResearchCoverageSummaryPlan,
    OnlyResearchEffectSummaryPlan,
    OnlyResearchSummaryPlan,
    OnlyResearchTemporalStabilityPlan,
    only_research_summary_plan_from_dict,
)
from .reader import OnlyResearchStatisticsResultReader
from .result import (
    OnlyResearchCoverageSummary,
    OnlyResearchEffectSummary,
    OnlyResearchSummary,
    OnlyResearchSummaryStatisticsResult,
    OnlyResearchSummaryStatisticsResultManifest,
    OnlyResearchTemporalSliceEvidence,
    OnlyResearchTemporalSliceValue,
    OnlyResearchTemporalStabilitySummary,
    only_research_summary_from_dict,
)
from .result_store import OnlyJsonResearchSummaryStatisticsResultStore
from .scalar import OnlyResearchSummaryScalar, OnlyResearchSummaryScalarStatus
from .temporal import OnlyResearchTemporalSlice

__all__ = [name for name in globals() if name.startswith(("Only", "only_", "RESEARCH_", "ONLY_RESEARCH_"))]
