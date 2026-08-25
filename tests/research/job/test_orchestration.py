from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from onlyalpha.research import (
    OnlyResearchCalculationError,
    OnlyResearchCalculationResultStoreError,
    OnlyResearchJobDisposition,
    OnlyResearchJobError,
    OnlyResearchJobPhase,
    OnlyResearchJobPlan,
    OnlyResearchJobStatus,
)
from tests.research.job.support import job_case, research_job_executor


class _CountingCalculationExecutor:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.calls = 0

    def _execute_verified(self, snapshot_fingerprint, graph):
        self.calls += 1
        return self.delegate._execute_verified(snapshot_fingerprint, graph)


class _StoreProxy:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.load_calls = 0
        self.commit_calls = 0

    def load_verified(self, fingerprint):
        self.load_calls += 1
        return self.delegate.load_verified(fingerprint)

    def commit(self, execution, graph):
        self.commit_calls += 1
        return self.delegate.commit(execution, graph)

    def verify(self, fingerprint):
        return self.delegate.verify(fingerprint)

    def exists(self, fingerprint):
        return self.delegate.exists(fingerprint)


def _result_root(tmp_path: Path, fingerprint: str) -> Path:
    return tmp_path / "results" / "sha256" / fingerprint[:2] / fingerprint


def test_first_execution_then_verified_reuse_preserves_authoritative_identity(tmp_path) -> None:
    plan, calculation, result_store, _ = job_case(tmp_path)
    counted_calculation = _CountingCalculationExecutor(calculation)
    counted_store = _StoreProxy(result_store)
    job = research_job_executor(counted_calculation, counted_store)

    first = job.execute(plan)
    second = job.execute(plan)

    assert first.status is second.status is OnlyResearchJobStatus.SUCCEEDED
    assert first.disposition is OnlyResearchJobDisposition.EXECUTED
    assert second.disposition is OnlyResearchJobDisposition.REUSED
    assert first.calculation_fingerprint == second.calculation_fingerprint == plan.calculation_fingerprint
    assert first.calculation_result_fingerprint == second.calculation_result_fingerprint
    assert counted_calculation.calls == 1
    assert counted_store.commit_calls == 1
    assert counted_store.load_calls == 2


def test_fresh_instances_reuse_durable_result(tmp_path) -> None:
    plan, _, _, first = job_case(tmp_path)
    executed = first.execute(plan)
    repeated_plan, repeated_calculation, repeated_store, _ = job_case(tmp_path)
    counted = _CountingCalculationExecutor(repeated_calculation)
    reused = research_job_executor(counted, repeated_store).execute(repeated_plan)
    assert reused.disposition is OnlyResearchJobDisposition.REUSED
    assert reused.calculation_fingerprint == executed.calculation_fingerprint
    assert reused.calculation_result_fingerprint == executed.calculation_result_fingerprint
    assert counted.calls == 0


def test_fresh_process_reuses_exact_job_result(tmp_path) -> None:
    plan, _, _, job = job_case(tmp_path)
    executed = job.execute(plan)
    code = (
        "import json,sys; from datetime import UTC,datetime; from pathlib import Path; "
        "from onlyalpha.calculation import OnlyCalculationGraphDefinition,OnlyCalculationNodeDefinition,OnlyCalculationRegistry; "
        "from onlyalpha.research import OnlyParquetResearchCalculationResultStore,OnlyParquetResearchDatasetSnapshotStore,"
        "OnlyResearchCalculationBackendResolver,OnlyResearchCalculationExecutionEvidenceStore,"
        "OnlyResearchCalculationExecutor,OnlyResearchJobExecutor,OnlyResearchJobPlan; "
        "from onlyalpha_plugin_indicators.registration import TYPES,registrations,resolve_definition; "
        "d=OnlyParquetResearchDatasetSnapshotStore(Path(sys.argv[1])); r=OnlyCalculationRegistry(); "
        "[r.register(x) for x in registrations()]; g=OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition("
        "resolve_definition(TYPES[0],{'period':2})),)); c=OnlyResearchCalculationExecutor(d,"
        "OnlyResearchCalculationBackendResolver(r)); s=OnlyParquetResearchCalculationResultStore(Path(sys.argv[2]),d,"
        "audit_time=lambda:datetime(2026,8,14,tzinfo=UTC)); e=OnlyResearchCalculationExecutionEvidenceStore("
        "Path(sys.argv[4])); o=OnlyResearchJobExecutor(c,s,e).execute("
        "OnlyResearchJobPlan(sys.argv[3],g)); print(json.dumps({'disposition':o.disposition.value,"
        "'calculation':o.calculation_fingerprint,'result':o.calculation_result_fingerprint},sort_keys=True))"
    )
    value = json.loads(
        subprocess.check_output(
            [
                sys.executable,
                "-c",
                code,
                str(tmp_path / "datasets"),
                str(tmp_path / "results"),
                plan.dataset_snapshot_fingerprint,
                str(tmp_path / "semantic"),
            ],
            text=True,
        )
    )
    assert value == {
        "calculation": executed.calculation_fingerprint,
        "disposition": "REUSED",
        "result": executed.calculation_result_fingerprint,
    }


