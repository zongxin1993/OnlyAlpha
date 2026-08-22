from __future__ import annotations

import json

import pytest

from onlyalpha.research import (
    OnlyResearchResultCalculationPlan,
    OnlyResearchResultCandidatePlan,
    OnlyResearchResultPlan,
    OnlyResearchResultSeriesPlan,
    OnlyResearchResultSignalPlan,
    only_research_result_plan_fingerprint,
)

A = "a" * 64
B = "b" * 64
C = "c" * 64
D = "d" * 64
E = "e" * 64
F = "f" * 64


def _scientific_members():
    calculation = OnlyResearchResultCalculationPlan(B, C)
    candidate = OnlyResearchResultCandidatePlan(D, "decision", (), B, C, (A,))
    series = OnlyResearchResultSeriesPlan(D, B, E, "value")
    signal = OnlyResearchResultSignalPlan("ENTRY_SIGNAL", D, B, E, "value")
    return calculation, candidate, series, signal


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
        OnlyResearchResultPlan.from_dict({**payload, "schema_version": 3})


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


def test_scientific_plan_rejects_duplicate_candidate_role_with_different_series() -> None:
    calculation = OnlyResearchResultCalculationPlan(B, "c" * 64)
    candidate = OnlyResearchResultCandidatePlan("d" * 64, "decision", (), B, "c" * 64, (A,))
    signals = (
        OnlyResearchResultSignalPlan("ENTRY_SIGNAL", "d" * 64, B, "e" * 64, "first"),
        OnlyResearchResultSignalPlan("ENTRY_SIGNAL", "d" * 64, B, "f" * 64, "second"),
    )

    with pytest.raises(ValueError, match="Candidate and role"):
        OnlyResearchResultPlan((A,), 2, "a" * 64, (calculation,), (candidate,), (), signals)


@pytest.mark.parametrize(
    "second",
    (
        OnlyResearchResultCandidatePlan("d" * 64, "decision", (("period", 20),), B, "c" * 64, (A,)),
        OnlyResearchResultCandidatePlan("d" * 64, "decision", (), "e" * 64, "c" * 64, (A,)),
        OnlyResearchResultCandidatePlan("d" * 64, "decision", (), B, "e" * 64, (A,)),
    ),
)
def test_scientific_plan_rejects_one_candidate_identity_for_different_members(second) -> None:  # type: ignore[no-untyped-def]
    calculations = tuple(
        sorted(
            {
                OnlyResearchResultCalculationPlan(B, "c" * 64),
                OnlyResearchResultCalculationPlan("e" * 64, "c" * 64),
            }
        )
    )
    first = OnlyResearchResultCandidatePlan("d" * 64, "decision", (), B, "c" * 64, (A,))

    with pytest.raises(ValueError, match="Candidate identities"):
        OnlyResearchResultPlan((A,), 2, "a" * 64, calculations, tuple(sorted((first, second))))


def test_scientific_plan_rejects_one_calculation_identity_for_different_members() -> None:
    calculations = tuple(
        sorted(
            (
                OnlyResearchResultCalculationPlan(B, "c" * 64),
                OnlyResearchResultCalculationPlan(B, "d" * 64),
            )
        )
    )

    with pytest.raises(ValueError, match="Calculation identities"):
        OnlyResearchResultPlan((A,), 2, "a" * 64, calculations)


