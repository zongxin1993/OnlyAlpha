"""Canonical Research Result plan, content, and result identities."""

from __future__ import annotations

from onlyalpha.canonical import only_canonical_fingerprint

RESEARCH_RESULT_PLAN_SCHEMA_VERSION = 1
RESEARCH_RESULT_SCHEMA_VERSION = 1


def only_research_result_plan_fingerprint(statistics_fingerprints: tuple[str, ...]) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": RESEARCH_RESULT_PLAN_SCHEMA_VERSION,
            "statistics_fingerprints": statistics_fingerprints,
        }
    )


def only_research_result_content_fingerprint(statistics_results: tuple[object, ...]) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": RESEARCH_RESULT_SCHEMA_VERSION,
            "statistics_results": statistics_results,
        }
    )


def only_research_result_fingerprint(plan_fingerprint: str, content_fingerprint: str) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": RESEARCH_RESULT_SCHEMA_VERSION,
            "research_result_plan_fingerprint": plan_fingerprint,
            "research_result_content_fingerprint": content_fingerprint,
        }
    )