@pytest.mark.parametrize("corruption", ("partition", "path-identity"))
def test_corrupt_or_invalid_result_fails_closed_without_recomputation(tmp_path, corruption) -> None:
    plan, calculation, _, job = job_case(tmp_path)
    job.execute(plan)
    root = _result_root(tmp_path, plan.calculation_fingerprint)
    if corruption == "partition":
        partition = next((root / "data").iterdir())
        partition.write_bytes(partition.read_bytes() + b"tamper")
    else:
        manifest = root / "manifest.json"
        payload = json.loads(manifest.read_text())
        payload["calculation_fingerprint"] = "0" * 64
        manifest.write_text(json.dumps(payload))
    counted = _CountingCalculationExecutor(calculation)
    before = tuple(path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file())
    with pytest.raises(OnlyResearchJobError) as raised:
        research_job_executor(counted, job_case(tmp_path)[2]).execute(plan)
    after = tuple(path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file())
    assert raised.value.phase is OnlyResearchJobPhase.RESULT_REUSE
    assert raised.value.code == "RESULT_CORRUPT"
    assert counted.calls == 0
    assert after == before


def test_result_invalid_is_not_treated_as_a_miss(tmp_path) -> None:
    plan, calculation, result_store, _ = job_case(tmp_path)
    counted = _CountingCalculationExecutor(calculation)

    class _InvalidReadStore(_StoreProxy):
        def load_verified(self, fingerprint):
            raise OnlyResearchCalculationResultStoreError("RESULT_INVALID", "injected")

    with pytest.raises(OnlyResearchJobError) as raised:
        research_job_executor(counted, _InvalidReadStore(result_store)).execute(plan)
    assert raised.value.phase is OnlyResearchJobPhase.RESULT_REUSE
    assert raised.value.code == "RESULT_INVALID"
    assert counted.calls == 0
    assert not result_store.exists(plan.calculation_fingerprint)


def test_dataset_verification_failure_publishes_no_result(tmp_path) -> None:
    valid, calculation, result_store, _ = job_case(tmp_path)
    plan = OnlyResearchJobPlan("0" * 64, valid.calculation_graph)
    with pytest.raises(OnlyResearchJobError) as raised:
        research_job_executor(calculation, result_store).execute(plan)
    assert raised.value.phase is OnlyResearchJobPhase.DATASET_VERIFICATION
    assert raised.value.code == "RESEARCH_DATASET_VERIFICATION_FAILED"
    assert not result_store.exists(plan.calculation_fingerprint)


class _FailingCalculationExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def _execute_verified(self, snapshot_fingerprint, graph):
        self.calls += 1
        raise OnlyResearchCalculationError("RESEARCH_EXECUTION_FAILED", "injected")


def test_calculation_failure_has_phase_and_no_durable_result(tmp_path) -> None:
    plan, _, result_store, _ = job_case(tmp_path)
    calculation = _FailingCalculationExecutor()
    with pytest.raises(OnlyResearchJobError) as raised:
        research_job_executor(calculation, result_store).execute(plan)
    assert raised.value.phase is OnlyResearchJobPhase.CALCULATION_EXECUTION
    assert raised.value.code == "RESEARCH_EXECUTION_FAILED"
    assert calculation.calls == 1
    assert not result_store.exists(plan.calculation_fingerprint)


class _FailingStore(_StoreProxy):
    def __init__(self, delegate, code: str) -> None:
        super().__init__(delegate)
        self.code = code

    def commit(self, execution, graph):
        self.commit_calls += 1
        raise OnlyResearchCalculationResultStoreError(self.code, "injected")


@pytest.mark.parametrize("code", ("RESULT_COMMIT_FAILED", "DETERMINISTIC_RESULT_CONFLICT"))
def test_commit_failure_and_deterministic_conflict_propagate(code, tmp_path) -> None:
    plan, calculation, result_store, _ = job_case(tmp_path)
    store = _FailingStore(result_store, code)
    with pytest.raises(OnlyResearchJobError) as raised:
        research_job_executor(calculation, store).execute(plan)
    assert raised.value.phase is OnlyResearchJobPhase.RESULT_COMMIT
    assert raised.value.code == code
    assert store.commit_calls == 1
    assert not result_store.exists(plan.calculation_fingerprint)