def test_candidate_statistics_membership_is_order_neutral_and_duplicate_closed() -> None:
    calculation = OnlyResearchResultCalculationPlan("c" * 64, "d" * 64)
    first = OnlyResearchResultCandidatePlan("e" * 64, "decision", (), "c" * 64, "d" * 64, (B, A))
    second = OnlyResearchResultCandidatePlan("e" * 64, "decision", (), "c" * 64, "d" * 64, (A, B))

    assert first == second
    assert first.statistics_fingerprints == (A, B)
    first_plan = OnlyResearchResultPlan((B, A), 2, "f" * 64, (calculation,), (first,))
    second_plan = OnlyResearchResultPlan((A, B), 2, "f" * 64, (calculation,), (second,))
    assert first_plan.to_dict() == second_plan.to_dict()
    assert first_plan.fingerprint == second_plan.fingerprint
    assert first_plan.fingerprint == "8d60326eda40ac5cccfc02a05097283474530bd8f6ea7f37e2fb20598dfd4143"

    with pytest.raises(ValueError, match="duplicate"):
        OnlyResearchResultCandidatePlan("e" * 64, "decision", (), "c" * 64, "d" * 64, (A, A))


@pytest.mark.parametrize(
    "factory",
    (
        lambda: OnlyResearchResultCalculationPlan("BAD", C),
        lambda: OnlyResearchResultCandidatePlan(D, "", (), B, C, (A,)),
        lambda: OnlyResearchResultCandidatePlan(D, "decision", (("z", 1), ("a", 2)), B, C, (A,)),
        lambda: OnlyResearchResultSeriesPlan(D, B, E, ""),
        lambda: OnlyResearchResultSignalPlan("UNKNOWN", D, B, E, "value"),
        lambda: OnlyResearchResultSignalPlan("ENTRY_SIGNAL", D, B, E, ""),
    ),
)
def test_scientific_member_contracts_fail_closed(factory) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        factory()


def test_scientific_plan_rejects_every_membership_and_canonicality_violation() -> None:
    calculation, candidate, series, signal = _scientific_members()
    with pytest.raises(ValueError, match="unsupported"):
        OnlyResearchResultPlan((A,), 99)
    with pytest.raises(ValueError, match="V1"):
        OnlyResearchResultPlan((A,), 1, F)
    with pytest.raises(ValueError, match="calculations are invalid"):
        OnlyResearchResultPlan((A,), 2, F, [calculation])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="not canonical and unique"):
        OnlyResearchResultPlan((A,), 2, F, (calculation, calculation))
    with pytest.raises(ValueError, match="requires Calculation"):
        OnlyResearchResultPlan((A,), 2, F)
    with pytest.raises(ValueError, match="unknown Calculation"):
        OnlyResearchResultPlan(
            (A,),
            2,
            F,
            (calculation,),
            (OnlyResearchResultCandidatePlan(D, "decision", (), E, C, (A,)),),
        )
    with pytest.raises(ValueError, match="unknown Candidate"):
        OnlyResearchResultPlan(
            (A,),
            2,
            F,
            (calculation,),
            (candidate,),
            (OnlyResearchResultSeriesPlan(None, B, E, "global"),),
            (OnlyResearchResultSignalPlan("ENTRY_SIGNAL", E, B, E, "value"),),
        )
    with pytest.raises(ValueError, match="unknown Statistics"):
        OnlyResearchResultPlan(
            (A,),
            2,
            F,
            (calculation,),
            (OnlyResearchResultCandidatePlan(D, "decision", (), B, C, (E,)),),
        )
    assert OnlyResearchResultPlan((A,), 2, F, (calculation,), (candidate,), (series,), (signal,)).schema_version == 2


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("calculations", [1], "object"),
        ("candidates", {}, "array"),
        (
            "candidates",
            [
                {
                    "candidate_fingerprint": D,
                    "candidate_calculation_id": "",
                    "assignment": {},
                    "calculation_fingerprint": B,
                    "graph_fingerprint": C,
                    "statistics_fingerprints": [A],
                }
            ],
            "non-empty string",
        ),
    ),
)
def test_scientific_plan_parser_rejects_malformed_nested_values(field: str, value: object, match: str) -> None:
    calculation, candidate, series, signal = _scientific_members()
    payload = OnlyResearchResultPlan((A,), 2, F, (calculation,), (candidate,), (series,), (signal,)).to_dict()
    payload[field] = value
    with pytest.raises(ValueError, match=match):
        OnlyResearchResultPlan.from_dict(payload)
