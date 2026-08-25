from __future__ import annotations

from pathlib import Path

import pytest

from onlyalpha.research import (
    OnlyResearchJobDisposition,
    OnlyResearchJobError,
    OnlyResearchJobExecutor,
    OnlyResearchJobOutcome,
    OnlyResearchJobPhase,
    OnlyResearchJobStatus,
    OnlyResearchSweepError,
    OnlyResearchSweepExecutor,
    OnlyResearchSweepPlanner,
)
from tests.research.job.support import research_job_executor
from tests.research.sweep.support import definition, execution_case, registry


class _CountingCalculationExecutor:
    def __init__(self, delegate) -> None:
        self.delegate = delegate
        self.calls = 0

    def _execute_verified(self, snapshot_fingerprint, graph):
        self.calls += 1
        return self.delegate._execute_verified(snapshot_fingerprint, graph)


def _plan(snapshot_fingerprint: str, candidates=(1, 3, 4)):
    return OnlyResearchSweepPlanner(registry()).plan(definition(snapshot_fingerprint, candidates=candidates))


def test_first_run_executes_and_second_identical_run_reuses_without_calculation(tmp_path) -> None:
    dataset, calculation, store = execution_case(tmp_path)
    plan = _plan(dataset.snapshot_fingerprint)
    first_counted = _CountingCalculationExecutor(calculation)
    first = OnlyResearchSweepExecutor(research_job_executor(first_counted, store)).execute(plan)
    second_counted = _CountingCalculationExecutor(calculation)
    second = OnlyResearchSweepExecutor(research_job_executor(second_counted, store)).execute(plan)
    assert first.total_cells == first.executed_count == 3
    assert first.reused_count == 0
    assert second.total_cells == second.reused_count == 3
    assert second.executed_count == 0
    assert first_counted.calls == 3
    assert second_counted.calls == 0
    assert [item.calculation_result_fingerprint for item in first.cells] == [
        item.calculation_result_fingerprint for item in second.cells
    ]


def test_partial_reentry_reuses_prefix_executes_suffix_and_converges_to_clean_identities(tmp_path) -> None:
    dataset, calculation, store = execution_case(tmp_path)
    plan = _plan(dataset.snapshot_fingerprint)
    job = research_job_executor(calculation, store)
    prefix = tuple(job.execute(cell.job_plan) for cell in plan.cells[:2])
    counted = _CountingCalculationExecutor(calculation)
    resumed = OnlyResearchSweepExecutor(research_job_executor(counted, store)).execute(plan)
    assert [cell.disposition for cell in resumed.cells] == [
        OnlyResearchJobDisposition.REUSED,
        OnlyResearchJobDisposition.REUSED,
        OnlyResearchJobDisposition.EXECUTED,
    ]
    assert counted.calls == 1
    assert [item.calculation_result_fingerprint for item in resumed.cells[:2]] == [
        item.calculation_result_fingerprint for item in prefix
    ]
    clean_dataset, clean_calculation, clean_store = execution_case(tmp_path / "clean")
    clean_plan = _plan(clean_dataset.snapshot_fingerprint)
    clean = OnlyResearchSweepExecutor(research_job_executor(clean_calculation, clean_store)).execute(clean_plan)
    assert [item.calculation_fingerprint for item in resumed.cells] == [
        item.calculation_fingerprint for item in clean.cells
    ]
    assert [item.calculation_result_fingerprint for item in resumed.cells] == [
        item.calculation_result_fingerprint for item in clean.cells
    ]


def _result_root(root: Path, fingerprint: str) -> Path:
    return root / "results" / "sha256" / fingerprint[:2] / fingerprint


def test_corrupt_result_fails_closed_at_exact_cell_without_reexecution(tmp_path) -> None:
    dataset, calculation, store = execution_case(tmp_path)
    plan = _plan(dataset.snapshot_fingerprint)
    job = research_job_executor(calculation, store)
    job.execute(plan.cells[0].job_plan)
    job.execute(plan.cells[1].job_plan)
    root = _result_root(tmp_path, plan.cells[1].calculation_fingerprint)
    partition = next((root / "data").iterdir())
    partition.write_bytes(partition.read_bytes() + b"tamper")
    counted = _CountingCalculationExecutor(calculation)
    with pytest.raises(OnlyResearchSweepError) as raised:
        OnlyResearchSweepExecutor(research_job_executor(counted, store)).execute(plan)
    assert raised.value.code == "SWEEP_JOB_FAILED"
    assert raised.value.ordinal == 1
    assert raised.value.job_phase is OnlyResearchJobPhase.RESULT_REUSE
    assert raised.value.job_code == "RESULT_CORRUPT"
    assert counted.calls == 0


class _FailingJobExecutor(OnlyResearchJobExecutor):
    def __init__(self, failure_ordinal: int) -> None:
        self.failure_ordinal = failure_ordinal
        self.calls: list[str] = []

    def execute(self, plan):
        self.calls.append(plan.calculation_fingerprint)
        if len(self.calls) - 1 == self.failure_ordinal:
            raise OnlyResearchJobError(OnlyResearchJobPhase.CALCULATION_EXECUTION, "INJECTED", "boom")
        return OnlyResearchJobOutcome(
            OnlyResearchJobStatus.SUCCEEDED,
            OnlyResearchJobDisposition.REUSED,
            plan.calculation_fingerprint,
            (str(len(self.calls)) * 64)[:64],
            "e" * 64,
        )


def test_execution_is_canonical_sequential_and_fail_fast_preserves_job_error() -> None:
    plan = OnlyResearchSweepPlanner(registry()).plan(definition(candidates=(1, 3, 4)))
    job = _FailingJobExecutor(1)
    with pytest.raises(OnlyResearchSweepError) as raised:
        OnlyResearchSweepExecutor(job).execute(plan)
    assert raised.value.code == "SWEEP_JOB_FAILED"
    assert raised.value.ordinal == 1
    assert raised.value.assignment == dict(plan.cells[1].assignment_by_key)
    assert raised.value.job_phase is OnlyResearchJobPhase.CALCULATION_EXECUTION
    assert raised.value.job_code == "INJECTED"
    assert len(job.calls) == 2


def test_executor_rejects_non_authority_inputs() -> None:
    with pytest.raises(TypeError):
        OnlyResearchSweepExecutor(object())  # type: ignore[arg-type]
    job = _FailingJobExecutor(99)
    with pytest.raises(OnlyResearchSweepError):
        OnlyResearchSweepExecutor(job).execute(object())  # type: ignore[arg-type]
