from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres import (
    OnlyPostgresResearchExecutionStore,
    OnlyPostgresResearchRunStore,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.research.execution import (
    OnlyResearchExecutionClaim,
    OnlyResearchExecutionOwnershipLostError,
    OnlyResearchRunAttemptId,
    OnlyResearchRunAttemptState,
)
from onlyalpha.research.execution.worker import OnlyEngineResearchRuntimeExecutor
from onlyalpha.research.run import (
    OnlyResearchRun,
    OnlyResearchRunId,
    OnlyResearchRunState,
    only_research_admission_resolution_fingerprint,
)
from onlyalpha.research.specification import OnlyResearchSpecificationResolver
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.research import OnlyResearchRuntimeBoundary
from onlyalpha.runtime.result import OnlyRuntimeResultStatus
from scripts.database import _initialize_deployment
from tests.research.specification.support import registry, specification
from tests.runtime.research.support import workload_case
from tests.runtime_generation_process_support import only_prepare_test_process_generation

pytestmark = [pytest.mark.recovery, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]


class _NoopControl:
    def checkpoint(self, boundary: OnlyResearchRuntimeBoundary) -> None:
        del boundary


def _environment(postgres_dsn: str) -> dict[str, str]:
    return {
        **os.environ,
        "ONLYALPHA_POSTGRES_DSN": postgres_dsn,
        "UV_CACHE_DIR": "/tmp/onlyalpha-uv-cache",
    }


def _files(root: Path) -> dict[Path, bytes]:
    if not root.exists():
        return {}
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _wait_barrier(path: Path, process: subprocess.Popen[str], *, timeout: float = 40) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return
        if process.poll() is not None:
            raise AssertionError(f"crash worker exited before boundary: {process.returncode}")
        time.sleep(0.02)
    raise AssertionError("crash worker did not reach deterministic boundary")


def _wait_completed(
    store: OnlyPostgresResearchRunStore,
    run_id: OnlyResearchRunId,
    worker: subprocess.Popen[str],
    *,
    timeout: float = 60,
) -> OnlyResearchRun:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = store.load(run_id)
        if run.state.terminal:
            return run
        if worker.poll() is not None:
            raise AssertionError(f"recovery worker exited before completion: {worker.returncode}")
        time.sleep(0.05)
    raise AssertionError("recovery worker did not converge Run")


def _stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.parametrize("boundary", ("C1", "C2", "C3", "C4"))
def test_process_kill_boundaries_reenter_and_converge_exact_semantic_truth(
    postgres_dsn: str,
    tmp_path: Path,
    boundary: str,
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    _initialize_deployment(postgres_dsn, tmp_path)
    _, workload = workload_case(tmp_path)
    resolver = OnlyResearchSpecificationResolver(registry())
    spec = specification(workload.dataset_snapshot_fingerprint)
    resolution = resolver.resolve(spec)
    run_id = OnlyResearchRunId(f"00000000-0000-4000-8000-{8610 + int(boundary[-1]):012d}")
    queued = OnlyResearchRun.queued(
        run_id=run_id,
        specification=spec,
        canonical_specification_payload=only_canonical_json(spec.to_dict()),
        admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(resolution),
        queued_at=datetime(2026, 8, 22, tzinfo=UTC),
    )
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    run_store.create_queued(queued)
    generation_root, generation = only_prepare_test_process_generation(
        tmp_path / "runtime-generation-authority",
        work_ids=(run_id.value,),
    )

    control_root = tmp_path.parent / f"{tmp_path.name}-control"
    _, control_workload = workload_case(control_root)
    control = OnlyEngineResearchRuntimeExecutor(control_root, only_default_engine_services(fail_fast=True)).execute(
        control_workload,
        _NoopControl(),
    )
    assert control.status is OnlyRuntimeResultStatus.COMPLETED

    barrier = tmp_path / f"{boundary}.barrier.json"
    crash = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.certification.p8_6.crash_worker",
            boundary,
            "--barrier",
            str(barrier),
            "--user-data-root",
            str(tmp_path),
            "--runtime-generation-authority-root",
            str(generation_root),
            "--runtime-generation-fingerprint",
            generation,
        ],
        env=_environment(postgres_dsn),
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _wait_barrier(barrier, crash)
    assert json.loads(barrier.read_text()) == {"boundary": boundary}
    running = run_store.load(run_id)
    assert running.state is OnlyResearchRunState.RUNNING
    with psycopg.connect(postgres_dsn) as connection:
        row = connection.execute(
            "SELECT attempt_id FROM research_run_attempt WHERE run_id = %s AND state = 'ACTIVE'",
            (run_id.value,),
        ).fetchone()
    assert row is not None
    execution = OnlyPostgresResearchExecutionStore(postgres_dsn)
    stale_claim = OnlyResearchExecutionClaim(execution.load_attempt(OnlyResearchRunAttemptId(str(row[0]))))
    layout = OnlyUserDataLayout(tmp_path)
    result_at_crash = _files(layout.research_result_root)
    artifact_at_crash = _files(layout.research_artifact_root)
    if boundary in {"C1", "C2"}:
        assert result_at_crash == {} and artifact_at_crash == {}
    elif boundary == "C3":
        assert result_at_crash and artifact_at_crash == {}
    else:
        assert result_at_crash and artifact_at_crash

    crash.kill()
    crash.wait(timeout=10)
    assert crash.returncode is not None and crash.returncode < 0
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE research_run_attempt SET lease_expires_at = last_heartbeat_at "
            "WHERE attempt_id = %s AND state = 'ACTIVE'",
            (stale_claim.attempt.attempt_id.value,),
        )

    recovery = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.runtime_generation_worker_main",
            "--user-data-root",
            str(tmp_path),
            "--polling-seconds",
            "0.05",
            "--lease-seconds",
            "30",
            "--heartbeat-seconds",
            "12",
            "--runtime-generation-authority-root",
            str(generation_root),
            "--runtime-generation-fingerprint",
            generation,
        ],
        env=_environment(postgres_dsn),
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        completed = _wait_completed(run_store, run_id, recovery)
    finally:
        _stop(recovery)
    assert completed.state is OnlyResearchRunState.COMPLETED
    assert completed.research_result_fingerprint == control.research_result_fingerprint
    assert completed.artifact_content_fingerprint == control.artifact_content_fingerprint
    assert _files(layout.research_result_root)
    assert _files(layout.research_artifact_root)
    if result_at_crash:
        assert _files(layout.research_result_root) == result_at_crash
    if artifact_at_crash:
        assert _files(layout.research_artifact_root) == artifact_at_crash

    expired = execution.load_attempt(stale_claim.attempt.attempt_id)
    assert expired.state is OnlyResearchRunAttemptState.EXPIRED
    with psycopg.connect(postgres_dsn) as connection:
        history = connection.execute(
            "SELECT attempt_number, state FROM research_run_attempt WHERE run_id = %s ORDER BY attempt_number",
            (run_id.value,),
        ).fetchall()
    assert history == [(1, "EXPIRED"), (2, "SUCCEEDED")]
    with pytest.raises(OnlyResearchExecutionOwnershipLostError):
        execution.complete(
            claim=stale_claim,
            run_finished_at=datetime.now(UTC) + timedelta(seconds=1),
            research_result_fingerprint=completed.research_result_fingerprint or "",
            artifact_content_fingerprint=completed.artifact_content_fingerprint or "",
            calculation_execution_evidence_fingerprints=(completed.calculation_execution_evidence_fingerprints),
        )
