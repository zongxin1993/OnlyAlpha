"""Canonical Statistics and Statistics Result identities."""

from __future__ import annotations

from onlyalpha.canonical import only_canonical_fingerprint

from .definition import OnlyResearchStatisticsDefinition
from .reference import OnlyResearchFeatureSeriesReference, OnlyResearchTargetSeriesReference

RESEARCH_STATISTICS_RESULT_SCHEMA_VERSION = 1
RESEARCH_STATISTICS_IDENTITY_SCHEMA_VERSION = 1


def only_research_statistics_fingerprint(
    feature: OnlyResearchFeatureSeriesReference,
    target: OnlyResearchTargetSeriesReference,
    definition: OnlyResearchStatisticsDefinition,
) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": RESEARCH_STATISTICS_IDENTITY_SCHEMA_VERSION,
            "feature": feature.to_dict(),
            "target": target.to_dict(),
            "definition": definition.to_dict(),
        }
    )


def only_research_statistics_result_content_fingerprint(rows: tuple[object, ...]) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": RESEARCH_STATISTICS_RESULT_SCHEMA_VERSION,
            "rows": rows,
        }
    )


def only_research_statistics_result_fingerprint(
    statistics_fingerprint: str,
    result_content_fingerprint: str,
) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": RESEARCH_STATISTICS_RESULT_SCHEMA_VERSION,
            "statistics_fingerprint": statistics_fingerprint,
            "result_content_fingerprint": result_content_fingerprint,
        }
    )
