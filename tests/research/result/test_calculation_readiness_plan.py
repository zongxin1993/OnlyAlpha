from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from onlyalpha.research.result.plan import (
    OnlyResearchResultCalculationPlan,
    OnlyResearchResultPlan,
    OnlyResearchResultSeriesPlan,
)


def readiness_plan():
    from onlyalpha.research.calculation.publication import OnlyResearchCalculationPublicationSelectionV1

    return OnlyResearchResultPlan(
        (),
        4,
        "a" * 64,
        (OnlyResearchResultCalculationPlan("b" * 64, "c" * 64),),
        (),
        (OnlyResearchResultSeriesPlan(None, "b" * 64, "d" * 64, "value"),),
        (),
        publication=OnlyResearchCalculationPublicationSelectionV1(),
    )


def test_readiness_plan_has_strict_shape_and_publication_identity():
    plan = readiness_plan()
    assert set(plan.to_dict()) == {
        "schema_version",
        "dataset_snapshot_fingerprint",
        "calculations",
        "published_series",
        "publication",
    }
    assert OnlyResearchResultPlan.from_dict(plan.to_dict()) == plan
    assert OnlyResearchResultPlan.from_dict(plan.to_dict()).fingerprint == plan.fingerprint
    numeric = OnlyResearchResultPlan(
        (), 3, plan.dataset_snapshot_fingerprint, plan.calculations, (), plan.published_series
    )
    assert numeric.fingerprint != plan.fingerprint


@pytest.mark.parametrize("name", ("statistics_fingerprints", "candidates", "signals"))
def test_readiness_plan_does_not_serialize_scientific_fields(name):
    payload = deepcopy(readiness_plan().to_dict())
    payload[name] = []
    with pytest.raises(ValueError):
        OnlyResearchResultPlan.from_dict(payload)


def test_readiness_plan_requires_complete_unique_unowned_membership():
    plan = readiness_plan()
    for changes in (
        {"publication": None},
        {"schema_version": 4.0},
        {"calculations": ()},
        {"calculations": plan.calculations * 2},
        {"published_series": ()},
        {"published_series": plan.published_series * 2},
        {"published_series": (replace(plan.published_series[0], calculation_fingerprint="e" * 64),)},
        {"published_series": (replace(plan.published_series[0], candidate_fingerprint="e" * 64),)},
        {"statistics_fingerprints": ("f" * 64,)},
    ):
        with pytest.raises(ValueError):
            replace(plan, **changes)


@pytest.mark.parametrize(
    "version,pinned",
    (
        (1, "98caf0f5688673a545bc51549642b942f567b2e7d27c43be984b67eb25dd6e72"),
        (2, "a580e14952ae73ef9316b92565458d2ba90f6650946fd76f8e976580a0eb7f61"),
        (3, "878032b5bf8d861ca847169f3e1ec4663d38983ed6f58d09591f44e4e87289ea"),
    ),
)
def test_legacy_plan_payload_and_identity_are_not_upgraded(version, pinned):
    plan = (
        OnlyResearchResultPlan(("f" * 64,))
        if version == 1
        else OnlyResearchResultPlan(
            ("f" * 64,) if version == 2 else (),
            version,
            "a" * 64,
            (OnlyResearchResultCalculationPlan("b" * 64, "c" * 64),),
            (),
            (OnlyResearchResultSeriesPlan(None, "b" * 64, "d" * 64, "value"),),
        )
    )
    assert plan.fingerprint == pinned
    assert OnlyResearchResultPlan.from_dict(plan.to_dict()).to_dict() == plan.to_dict()
    assert "publication" not in plan.to_dict()
