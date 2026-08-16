from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from onlyalpha.research import (
    OnlyResearchResultDisposition,
    OnlyResearchResultManifest,
    OnlyResearchResultOutcome,
    OnlyResearchResultPlan,
    OnlyResearchStatisticsResultReference,
    only_research_result_content_fingerprint,
    only_research_result_fingerprint,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64
E = "e" * 64


def _manifest() -> OnlyResearchResultManifest:
    plan = OnlyResearchResultPlan((A, B))
    references = (
        OnlyResearchStatisticsResultReference(A, C),
        OnlyResearchStatisticsResultReference(B, D),
    )
    content = only_research_result_content_fingerprint(tuple(item.to_dict() for item in references))
    return OnlyResearchResultManifest(
        plan,
        plan.fingerprint,
        E,
        references,
        content,
        only_research_result_fingerprint(plan.fingerprint, content),
        datetime(2026, 8, 16, tzinfo=UTC),
    )


@pytest.mark.parametrize("invalid", (None, 1, "bad", "A" * 64, "g" * 64))
@pytest.mark.parametrize("field", ("statistics_fingerprint", "statistics_result_fingerprint"))
def test_statistics_reference_requires_exact_lower_case_sha256(field: str, invalid: object) -> None:
    values = {"statistics_fingerprint": A, "statistics_result_fingerprint": C, field: invalid}

    with pytest.raises(ValueError, match=field):
        OnlyResearchStatisticsResultReference(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "payload",
    (
        {"statistics_fingerprint": A},
        {"statistics_fingerprint": A, "statistics_result_fingerprint": C, "unknown": True},
        {"statistics_fingerprint": 1, "statistics_result_fingerprint": C},
    ),
)
def test_statistics_reference_parser_has_an_exact_schema(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        OnlyResearchStatisticsResultReference.from_dict(payload)


@pytest.mark.parametrize(
    ("changes", "match"),
    (
        ({"schema_version": 2}, "schema"),
        ({"research_result_plan_fingerprint": A}, "Plan fingerprint"),
        ({"dataset_snapshot_fingerprint": "bad"}, "dataset_snapshot_fingerprint"),
        ({"statistics_results": []}, "references are invalid"),
        ({"statistics_results": (object(),)}, "references are invalid"),
        (
            {
                "statistics_results": (
                    OnlyResearchStatisticsResultReference(B, D),
                    OnlyResearchStatisticsResultReference(A, C),
                )
            },
            "not canonical",
        ),
        (
            {"statistics_results": (OnlyResearchStatisticsResultReference(A, C),)},
            "do not match Plan",
        ),
        ({"research_result_content_fingerprint": A}, "content fingerprint"),
        ({"research_result_fingerprint": A}, "fingerprint linkage"),
        ({"created_at": "2026-08-16T00:00:00Z"}, "timezone-aware UTC"),
        ({"created_at": datetime(2026, 8, 16)}, "timezone-aware UTC"),
        (
            {"created_at": datetime(2026, 8, 16, tzinfo=timezone(timedelta(hours=8)))},
            "timezone-aware UTC",
        ),
    ),
)
def test_manifest_constructor_enforces_composition_invariants(changes: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        replace(_manifest(), **changes)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (lambda payload: payload.pop("created_at"), "fields"),
        (lambda payload: payload.__setitem__("unknown", True), "fields"),
        (lambda payload: payload.__setitem__("schema_version", True), "integer"),
        (lambda payload: payload.__setitem__("plan", []), "plan must be an object"),
        (lambda payload: payload.__setitem__("statistics_results", ()), "must be an array"),
        (lambda payload: payload.__setitem__("statistics_results", [1]), "reference must be an object"),
        (lambda payload: payload.__setitem__("dataset_snapshot_fingerprint", 1), "must be a string"),
        (lambda payload: payload.__setitem__("dataset_snapshot_fingerprint", "bad"), "lower-case SHA256"),
        (lambda payload: payload.__setitem__("created_at", 1), "must be a string"),
        (lambda payload: payload.__setitem__("created_at", "not-a-time"), "ISO datetime"),
        (lambda payload: payload.__setitem__("created_at", "2026-08-16T00:00:00"), "timezone-aware UTC"),
        (lambda payload: payload.__setitem__("created_at", "2026-08-16T08:00:00+08:00"), "timezone-aware UTC"),
    ),
)
def test_manifest_parser_rejects_malformed_untrusted_state(mutation, match: str) -> None:  # type: ignore[no-untyped-def]
    payload = _manifest().to_dict()
    mutation(payload)

    with pytest.raises(ValueError, match=match):
        OnlyResearchResultManifest.from_dict(payload)


@pytest.mark.parametrize(
    "changes",
    (
        {"disposition": "EXECUTED"},
        {"research_result_plan_fingerprint": "bad"},
        {"research_result_fingerprint": "A" * 64},
    ),
)
def test_outcome_rejects_invalid_public_evidence(changes: dict[str, object]) -> None:
    manifest = _manifest()
    outcome = OnlyResearchResultOutcome(
        OnlyResearchResultDisposition.EXECUTED,
        manifest.research_result_plan_fingerprint,
        manifest.research_result_fingerprint,
    )

    with pytest.raises(ValueError):
        replace(outcome, **changes)
