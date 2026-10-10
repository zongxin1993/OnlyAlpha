"""A previously observed immutable prefix cannot become permission to recreate it."""

from __future__ import annotations

import pytest

from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendResolver
from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
from onlyalpha.research.calculation.execution_evidence import OnlyResearchCalculationExecutionEvidenceStore
from onlyalpha.research.calculation.result_store import OnlyParquetResearchCalculationResultStore
from onlyalpha.research.job.errors import OnlyResearchJobError
from onlyalpha.research.job.executor import _only_execute_generation_bound_calculation_job
from onlyalpha.research.job.plan import OnlyResearchJobPlan
from tests.research.artifact.test_calculation_v2 import _publication
from tests.research.artifact.test_calculation_v2_exact_inspection import _bytes
from tests.research.calculation.test_execution_readiness_v2 import PUBLICATION, _registry

pytestmark = pytest.mark.contract


@pytest.mark.parametrize("missing", ["calculation", "evidence"])
def test_protected_generation_job_never_falls_back_to_backend_after_guard_loss(tmp_path, monkeypatch, missing):
    publish, _, context, _, _, evidence = _publication(tmp_path)
    artifact = publish()
    calculations = evidence._result_store
    calculation = artifact.manifest.calculations[0]
    producer = artifact.manifest.selected_evidence[0]
    plan = OnlyResearchJobPlan(calculation.dataset_snapshot_fingerprint, calculation.calculation_graph, 2, PUBLICATION)
    target = (
        calculations._target(calculation.calculation_fingerprint)
        if missing == "calculation"
        else evidence._target(producer.evidence_fingerprint)
    )
    target.rename(tmp_path / "unavailable-prefix")
    before = _bytes(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("protected Job reached numerical work")

    monkeypatch.setattr(OnlyResearchCalculationExecutor, "_execute_verified_v2", forbidden)
    with pytest.raises(OnlyResearchJobError) as raised:
        _only_execute_generation_bound_calculation_job(
            plan,
            OnlyResearchCalculationExecutor(
                calculations._dataset_store, OnlyResearchCalculationBackendResolver(_registry())
            ),
            OnlyParquetResearchCalculationResultStore(calculations._root, calculations._dataset_store),
            OnlyResearchCalculationExecutionEvidenceStore(evidence._semantic_root),
            calculations,
            evidence,
            context,
            required_result_fingerprint=calculation.calculation_result_fingerprint,
            required_evidence_fingerprint=producer.evidence_fingerprint,
        )
    assert (
        raised.value.code
        == {"calculation": "RESULT_NOT_FOUND", "evidence": "RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND"}[missing]
    )
    assert _bytes(tmp_path) == before
    assert not target.exists()


def test_result_only_new_producer_does_not_recreate_calculation_lost_during_execution(tmp_path, monkeypatch):
    publish, _, context, _, _, evidence = _publication(tmp_path)
    artifact = publish()
    calculations = evidence._result_store
    calculation = artifact.manifest.calculations[0]
    producer = artifact.manifest.selected_evidence[0]
    evidence._target(producer.evidence_fingerprint).rename(tmp_path / "unavailable-producer")
    plan = OnlyResearchJobPlan(calculation.dataset_snapshot_fingerprint, calculation.calculation_graph, 2, PUBLICATION)
    target = calculations._target(calculation.calculation_fingerprint)
    execute = OnlyResearchCalculationExecutor._execute_verified_v2
    observed = []

    def lose_result_after_execution(self, *args, **kwargs):
        sealed = execute(self, *args, **kwargs)
        target.rename(tmp_path / "unavailable-calculation")
        observed.append(_bytes(tmp_path))
        return sealed

    monkeypatch.setattr(OnlyResearchCalculationExecutor, "_execute_verified_v2", lose_result_after_execution)
    with pytest.raises(OnlyResearchJobError, match="RESULT_NOT_FOUND"):
        _only_execute_generation_bound_calculation_job(
            plan,
            OnlyResearchCalculationExecutor(
                calculations._dataset_store, OnlyResearchCalculationBackendResolver(_registry())
            ),
            OnlyParquetResearchCalculationResultStore(calculations._root, calculations._dataset_store),
            OnlyResearchCalculationExecutionEvidenceStore(evidence._semantic_root),
            calculations,
            evidence,
            context,
        )
    assert len(observed) == 1
    assert _bytes(tmp_path) == observed[0]
    assert not target.exists()