def test_reentry_before_and_after_commit_converges_without_job_database(tmp_path) -> None:
    plan, calculation, result_store, _ = job_case(tmp_path)
    failing = _FailingCalculationExecutor()
    with pytest.raises(OnlyResearchJobError):
        research_job_executor(failing, result_store).execute(plan)
    executed = research_job_executor(calculation, result_store).execute(plan)
    restarted = research_job_executor(calculation, result_store).execute(plan)
    assert executed.disposition is OnlyResearchJobDisposition.EXECUTED
    assert restarted.disposition is OnlyResearchJobDisposition.REUSED
    assert restarted.calculation_result_fingerprint == executed.calculation_result_fingerprint


def test_concurrent_same_job_converges_to_one_durable_authority(tmp_path) -> None:
    plan, calculation, result_store, _ = job_case(tmp_path)

    def run_job(_index):
        return research_job_executor(calculation, result_store).execute(plan)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(run_job, range(2)))
    assert {item.calculation_fingerprint for item in outcomes} == {plan.calculation_fingerprint}
    assert len({item.calculation_result_fingerprint for item in outcomes}) == 1
    root = _result_root(tmp_path, plan.calculation_fingerprint)
    assert {item.name for item in root.iterdir()} == {"data", "manifest.json"}
    assert (
        result_store.load_verified(plan.calculation_fingerprint).manifest.calculation_result_fingerprint
        == outcomes[0].calculation_result_fingerprint
    )


def test_executor_rejects_non_plan_input(tmp_path) -> None:
    _, calculation, result_store, _ = job_case(tmp_path)
    with pytest.raises(OnlyResearchJobError) as raised:
        research_job_executor(calculation, result_store).execute(object())
    assert raised.value.phase is OnlyResearchJobPhase.PLAN_VALIDATION
    assert raised.value.code == "RESEARCH_JOB_INVALID"


class _UnexpectedFailureStore(_StoreProxy):
    def __init__(self, delegate, fail_load: bool) -> None:
        super().__init__(delegate)
        self.fail_load = fail_load

    def load_verified(self, fingerprint):
        if self.fail_load:
            raise ValueError("unexpected read failure")
        return super().load_verified(fingerprint)

    def commit(self, execution, graph):
        raise ValueError("unexpected commit failure")


class _UnexpectedFailureCalculationExecutor:
    def _execute_verified(self, snapshot_fingerprint, graph):
        raise ValueError("unexpected calculation failure")


@pytest.mark.parametrize(
    ("calculation_factory", "store_factory", "phase", "code"),
    (
        (
            lambda calculation: calculation,
            lambda store: _UnexpectedFailureStore(store, True),
            OnlyResearchJobPhase.RESULT_REUSE,
            "RESEARCH_JOB_RESULT_REUSE_FAILED",
        ),
        (
            lambda calculation: _UnexpectedFailureCalculationExecutor(),
            lambda store: store,
            OnlyResearchJobPhase.CALCULATION_EXECUTION,
            "RESEARCH_JOB_EXECUTION_FAILED",
        ),
        (
            lambda calculation: calculation,
            lambda store: _UnexpectedFailureStore(store, False),
            OnlyResearchJobPhase.RESULT_COMMIT,
            "RESEARCH_JOB_RESULT_COMMIT_FAILED",
        ),
    ),
)
def test_unexpected_boundary_failure_is_phase_specific(
    calculation_factory, store_factory, phase, code, tmp_path
) -> None:
    plan, calculation, store, _ = job_case(tmp_path)
    with pytest.raises(OnlyResearchJobError) as raised:
        research_job_executor(calculation_factory(calculation), store_factory(store)).execute(plan)
    assert raised.value.phase is phase
    assert raised.value.code == code


def test_result_authority_must_match_exact_plan(tmp_path) -> None:
    plan, calculation, store, job = job_case(tmp_path)
    job.execute(plan)
    mismatched = OnlyResearchJobPlan("0" * 64, plan.calculation_graph)

    class _WrongResultStore(_StoreProxy):
        def load_verified(self, fingerprint):
            return store.load_verified(plan.calculation_fingerprint)

    with pytest.raises(OnlyResearchJobError) as raised:
        research_job_executor(calculation, _WrongResultStore(store)).execute(mismatched)
    assert raised.value.phase is OnlyResearchJobPhase.RESULT_REUSE
    assert raised.value.code == "RESULT_INVALID"
