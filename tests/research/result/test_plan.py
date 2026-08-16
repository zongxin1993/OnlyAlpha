from __future__ import annotations

import json

import pytest

from onlyalpha.research import OnlyResearchResultPlan, only_research_result_plan_fingerprint

A = "a" * 64
B = "b" * 64


def test_plan_is_canonical_input_order_neutral_and_exactly_serializable() -> None:
    first = OnlyResearchResultPlan((B, A))
    second = OnlyResearchResultPlan((A, B))

    assert first == second
    assert first.statistics_fingerprints == (A, B)
    assert first.fingerprint == second.fingerprint == only_research_result_plan_fingerprint((A, B))
    assert len(first.fingerprint) == 64
    assert first.to_dict() == {
        "schema_version": 1,
        "statistics_fingerprints": [A, B],
    }
    assert OnlyResearchResultPlan.from_dict(json.loads(json.dumps(first.to_dict()))) == first


@pytest.mark.parametrize(
    "values,match",
    (
        ((), "at least one"),
        ((A, A), "duplicate"),
        (("A" * 64,), "lower-case SHA256"),
        (("bad",), "lower-case SHA256"),
    ),
)
def test_plan_rejects_empty_duplicate_and_invalid_identities(values, match: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match=match):
        OnlyResearchResultPlan(values)


def test_plan_rejects_unknown_fields_and_schema_versions() -> None:
    payload = OnlyResearchResultPlan((A,)).to_dict()
    with pytest.raises(ValueError, match="fields"):
        OnlyResearchResultPlan.from_dict({**payload, "title": "presentation must not enter identity"})
    with pytest.raises(ValueError, match="unsupported"):
        OnlyResearchResultPlan.from_dict({**payload, "schema_version": 2})


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("schema_version", True, "integer"),
        ("schema_version", "1", "integer"),
        ("statistics_fingerprints", (A,), "array of strings"),
        ("statistics_fingerprints", [1], "array of strings"),
    ),
)
def test_plan_parser_rejects_non_exact_serialized_types(field: str, value: object, match: str) -> None:
    payload = OnlyResearchResultPlan((A,)).to_dict()
    payload[field] = value

    with pytest.raises(ValueError, match=match):
        OnlyResearchResultPlan.from_dict(payload)
