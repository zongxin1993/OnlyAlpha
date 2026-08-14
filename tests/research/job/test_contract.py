from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import pytest

from onlyalpha.research import (
    RESEARCH_JOB_PLAN_SCHEMA_VERSION,
    OnlyResearchJobDisposition,
    OnlyResearchJobError,
    OnlyResearchJobOutcome,
    OnlyResearchJobPhase,
    OnlyResearchJobPlan,
    OnlyResearchJobStatus,
)
from tests.research.job.support import job_case


def test_resolved_plan_is_exact_immutable_and_reuses_calculation_identity(tmp_path) -> None:
    plan, _, _, _ = job_case(tmp_path)
    assert RESEARCH_JOB_PLAN_SCHEMA_VERSION == 1
    assert tuple(item.name for item in fields(plan)) == (
        "dataset_snapshot_fingerprint",
        "calculation_graph",
        "schema_version",
    )
    assert plan.calculation_fingerprint
    assert not hasattr(plan, "research_job_fingerprint")
    assert not hasattr(plan, "research_plan_fingerprint")
    with pytest.raises(FrozenInstanceError):
        plan.schema_version = 2


@pytest.mark.parametrize(
    ("fingerprint", "schema_version"),
    (("not-a-sha", 1), ("A" * 64, 1), ("0" * 64, 2), ("0" * 64, True)),
)
def test_plan_validation_fails_closed(fingerprint, schema_version, tmp_path) -> None:
    valid, _, _, _ = job_case(tmp_path)
    with pytest.raises(OnlyResearchJobError) as raised:
        OnlyResearchJobPlan(fingerprint, valid.calculation_graph, schema_version)
    assert raised.value.phase is OnlyResearchJobPhase.PLAN_VALIDATION
    assert raised.value.code == "RESEARCH_JOB_INVALID"


def test_plan_rejects_noncanonical_graph(tmp_path) -> None:
    valid, _, _, _ = job_case(tmp_path)
    with pytest.raises(OnlyResearchJobError, match="calculation_graph must be canonical"):
        OnlyResearchJobPlan(valid.dataset_snapshot_fingerprint, object())


def test_outcome_contract_is_exact_and_validated() -> None:
    outcome = OnlyResearchJobOutcome(
        OnlyResearchJobStatus.SUCCEEDED,
        OnlyResearchJobDisposition.EXECUTED,
        "a" * 64,
        "b" * 64,
    )
    assert tuple(item.name for item in fields(outcome)) == (
        "status",
        "disposition",
        "calculation_fingerprint",
        "calculation_result_fingerprint",
    )
    with pytest.raises(ValueError, match="lower-case SHA256"):
        OnlyResearchJobOutcome(
            OnlyResearchJobStatus.SUCCEEDED,
            OnlyResearchJobDisposition.REUSED,
            "invalid",
            "b" * 64,
        )
    with pytest.raises(ValueError, match="status must be SUCCEEDED"):
        OnlyResearchJobOutcome("FAILED", OnlyResearchJobDisposition.REUSED, "a" * 64, "b" * 64)
    with pytest.raises(ValueError, match="disposition is invalid"):
        OnlyResearchJobOutcome(OnlyResearchJobStatus.SUCCEEDED, "UNKNOWN", "a" * 64, "b" * 64)
