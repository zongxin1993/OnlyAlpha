from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace

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
        "publication",
    )
    assert plan.calculation_fingerprint
    assert plan.publication is None
    assert OnlyResearchJobPlan(plan.dataset_snapshot_fingerprint, plan.calculation_graph, 1) == plan
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
        "c" * 64,
    )
    assert tuple(item.name for item in fields(outcome)) == (
        "status",
        "disposition",
        "calculation_fingerprint",
        "calculation_result_fingerprint",
        "calculation_execution_evidence_fingerprint",
    )
    with pytest.raises(ValueError, match="lower-case SHA256"):
        OnlyResearchJobOutcome(
            OnlyResearchJobStatus.SUCCEEDED,
            OnlyResearchJobDisposition.REUSED,
            "invalid",
            "b" * 64,
            "c" * 64,
        )
    with pytest.raises(ValueError, match="status must be SUCCEEDED"):
        OnlyResearchJobOutcome("FAILED", OnlyResearchJobDisposition.REUSED, "a" * 64, "b" * 64, "c" * 64)
    with pytest.raises(ValueError, match="disposition is invalid"):
        OnlyResearchJobOutcome(OnlyResearchJobStatus.SUCCEEDED, "UNKNOWN", "a" * 64, "b" * 64, "c" * 64)


def test_job_plan_v2_requires_exact_publication_without_changing_calculation_identity(tmp_path):
    from onlyalpha.research.calculation.publication import OnlyResearchCalculationPublicationContract
    from onlyalpha.research.job import RESEARCH_JOB_PLAN_READINESS_SCHEMA_VERSION

    plan, _, _, _ = job_case(tmp_path)
    assert RESEARCH_JOB_PLAN_SCHEMA_VERSION == 1
    assert RESEARCH_JOB_PLAN_READINESS_SCHEMA_VERSION == 2
    publication = OnlyResearchCalculationPublicationContract()
    second = OnlyResearchJobPlan(plan.dataset_snapshot_fingerprint, plan.calculation_graph, 2, publication)
    assert second.calculation_fingerprint == plan.calculation_fingerprint
    assert second.publication is publication


@pytest.mark.parametrize("version", (True, False, 1.0, 2.0, "1", "2", 0, 3, None))
def test_job_plan_rejects_coerced_unknown_schema(version, tmp_path):
    plan, _, _, _ = job_case(tmp_path)
    with pytest.raises(OnlyResearchJobError, match="RESEARCH_JOB_INVALID"):
        replace(plan, schema_version=version)


@pytest.mark.parametrize("candidate", ("v1-with-publication", "v2-without-publication", "dict", "subclass", "corrupt"))
def test_job_plan_rejects_wrong_or_subclassed_publication_contract(tmp_path, candidate):
    from onlyalpha.research.calculation.publication import OnlyResearchCalculationPublicationContract

    class _Subclass(OnlyResearchCalculationPublicationContract):
        pass

    plan, _, _, _ = job_case(tmp_path)
    publication = OnlyResearchCalculationPublicationContract()
    if candidate == "corrupt":
        object.__setattr__(publication, "readiness_contract_version", True)
    claims = {
        "v1-with-publication": (1, publication),
        "v2-without-publication": (2, None),
        "dict": (2, publication.to_dict()),
        "subclass": (2, _Subclass()),
        "corrupt": (2, publication),
    }
    version, contract = claims[candidate]
    with pytest.raises(OnlyResearchJobError, match="RESEARCH_JOB_INVALID"):
        OnlyResearchJobPlan(plan.dataset_snapshot_fingerprint, plan.calculation_graph, version, contract)
