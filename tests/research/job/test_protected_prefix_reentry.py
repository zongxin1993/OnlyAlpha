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
from tests.research.calculation.test_runtime_execution_provenance import _context
from tests.research.job.support import readiness_job_case
from tests.research.job.test_readiness_publication import _job

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


@pytest.mark.parametrize("runtime", [False, True])
def test_selected_producer_loss_before_ack_is_not_initial_lookup_absence(tmp_path, monkeypatch, runtime):
    from onlyalpha.research.calculation.execution_evidence_v2 import OnlyResearchCalculationExecutionEvidenceStoreV2

    plan, calculation, legacy, results, evidence = readiness_job_case(tmp_path)
    context = _context(calculation, plan.calculation_graph) if runtime else None
    job = _job(calculation, legacy, results, evidence)

    def execute():
        if context is None:
            return job.execute(plan)
        return _only_execute_generation_bound_calculation_job(
            plan, calculation, legacy, legacy._test_execution_evidence_store, results, evidence, context
        )

    first = execute()
    target = evidence._target(first.calculation_execution_evidence_fingerprint)
    method = "load_exact_for_result" if runtime else "require_for_result"
    lookup = getattr(OnlyResearchCalculationExecutionEvidenceStoreV2, method)
    snapshots = []
    backend_calls = []

    def lose_after_read(self, *args, **kwargs):
        selected = lookup(self, *args, **kwargs)
        target.rename(tmp_path / "unavailable-selected-producer")
        snapshots.append(_bytes(tmp_path))
        return selected

    def forbidden(*args, **kwargs):
        backend_calls.append(True)
        raise AssertionError("selected producer loss authorized numerical work")

    monkeypatch.setattr(OnlyResearchCalculationExecutionEvidenceStoreV2, method, lose_after_read)
    monkeypatch.setattr(OnlyResearchCalculationExecutor, "_execute_verified_v2", forbidden)
    with pytest.raises(OnlyResearchJobError) as raised:
        execute()
    assert backend_calls == []
    assert raised.value.code == "RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND"
    assert len(snapshots) == 1
    assert snapshots[0] == _bytes(tmp_path)
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
