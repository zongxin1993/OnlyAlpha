from __future__ import annotations

from pathlib import Path

import pytest

from onlyalpha.core.errors import OnlyLifecycleError
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.runtime.research import OnlyResearchRuntimePhase
from onlyalpha.runtime.result import OnlyRuntimeResultStatus
from tests.runtime.research.support import workload_case


def test_missing_dataset_fails_in_dataset_verification_phase(tmp_path: Path) -> None:
    _, workload = workload_case(tmp_path / "source")
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("missing-dataset"), tmp_path / "empty"))
    runtime_id = engine.add_research_workload(workload)
    engine.initialize()
    engine.start()
    result = engine.run_runtime(runtime_id)
    assert result.status is OnlyRuntimeResultStatus.FAILED
    assert result.phase is OnlyResearchRuntimePhase.DATASET_VERIFICATION
    assert result.code == "DATASET_SNAPSHOT_NOT_FOUND"
    engine.stop()


def test_corrupt_dataset_fails_closed_and_is_not_rebuilt(tmp_path: Path) -> None:
    engine, workload = workload_case(tmp_path)
    layout = OnlyUserDataLayout(tmp_path)
    manifest = next(layout.research_dataset_root.rglob("manifest.json"))
    manifest.write_text("{}", encoding="utf-8")
    runtime_id = engine.add_research_workload(workload)
    engine.initialize()
    engine.start()
    result = engine.run_runtime(runtime_id)
    assert result.status is OnlyRuntimeResultStatus.FAILED
    assert result.phase is OnlyResearchRuntimePhase.DATASET_VERIFICATION
    assert result.code == "DATASET_SNAPSHOT_CORRUPT"
    assert manifest.read_text(encoding="utf-8") == "{}"
    engine.stop()


def test_mixed_research_and_trading_engine_fails_closed(tmp_path: Path) -> None:
    engine, workload = workload_case(tmp_path)
    engine.add_research_workload(workload)
    engine.add_cluster_from_file("tests/fixtures/legacy_macd/cluster.json")
    validation = engine.validate()
    assert not validation.valid
    assert "MIXED_RESEARCH_TRADING_NOT_SUPPORTED" in validation.errors
    with pytest.raises(OnlyLifecycleError, match="MIXED_RESEARCH_TRADING_NOT_SUPPORTED"):
        engine.initialize()


@pytest.mark.parametrize(
    ("authority", "phase", "code"),
    (
        ("calculation-results", OnlyResearchRuntimePhase.JOB_EXECUTION, "RESULT_CORRUPT"),
        ("statistics-results", OnlyResearchRuntimePhase.STATISTICS_EXECUTION, "STATISTICS_RESULT_CORRUPT"),
        ("results", OnlyResearchRuntimePhase.RESULT_COMMIT, "RESEARCH_RESULT_CORRUPT"),
        ("artifacts", OnlyResearchRuntimePhase.ARTIFACT_COMMIT, "ARTIFACT_CORRUPT"),
    ),
)
def test_existing_corrupt_authority_is_never_rebuilt(
    tmp_path: Path,
    authority: str,
    phase: OnlyResearchRuntimePhase,
    code: str,
) -> None:
    first, workload = workload_case(tmp_path)
    runtime_id = first.add_research_workload(workload)
    first.initialize()
    first.start()
    assert first.run_runtime(runtime_id).status is OnlyRuntimeResultStatus.COMPLETED
    first.stop()
    root = tmp_path / "research" / authority
    manifest_name = "artifact_manifest.json" if authority == "artifacts" else "manifest.json"
    manifest = next(root.rglob(manifest_name))
    manifest.write_text("{}", encoding="utf-8")

    repeated, repeated_workload = workload_case(tmp_path)
    repeated_id = repeated.add_research_workload(repeated_workload)
    repeated.initialize()
    repeated.start()
    result = repeated.run_runtime(repeated_id)
    assert result.status is OnlyRuntimeResultStatus.FAILED
    assert result.phase is phase
    assert result.code == code
    assert manifest.read_text(encoding="utf-8") == "{}"
    repeated.stop()


def test_unstructured_job_failure_is_phase_aware_and_serializable(tmp_path: Path) -> None:
    engine, workload = workload_case(tmp_path)
    runtime_id = engine.add_research_workload(workload)
    engine.initialize()
    runtime = engine.runtime_sessions[0].runtime
    runtime._job_executor.execute = lambda plan: (_ for _ in ()).throw(RuntimeError("injected failure"))  # type: ignore[attr-defined,method-assign]
    engine.start()
    result = engine.run_runtime(runtime_id)
    assert result.phase is OnlyResearchRuntimePhase.JOB_EXECUTION
    assert result.code == "RESEARCH_RUNTIMEERROR"
    assert result.to_dict()["failure"] == {
        "phase": "JOB_EXECUTION",
        "code": "RESEARCH_RUNTIMEERROR",
        "detail": "injected failure",
    }
    engine.stop()


def test_sweep_failure_is_phase_aware(tmp_path: Path) -> None:
    from tests.runtime.research.support import sweep_only_workload_case

    engine, workload = sweep_only_workload_case(tmp_path)
    runtime_id = engine.add_research_workload(workload)
    engine.initialize()
    runtime = engine.runtime_sessions[0].runtime
    runtime._sweep_executor.execute = lambda plan: (_ for _ in ()).throw(RuntimeError("sweep failed"))  # type: ignore[attr-defined,method-assign]
    engine.start()
    result = engine.run_runtime(runtime_id)
    assert result.phase is OnlyResearchRuntimePhase.SWEEP_EXECUTION
    assert result.code == "RESEARCH_RUNTIMEERROR"
    engine.stop()
