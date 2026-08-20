"""Deterministic immutable Research Result composition authority."""
# ruff: noqa: F401

from .assembler import OnlyResearchResultAssembler
from .errors import OnlyResearchResultError, OnlyResearchResultStoreError
from .identity import (
    RESEARCH_RESULT_SCIENTIFIC_PLAN_SCHEMA_VERSION,
    RESEARCH_RESULT_SCIENTIFIC_SCHEMA_VERSION,
    only_research_result_content_fingerprint,
    only_research_result_fingerprint,
    only_research_result_plan_fingerprint,
)
from .plan import (
    OnlyResearchResultCalculationPlan,
    OnlyResearchResultCandidatePlan,
    OnlyResearchResultPlan,
    OnlyResearchResultSeriesPlan,
    OnlyResearchResultSignalPlan,
)
from .result import (
    OnlyResearchCalculationResultReference,
    OnlyResearchResult,
    OnlyResearchResultDisposition,
    OnlyResearchResultManifest,
    OnlyResearchResultOutcome,
    OnlyResearchStatisticsResultReference,
)
from .result_store import OnlyJsonResearchResultStore

__all__ = [name for name in globals() if name.startswith(("Only", "only_"))]
