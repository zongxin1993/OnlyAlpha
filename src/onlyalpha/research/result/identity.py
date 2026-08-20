"""Canonical Research Result plan, content, and result identities."""

from __future__ import annotations

from onlyalpha.canonical import only_canonical_fingerprint

RESEARCH_RESULT_PLAN_SCHEMA_VERSION = 1
RESEARCH_RESULT_SCHEMA_VERSION = 1
RESEARCH_RESULT_SCIENTIFIC_PLAN_SCHEMA_VERSION = 2
RESEARCH_RESULT_SCIENTIFIC_SCHEMA_VERSION = 2


def only_research_result_plan_fingerprint(payload: object) -> str:
    if isinstance(payload, tuple):
        payload = {"schema_version": RESEARCH_RESULT_PLAN_SCHEMA_VERSION, "statistics_fingerprints": payload}
    return only_canonical_fingerprint(payload)


def only_research_result_content_fingerprint(
    statistics_results: tuple[object, ...],
    calculation_results: tuple[object, ...] = (),
    *,
    schema_version: int = RESEARCH_RESULT_SCHEMA_VERSION,
) -> str:
    payload: dict[str, object] = {"schema_version": schema_version, "statistics_results": statistics_results}
    if schema_version == RESEARCH_RESULT_SCIENTIFIC_SCHEMA_VERSION:
        payload["calculation_results"] = calculation_results
    return only_canonical_fingerprint(payload)


def only_research_result_fingerprint(
    plan_fingerprint: str, content_fingerprint: str, *, schema_version: int = RESEARCH_RESULT_SCHEMA_VERSION
) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": schema_version,
            "research_result_plan_fingerprint": plan_fingerprint,
            "research_result_content_fingerprint": content_fingerprint,
        }
    )
