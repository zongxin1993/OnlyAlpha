"""Layered canonical identities for typed Summary Statistics."""

from __future__ import annotations

from onlyalpha.canonical import only_canonical_fingerprint

from ..reference import OnlyResearchFeatureSeriesReference
from .definition import OnlyResearchCoverageSummaryDefinition, OnlyResearchEffectSummaryDefinition

RESEARCH_SUMMARY_STATISTICS_IDENTITY_SCHEMA_VERSION = 1
RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION = 1
RESEARCH_SUMMARY_STATISTICS_DOMAIN = "RESEARCH_SUMMARY_STATISTICS"


def only_research_effect_summary_fingerprint(
    dataset_snapshot_fingerprint: str,
    subject_candidate_fingerprint: str,
    subject: OnlyResearchFeatureSeriesReference,
    source_statistics_fingerprint: str,
    definition: OnlyResearchEffectSummaryDefinition,
) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": RESEARCH_SUMMARY_STATISTICS_IDENTITY_SCHEMA_VERSION,
            "domain": RESEARCH_SUMMARY_STATISTICS_DOMAIN,
            "summary_kind": definition.summary_kind.value,
            "dataset_snapshot_fingerprint": dataset_snapshot_fingerprint,
            "subject_candidate_fingerprint": subject_candidate_fingerprint,
            "subject": subject.to_dict(),
            "source_statistics_fingerprint": source_statistics_fingerprint,
            "definition": definition.to_dict(),
        }
    )


def only_research_coverage_summary_fingerprint(
    dataset_snapshot_fingerprint: str,
    subject_candidate_fingerprint: str,
    subject: OnlyResearchFeatureSeriesReference,
    source_statistics_fingerprint: str,
    definition: OnlyResearchCoverageSummaryDefinition,
) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": RESEARCH_SUMMARY_STATISTICS_IDENTITY_SCHEMA_VERSION,
            "domain": RESEARCH_SUMMARY_STATISTICS_DOMAIN,
            "summary_kind": definition.summary_kind.value,
            "dataset_snapshot_fingerprint": dataset_snapshot_fingerprint,
            "subject_candidate_fingerprint": subject_candidate_fingerprint,
            "subject": subject.to_dict(),
            "source_statistics_fingerprint": source_statistics_fingerprint,
            "definition": definition.to_dict(),
        }
    )


def only_research_summary_result_content_fingerprint(
    source_statistics_fingerprint: str,
    source_statistics_result_fingerprint: str,
    summary_payload: object,
) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION,
            "domain": RESEARCH_SUMMARY_STATISTICS_DOMAIN,
            "source_statistics_fingerprint": source_statistics_fingerprint,
            "source_statistics_result_fingerprint": source_statistics_result_fingerprint,
            "summary": summary_payload,
        }
    )


def only_research_summary_result_fingerprint(
    statistics_fingerprint: str,
    result_content_fingerprint: str,
) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": RESEARCH_SUMMARY_STATISTICS_RESULT_SCHEMA_VERSION,
            "domain": RESEARCH_SUMMARY_STATISTICS_DOMAIN,
            "statistics_fingerprint": statistics_fingerprint,
            "result_content_fingerprint": result_content_fingerprint,
        }
    )


__all__ = [
    "RESEARCH_SUMMARY_STATISTICS_DOMAIN",
    "only_research_coverage_summary_fingerprint",
    "only_research_effect_summary_fingerprint",
    "only_research_summary_result_content_fingerprint",
    "only_research_summary_result_fingerprint",
]
