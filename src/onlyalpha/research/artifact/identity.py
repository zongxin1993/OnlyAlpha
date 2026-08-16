"""Canonical logical identity for the Research Artifact read view."""

from __future__ import annotations

from onlyalpha.canonical import only_canonical_fingerprint

RESEARCH_ARTIFACT_SCHEMA_VERSION = 1
RESEARCH_ARTIFACT_PROFILE = "RESEARCH_STATISTICS_V1"


def only_research_artifact_content_fingerprint(
    research_result_fingerprint: str,
    dataset_snapshot_fingerprint: str,
    statistics_results: tuple[object, ...],
) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": RESEARCH_ARTIFACT_SCHEMA_VERSION,
            "profile": RESEARCH_ARTIFACT_PROFILE,
            "research_result_fingerprint": research_result_fingerprint,
            "dataset_snapshot_fingerprint": dataset_snapshot_fingerprint,
            "statistics_results": statistics_results,
        }
    )
