from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.research import OnlyParquetResearchDatasetSnapshotStore, OnlyParquetResearchScientificArtifactStore
from onlyalpha.research.artifact.errors import OnlyResearchArtifactStoreError
from onlyalpha.research.artifact.scientific_store import OnlyParquetResearchCalculationArtifactStore
from onlyalpha.research.runtime_errors import OnlyResearchRuntimePhase
from onlyalpha.runtime.research import OnlyResearchRuntimeBoundary, OnlyResearchRuntimeCancellationRequested
from tests.support.research_calculation_publication import calculation_workload_case


def test_official_sma_calculation_only_runtime_reuses_without_mutating_dataset(tmp_path: Path) -> None:
    outcomes = []
    for _ in range(2):
        engine, workload = calculation_workload_case(tmp_path)
        layout = OnlyUserDataLayout(tmp_path)
        datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
        before = datasets.load_verified_table(workload.dataset_snapshot_fingerprint).table.to_pydict()
        runtime_id = engine.add_research_workload(workload)
        engine.initialize()
        engine.start()
        outcome = engine.run_runtime(runtime_id)
        engine.stop()
        engine.close()
        assert outcome.status.value == "COMPLETED"
        assert outcome.statistics_outcomes == ()
        assert len(outcome.calculation_execution_evidence_fingerprints) == 1
        assert datasets.load_verified_table(workload.dataset_snapshot_fingerprint).table.to_pydict() == before
        outcomes.append(outcome)
    assert outcomes[0].direct_job_outcomes[0].disposition.value == "EXECUTED"
    assert outcomes[1].direct_job_outcomes[0].disposition.value == "REUSED"
    assert outcomes[0].determinism_fingerprint == outcomes[1].determinism_fingerprint
    artifact = OnlyParquetResearchCalculationArtifactStore(layout.research_artifact_root).load_verified(
        outcomes[0].research_result_fingerprint
    )
    assert artifact.manifest.plan.schema_version == 3
    assert artifact.statistics_rows == artifact.signal_rows == ()
    assert [item.decimal_value for item in artifact.variable_rows] == [
        "0.000000000000",
        "1.000000000000",
        "3.000000000000",
        "6.000000000000",
    ]
    assert artifact.graphs[0].graph.nodes[0].definition.type_id == "onlyalpha.indicator.sma"


def test_calculation_publication_reentry_in_fresh_process_preserves_identity(tmp_path: Path) -> None:
    program = (
        "import json,sys; from pathlib import Path; "
        "from tests.support.research_calculation_publication import calculation_workload_case; "
        "e,w=calculation_workload_case(Path(sys.argv[1])); r=e.add_research_workload(w); "
        "e.initialize(); e.start(); o=e.run_runtime(r); e.stop(); e.close(); "
        "print(json.dumps({'status':o.status.value,'result':o.research_result_fingerprint,"
        "'artifact':o.artifact_content_fingerprint,'determinism':o.determinism_fingerprint,"
        "'disposition':o.direct_job_outcomes[0].disposition.value}))"
    )
    first, second = [
        json.loads(subprocess.check_output([sys.executable, "-c", program, str(tmp_path)], text=True)) for _ in range(2)
    ]
    assert first.pop("disposition") == "EXECUTED"
    assert second.pop("disposition") == "REUSED"
    assert first == second
    assert first["status"] == "COMPLETED"


def test_changed_sma_parameters_have_distinct_calculation_and_publication_identity(tmp_path: Path) -> None:
    outcomes = []
    workloads = []
    for period in (2, 3):
        engine, workload = calculation_workload_case(tmp_path, period=period)
        runtime_id = engine.add_research_workload(workload)
        engine.initialize()
        engine.start()
        outcome = engine.run_runtime(runtime_id)
        engine.stop()
        assert outcome.status.value == "COMPLETED"
        outcomes.append(outcome)
        workloads.append(workload)
    assert workloads[0].dataset_snapshot_fingerprint == workloads[1].dataset_snapshot_fingerprint
    assert workloads[0].direct_jobs[0].calculation_fingerprint != workloads[1].direct_jobs[0].calculation_fingerprint
    assert outcomes[0].research_result_fingerprint != outcomes[1].research_result_fingerprint
    assert outcomes[0].artifact_content_fingerprint != outcomes[1].artifact_content_fingerprint


def test_failed_calculation_publication_preserves_result_and_exact_reentry_recovers(
    tmp_path: Path, monkeypatch
) -> None:
    engine, workload = calculation_workload_case(tmp_path)
    runtime_id = engine.add_research_workload(workload)
    engine.initialize()
    engine.start()
    original = OnlyParquetResearchScientificArtifactStore.publish_calculation

    def fail(self, *args):  # type: ignore[no-untyped-def]
        raise OnlyResearchArtifactStoreError("ARTIFACT_COMMIT_FAILED", "injected publication fault")

    monkeypatch.setattr(OnlyParquetResearchScientificArtifactStore, "publish_calculation", fail)
    failed = engine.run_runtime(runtime_id)
    engine.stop()
    assert failed.status.value == "FAILED"
    assert failed.phase is OnlyResearchRuntimePhase.ARTIFACT_COMMIT
    assert failed.research_result_fingerprint
    assert not failed.artifact_content_fingerprint
    monkeypatch.setattr(OnlyParquetResearchScientificArtifactStore, "publish_calculation", original)
    fresh, same = calculation_workload_case(tmp_path)
    fresh_id = fresh.add_research_workload(same)
    fresh.initialize()
    fresh.start()
    recovered = fresh.run_runtime(fresh_id)
    fresh.stop()
    assert recovered.status.value == "COMPLETED"
    assert recovered.research_result_fingerprint == failed.research_result_fingerprint
    assert recovered.direct_job_outcomes[0].disposition.value == "REUSED"


def test_cancel_before_calculation_artifact_does_not_publish_completed_fact(tmp_path: Path) -> None:
    engine, workload = calculation_workload_case(tmp_path)
    runtime_id = engine.add_research_workload(workload)
    engine.initialize()
    engine.start()

    class Cancel:
        def checkpoint(self, boundary: OnlyResearchRuntimeBoundary) -> None:
            if boundary is OnlyResearchRuntimeBoundary.BEFORE_ARTIFACT_COMMIT:
                raise OnlyResearchRuntimeCancellationRequested("injected cancellation")

    with pytest.raises(OnlyResearchRuntimeCancellationRequested):
        engine.run_runtime(runtime_id, research_control=Cancel())
    engine.stop()
    layout = OnlyUserDataLayout(tmp_path)
    assert not (layout.research_artifact_root / "research-calculation-v1").exists()


def test_existing_calculation_corruption_is_not_rebuilt_during_runtime_reentry(tmp_path: Path) -> None:
    engine, workload = calculation_workload_case(tmp_path)
    runtime_id = engine.add_research_workload(workload)
    engine.initialize()
    engine.start()
    completed = engine.run_runtime(runtime_id)
    engine.stop()
    assert completed.status.value == "COMPLETED"
    layout = OnlyUserDataLayout(tmp_path)
    fingerprint = workload.direct_jobs[0].calculation_fingerprint
    target = layout.research_calculation_result_root / "sha256" / fingerprint[:2] / fingerprint
    manifest_path = target / "manifest.json"
    assert manifest_path.is_file()
    manifest_path.write_bytes(b"corrupt")
    fresh, same = calculation_workload_case(tmp_path)
    fresh_id = fresh.add_research_workload(same)
    fresh.initialize()
    fresh.start()
    failed = fresh.run_runtime(fresh_id)
    fresh.stop()
    assert failed.status.value == "FAILED"
    assert failed.phase is OnlyResearchRuntimePhase.JOB_EXECUTION
    assert failed.direct_job_outcomes == ()
    assert manifest_path.read_bytes() == b"corrupt"
