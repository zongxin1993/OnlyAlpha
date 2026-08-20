from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import psycopg
import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.persistence.postgres import (
    DEFAULT_MIGRATION_ROOT,
    OnlyPostgresMigrationAuthority,
    OnlyPostgresResearchExecutionStore,
    OnlyPostgresResearchRunStore,
)
from onlyalpha.research.artifact.store import OnlyParquetResearchArtifactStore
from onlyalpha.research.calculation.result_store import OnlyParquetResearchCalculationResultStore
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.evaluation.result_store import OnlyParquetResearchStatisticsResultStore
from onlyalpha.research.execution import (
    OnlyEngineResearchRuntimeExecutor,
    OnlyResearchCancellationRecoveryReconciler,
    OnlyResearchExecutionOwnershipLostError,
    OnlyResearchExecutionPolicy,
    OnlyResearchRetryDecision,
    OnlyResearchRunAttemptId,
    OnlyResearchRunAttemptState,
    OnlyResearchSemanticCompletionInspection,
    OnlyResearchSemanticCompletionStatus,
    OnlyResearchVerifiedSemanticCompletionProbe,
    OnlyResearchWorker,
    OnlyResearchWorkerInstanceId,
    OnlyResearchWorkerOutcomeKind,
)
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore
from onlyalpha.research.run import (
    OnlyResearchRun,
    OnlyResearchRunFailure,
    OnlyResearchRunFailurePhase,
    OnlyResearchRunId,
    OnlyResearchRunState,
    only_research_admission_resolution_fingerprint,
)
from onlyalpha.research.specification import OnlyResearchSpecificationResolver
from onlyalpha.runtime.research import OnlyResearchRuntimeBoundary
from tests.research.specification.support import registry, specification
from tests.runtime.research.support import workload_case

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]
NOW = datetime(2026, 8, 18, 1, 2, 3, tzinfo=UTC)
M1 = "0001_research_run_operational_authority"
M2 = "0002_research_run_authority_hardening"
M3 = "0003_research_run_attempt_authority"
M4 = "0004_research_run_submission_and_read_projection"
M5 = "0005_research_specification_v2_admission"
WORKER_1 = OnlyResearchWorkerInstanceId("00000000-0000-4000-8000-000000000301")
WORKER_2 = OnlyResearchWorkerInstanceId("00000000-0000-4000-8000-000000000302")


def _queued(run_id: int) -> OnlyResearchRun:
    spec = specification()
    resolution = OnlyResearchSpecificationResolver(registry()).resolve(spec)
    return OnlyResearchRun.queued(
        run_id=OnlyResearchRunId(f"00000000-0000-4000-8000-{run_id:012d}"),
        specification=spec,
        canonical_specification_payload=only_canonical_json(spec.to_dict()),
        admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(resolution),
        queued_at=NOW,
    )


def _claim(
    store: OnlyPostgresResearchExecutionStore,
    worker: OnlyResearchWorkerInstanceId,
    attempt_number: int,
    *,
    max_attempts: int = 3,
):
    return store.claim_next(
        worker_instance_id=worker,
        attempt_id=OnlyResearchRunAttemptId(f"00000000-0000-4000-8001-{attempt_number:012d}"),
        lease_duration=timedelta(minutes=2),
        max_attempts=max_attempts,
        run_started_at=NOW + timedelta(seconds=1),
    )


def _reconciler(
    postgres_dsn: str,
    root: Path,
    *,
    now: datetime = NOW + timedelta(minutes=4),
) -> OnlyResearchCancellationRecoveryReconciler:
    layout = OnlyUserDataLayout(root)
    dataset = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    calculation = OnlyParquetResearchCalculationResultStore(layout.research_calculation_result_root, dataset)
    statistics = OnlyParquetResearchStatisticsResultStore(layout.research_statistics_result_root, calculation)
    result = OnlyJsonResearchResultStore(layout.research_result_root, statistics)
    artifact = OnlyParquetResearchArtifactStore(layout.research_artifact_root)
    return OnlyResearchCancellationRecoveryReconciler(
        execution_store=OnlyPostgresResearchExecutionStore(postgres_dsn),
        resolver=OnlyResearchSpecificationResolver(registry()),
        completion_probe=OnlyResearchVerifiedSemanticCompletionProbe(result, artifact),
        now_utc=lambda: now,
    )


def _queued_workload(root: Path, run_id: int):
    _, workload = workload_case(root)
    resolver = OnlyResearchSpecificationResolver(registry())
    spec = specification(workload.dataset_snapshot_fingerprint)
    resolution = resolver.resolve(spec)
    queued = OnlyResearchRun.queued(
        run_id=OnlyResearchRunId(f"00000000-0000-4000-8000-{run_id:012d}"),
        specification=spec,
        canonical_specification_payload=only_canonical_json(spec.to_dict()),
        admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(resolution),
        queued_at=NOW,
    )
    return queued, resolution


def test_existing_m1_m2_database_plans_exact_forward_suffix_and_preserves_run(
    postgres_dsn: str, tmp_path: Path
) -> None:
    for migration_id in (M1, M2):
        source = DEFAULT_MIGRATION_ROOT / f"{migration_id}.sql"
        (tmp_path / source.name).write_bytes(source.read_bytes())
    assert OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=tmp_path).migrate() == (M1, M2)
    run = OnlyPostgresResearchRunStore(postgres_dsn).create_queued(_queued(310))
    authority = OnlyPostgresMigrationAuthority(postgres_dsn)
    assert tuple(item.migration_id for item in authority.plan()) == (M3, M4, M5)
    assert authority.migrate() == (M3, M4, M5)
    assert OnlyPostgresResearchRunStore(postgres_dsn).load(run.run_id) == run


def test_two_workers_claim_one_run_with_one_atomic_active_attempt(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    OnlyPostgresResearchRunStore(postgres_dsn).create_queued(_queued(311))
    barrier = Barrier(2)

    def compete(worker: OnlyResearchWorkerInstanceId, ordinal: int):
        barrier.wait()
        return _claim(OnlyPostgresResearchExecutionStore(postgres_dsn), worker, ordinal)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            item.result()
            for item in (
                executor.submit(compete, WORKER_1, 1),
                executor.submit(compete, WORKER_2, 2),
            )
        )
    claims = tuple(item for item in outcomes if item is not None)
    assert len(claims) == 1
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT state, revision FROM research_run").fetchone() == ("RUNNING", 1)
        assert connection.execute("SELECT COUNT(*) FROM research_run_attempt WHERE state = 'ACTIVE'").fetchone() == (1,)


def test_claim_order_is_queued_at_then_run_id_and_workers_do_not_duplicate(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    for ordinal in (314, 312, 313):
        run_store.create_queued(_queued(ordinal))
    store = OnlyPostgresResearchExecutionStore(postgres_dsn)
    claims = tuple(_claim(store, WORKER_1, ordinal) for ordinal in (11, 12, 13))
    assert [item.attempt.run_id.value for item in claims if item is not None] == [
        "00000000-0000-4000-8000-000000000312",
        "00000000-0000-4000-8000-000000000313",
        "00000000-0000-4000-8000-000000000314",
    ]


def test_four_workers_concurrently_claim_ten_runs_without_authoritative_duplicates(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    for ordinal in range(330, 340):
        run_store.create_queued(_queued(ordinal))
    workers = tuple(OnlyResearchWorkerInstanceId(f"00000000-0000-4000-8002-{ordinal:012d}") for ordinal in range(1, 5))

    def claim(ordinal: int):
        return _claim(
            OnlyPostgresResearchExecutionStore(postgres_dsn),
            workers[ordinal % len(workers)],
            100 + ordinal,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        claims = tuple(executor.map(claim, range(10)))
    run_ids = [item.attempt.run_id for item in claims if item is not None]
    assert len(run_ids) == 10 and len(set(run_ids)) == 10
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT run_id) FROM research_run_attempt WHERE state = 'ACTIVE'"
        ).fetchone() == (10, 10)


def test_heartbeat_expiry_reclaim_and_stale_worker_fencing(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    run_store.create_queued(_queued(315))
    store = OnlyPostgresResearchExecutionStore(postgres_dsn)
    first = _claim(store, WORKER_1, 21)
    assert first is not None
    renewed = store.heartbeat(
        attempt_id=first.attempt.attempt_id,
        worker_instance_id=WORKER_1,
        lease_duration=timedelta(minutes=3),
    )
    assert renewed.last_heartbeat_at > first.attempt.last_heartbeat_at
    assert renewed.lease_expires_at > first.attempt.lease_expires_at
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE research_run_attempt SET lease_expires_at = last_heartbeat_at WHERE attempt_id = %s",
            (first.attempt.attempt_id.value,),
        )
    expired = store.expire_next(max_attempts=3, run_finished_at=NOW + timedelta(minutes=5))
    assert expired is not None and expired.state is OnlyResearchRunAttemptState.EXPIRED
    second = _claim(store, WORKER_2, 22)
    assert second is not None
    assert second.attempt.attempt_number == 2 and second.attempt.attempt_id != first.attempt.attempt_id
    with pytest.raises(OnlyResearchExecutionOwnershipLostError):
        store.heartbeat(
            attempt_id=first.attempt.attempt_id,
            worker_instance_id=WORKER_1,
            lease_duration=timedelta(minutes=2),
        )
    for operation in (
        lambda: store.complete(
            claim=first,
            run_finished_at=NOW + timedelta(minutes=6),
            research_result_fingerprint="b" * 64,
            artifact_content_fingerprint="c" * 64,
        ),
        lambda: store.fail(
            claim=first,
            run_finished_at=NOW + timedelta(minutes=6),
            failure=OnlyResearchRunFailure(OnlyResearchRunFailurePhase.OPERATIONAL, "STALE", "stale"),
            retry_decision=OnlyResearchRetryDecision.FINAL_FAIL,
        ),
        lambda: store.cancel(claim=first, run_finished_at=NOW + timedelta(minutes=6)),
    ):
        with pytest.raises(OnlyResearchExecutionOwnershipLostError):
            operation()
    completed = store.complete(
        claim=second,
        run_finished_at=NOW + timedelta(minutes=6),
        research_result_fingerprint="b" * 64,
        artifact_content_fingerprint="c" * 64,
    )
    assert completed.state is OnlyResearchRunState.COMPLETED


def test_retry_is_attempt_local_bounded_and_terminal_run_never_reopens(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    run_store.create_queued(_queued(316))
    store = OnlyPostgresResearchExecutionStore(postgres_dsn)
    failure = OnlyResearchRunFailure(
        OnlyResearchRunFailurePhase.OPERATIONAL, "UNEXPECTED_WORKER_FAILURE", "worker died"
    )
    first = _claim(store, WORKER_1, 31, max_attempts=2)
    assert first is not None
    retrying = store.fail(
        claim=first,
        run_finished_at=NOW + timedelta(minutes=1),
        failure=failure,
        retry_decision=OnlyResearchRetryDecision.RETRY,
    )
    assert retrying.state is OnlyResearchRunState.RUNNING
    second = _claim(store, WORKER_2, 32, max_attempts=2)
    assert second is not None and second.attempt.attempt_number == 2
    failed = store.fail(
        claim=second,
        run_finished_at=NOW + timedelta(minutes=2),
        failure=failure,
        retry_decision=OnlyResearchRetryDecision.FINAL_FAIL,
    )
    assert failed.state is OnlyResearchRunState.FAILED
    assert _claim(store, WORKER_1, 33, max_attempts=2) is None


def test_cancellation_and_completion_race_preserve_committed_semantics(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    store = OnlyPostgresResearchExecutionStore(postgres_dsn)
    queued = run_store.create_queued(_queued(317))
    direct = queued.transition(OnlyResearchRunState.CANCELLED, at=NOW + timedelta(seconds=1))
    run_store.commit_transition(queued, direct)
    assert _claim(store, WORKER_1, 41) is None

    run_store.create_queued(_queued(318))
    claim = _claim(store, WORKER_1, 42)
    assert claim is not None
    running = run_store.load(claim.attempt.run_id)
    requested = running.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=2))
    run_store.commit_transition(running, requested)
    completed = store.complete(
        claim=claim,
        run_finished_at=NOW + timedelta(seconds=3),
        research_result_fingerprint="b" * 64,
        artifact_content_fingerprint="c" * 64,
    )
    assert completed.state is OnlyResearchRunState.COMPLETED
    assert completed.cancel_requested_at == requested.cancel_requested_at


def test_database_constraints_reject_duplicate_or_invalid_attempt_facts(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    OnlyPostgresResearchRunStore(postgres_dsn).create_queued(_queued(319))
    store = OnlyPostgresResearchExecutionStore(postgres_dsn)
    claim = _claim(store, WORKER_1, 51)
    assert claim is not None
    values = (
        "00000000-0000-4000-8001-000000000052",
        claim.attempt.run_id.value,
        2,
        "ACTIVE",
        WORKER_2.value,
        claim.attempt.claimed_at,
        claim.attempt.last_heartbeat_at,
        claim.attempt.lease_expires_at,
    )
    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.UniqueViolation):
        connection.execute(
            "INSERT INTO research_run_attempt "
            "(attempt_id, run_id, attempt_number, state, worker_instance_id, claimed_at, "
            "last_heartbeat_at, lease_expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            values,
        )
    with psycopg.connect(postgres_dsn) as connection, pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            "INSERT INTO research_run_attempt "
            "(attempt_id, run_id, attempt_number, state, worker_instance_id, claimed_at, "
            "last_heartbeat_at, lease_expires_at) VALUES (%s,%s,0,'UNKNOWN',%s,%s,%s,%s)",
            (
                "00000000-0000-4000-8001-000000000053",
                claim.attempt.run_id.value,
                WORKER_2.value,
                NOW,
                NOW,
                NOW,
            ),
        )


def test_execution_policy_defaults_are_safe_and_bounded() -> None:
    policy = OnlyResearchExecutionPolicy()
    assert policy.heartbeat_interval < policy.lease_duration
    assert policy.max_attempts == 3


class _NoopRuntimeControl:
    def checkpoint(self, boundary: OnlyResearchRuntimeBoundary) -> None:
        del boundary


def test_artifact_commit_crash_reenters_real_engine_and_completes_with_new_services(
    postgres_dsn: str, tmp_path: Path
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    _, workload = workload_case(tmp_path)
    resolver = OnlyResearchSpecificationResolver(registry())
    spec = specification(workload.dataset_snapshot_fingerprint)
    resolution = resolver.resolve(spec)
    queued = OnlyResearchRun.queued(
        run_id=OnlyResearchRunId("00000000-0000-4000-8000-000000000320"),
        specification=spec,
        canonical_specification_payload=only_canonical_json(spec.to_dict()),
        admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(resolution),
        queued_at=NOW,
    )
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    run_store.create_queued(queued)
    first_store = OnlyPostgresResearchExecutionStore(postgres_dsn)
    first = _claim(first_store, WORKER_1, 61)
    assert first is not None

    first_result = OnlyEngineResearchRuntimeExecutor(tmp_path).execute(resolution.workload, _NoopRuntimeControl())
    assert first_result.status.value == "COMPLETED"
    assert run_store.load(queued.run_id).state is OnlyResearchRunState.RUNNING
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE research_run_attempt SET lease_expires_at = last_heartbeat_at WHERE attempt_id = %s",
            (first.attempt.attempt_id.value,),
        )

    restarted_store = OnlyPostgresResearchExecutionStore(postgres_dsn)
    assert restarted_store.expire_next(max_attempts=3, run_finished_at=NOW + timedelta(minutes=3)) is not None
    second = _claim(restarted_store, WORKER_2, 62)
    assert second is not None and second.attempt.attempt_number == 2
    worker = OnlyResearchWorker(
        worker_instance_id=WORKER_2,
        execution_store=restarted_store,
        run_store=OnlyPostgresResearchRunStore(postgres_dsn),
        resolver=OnlyResearchSpecificationResolver(registry()),
        dataset_store=OnlyParquetResearchDatasetSnapshotStore(OnlyUserDataLayout(tmp_path).research_dataset_root),
        runtime_executor=OnlyEngineResearchRuntimeExecutor(tmp_path),
        policy=OnlyResearchExecutionPolicy(),
        now_utc=lambda: NOW + timedelta(minutes=4),
    )
    outcome = worker.execute_claim(second)
    assert outcome.kind is OnlyResearchWorkerOutcomeKind.COMPLETED
    completed = OnlyPostgresResearchRunStore(postgres_dsn).load(queued.run_id)
    assert completed.state is OnlyResearchRunState.COMPLETED
    assert completed.research_result_fingerprint == first_result.research_result_fingerprint
    assert completed.artifact_content_fingerprint == first_result.artifact_content_fingerprint


def test_result_commit_crash_reenters_real_engine_without_rewriting_result(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    _, workload = workload_case(tmp_path)
    resolver = OnlyResearchSpecificationResolver(registry())
    spec = specification(workload.dataset_snapshot_fingerprint)
    resolution = resolver.resolve(spec)
    queued = OnlyResearchRun.queued(
        run_id=OnlyResearchRunId("00000000-0000-4000-8000-000000000321"),
        specification=spec,
        canonical_specification_payload=only_canonical_json(spec.to_dict()),
        admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(resolution),
        queued_at=NOW,
    )
    OnlyPostgresResearchRunStore(postgres_dsn).create_queued(queued)
    first_store = OnlyPostgresResearchExecutionStore(postgres_dsn)
    first = _claim(first_store, WORKER_1, 71)
    assert first is not None

    def crash_after_result(self: object, candidate: object) -> object:
        del self, candidate
        raise RuntimeError("simulated process loss after Result commit")

    monkeypatch.setattr(OnlyParquetResearchArtifactStore, "commit", crash_after_result)
    failed = OnlyEngineResearchRuntimeExecutor(tmp_path).execute(resolution.workload, _NoopRuntimeControl())
    assert failed.status.value == "FAILED" and failed.phase is not None
    assert failed.phase.value == "ARTIFACT_COMMIT"
    result_root = OnlyUserDataLayout(tmp_path).research_result_root
    committed_result = {
        path.relative_to(result_root): path.read_bytes() for path in result_root.rglob("*") if path.is_file()
    }
    assert committed_result
    monkeypatch.undo()
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE research_run_attempt SET lease_expires_at = last_heartbeat_at WHERE attempt_id = %s",
            (first.attempt.attempt_id.value,),
        )
    restarted_store = OnlyPostgresResearchExecutionStore(postgres_dsn)
    restarted_store.expire_next(max_attempts=3, run_finished_at=NOW + timedelta(minutes=3))
    second = _claim(restarted_store, WORKER_2, 72)
    assert second is not None
    worker = OnlyResearchWorker(
        worker_instance_id=WORKER_2,
        execution_store=restarted_store,
        run_store=OnlyPostgresResearchRunStore(postgres_dsn),
        resolver=OnlyResearchSpecificationResolver(registry()),
        dataset_store=OnlyParquetResearchDatasetSnapshotStore(OnlyUserDataLayout(tmp_path).research_dataset_root),
        runtime_executor=OnlyEngineResearchRuntimeExecutor(tmp_path),
        policy=OnlyResearchExecutionPolicy(),
        now_utc=lambda: NOW + timedelta(minutes=4),
    )
    assert worker.execute_claim(second).kind is OnlyResearchWorkerOutcomeKind.COMPLETED
    assert {
        path.relative_to(result_root): path.read_bytes() for path in result_root.rglob("*") if path.is_file()
    } == committed_result


def test_expired_cancel_requested_attempt_waits_for_semantic_reconciliation(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    run_store.create_queued(_queued(322))
    store = OnlyPostgresResearchExecutionStore(postgres_dsn)
    claim = _claim(store, WORKER_1, 81)
    assert claim is not None
    running = run_store.load(claim.attempt.run_id)
    run_store.commit_transition(
        running,
        running.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=2)),
    )
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE research_run_attempt SET lease_expires_at = last_heartbeat_at WHERE attempt_id = %s",
            (claim.attempt.attempt_id.value,),
        )
    assert store.expire_next(max_attempts=3, run_finished_at=NOW + timedelta(minutes=1)) is not None
    assert run_store.load(claim.attempt.run_id).state is OnlyResearchRunState.CANCEL_REQUESTED


def test_cancel_crash_after_semantic_commit_reconciles_completed_on_last_attempt(
    postgres_dsn: str, tmp_path: Path
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    queued, resolution = _queued_workload(tmp_path, 323)
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    run_store.create_queued(queued)
    store = OnlyPostgresResearchExecutionStore(postgres_dsn)
    claim = _claim(store, WORKER_1, 82, max_attempts=1)
    assert claim is not None and claim.attempt.attempt_number == 1
    semantic = OnlyEngineResearchRuntimeExecutor(tmp_path).execute(resolution.workload, _NoopRuntimeControl())
    assert semantic.status.value == "COMPLETED"
    running = run_store.load(queued.run_id)
    requested = run_store.commit_transition(
        running,
        running.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=2)),
    )
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE research_run_attempt SET lease_expires_at = last_heartbeat_at WHERE attempt_id = %s",
            (claim.attempt.attempt_id.value,),
        )
    restarted = OnlyPostgresResearchExecutionStore(postgres_dsn)
    expired = restarted.expire_next(max_attempts=1, run_finished_at=NOW + timedelta(minutes=3))
    assert expired is not None and expired.state is OnlyResearchRunAttemptState.EXPIRED

    completed = _reconciler(postgres_dsn, tmp_path).reconcile_once()
    assert completed is not None and completed.state is OnlyResearchRunState.COMPLETED
    assert completed.cancel_requested_at == requested.cancel_requested_at
    assert completed.research_result_fingerprint == semantic.research_result_fingerprint
    assert completed.artifact_content_fingerprint == semantic.artifact_content_fingerprint
    assert (
        restarted.claim_next(
            worker_instance_id=WORKER_2,
            attempt_id=OnlyResearchRunAttemptId("00000000-0000-4000-8001-000000000083"),
            lease_duration=timedelta(minutes=2),
            max_attempts=1,
            run_started_at=NOW + timedelta(minutes=5),
        )
        is None
    )
    with pytest.raises(OnlyResearchExecutionOwnershipLostError):
        store.complete(
            claim=claim,
            run_finished_at=NOW + timedelta(minutes=6),
            research_result_fingerprint=semantic.research_result_fingerprint,
            artifact_content_fingerprint=semantic.artifact_content_fingerprint,
        )


def test_cancel_crash_without_complete_semantics_reconciles_cancelled(postgres_dsn: str, tmp_path: Path) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    run_store.create_queued(_queued(324))
    store = OnlyPostgresResearchExecutionStore(postgres_dsn)
    claim = _claim(store, WORKER_1, 84)
    assert claim is not None
    running = run_store.load(claim.attempt.run_id)
    run_store.commit_transition(
        running,
        running.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=2)),
    )
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE research_run_attempt SET lease_expires_at = last_heartbeat_at WHERE attempt_id = %s",
            (claim.attempt.attempt_id.value,),
        )
    store.expire_next(max_attempts=3, run_finished_at=NOW + timedelta(minutes=1))
    cancelled = _reconciler(postgres_dsn, tmp_path).reconcile_once()
    assert cancelled is not None and cancelled.state is OnlyResearchRunState.CANCELLED
    assert cancelled.research_result_fingerprint is None
    assert cancelled.artifact_content_fingerprint is None


def test_partial_result_is_preserved_but_does_not_force_artifact_work(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    queued, resolution = _queued_workload(tmp_path, 325)
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    run_store.create_queued(queued)
    store = OnlyPostgresResearchExecutionStore(postgres_dsn)
    claim = _claim(store, WORKER_1, 85)
    assert claim is not None

    def crash_after_result(self: object, candidate: object) -> object:
        del self, candidate
        raise RuntimeError("simulated process loss after Result commit")

    monkeypatch.setattr(OnlyParquetResearchArtifactStore, "commit", crash_after_result)
    failed = OnlyEngineResearchRuntimeExecutor(tmp_path).execute(resolution.workload, _NoopRuntimeControl())
    assert failed.status.value == "FAILED"
    result_root = OnlyUserDataLayout(tmp_path).research_result_root
    committed = {path.relative_to(result_root): path.read_bytes() for path in result_root.rglob("*") if path.is_file()}
    assert committed
    monkeypatch.undo()
    running = run_store.load(queued.run_id)
    run_store.commit_transition(
        running,
        running.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=2)),
    )
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE research_run_attempt SET lease_expires_at = last_heartbeat_at WHERE attempt_id = %s",
            (claim.attempt.attempt_id.value,),
        )
    store.expire_next(max_attempts=3, run_finished_at=NOW + timedelta(minutes=1))
    cancelled = _reconciler(postgres_dsn, tmp_path).reconcile_once()
    assert cancelled is not None and cancelled.state is OnlyResearchRunState.CANCELLED
    assert {
        path.relative_to(result_root): path.read_bytes() for path in result_root.rglob("*") if path.is_file()
    } == committed
    assert not OnlyUserDataLayout(tmp_path).research_artifact_root.exists()


def test_corrupt_artifact_fails_closed_during_cancellation_recovery(postgres_dsn: str, tmp_path: Path) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    queued, resolution = _queued_workload(tmp_path, 326)
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    run_store.create_queued(queued)
    store = OnlyPostgresResearchExecutionStore(postgres_dsn)
    claim = _claim(store, WORKER_1, 86)
    assert claim is not None
    semantic = OnlyEngineResearchRuntimeExecutor(tmp_path).execute(resolution.workload, _NoopRuntimeControl())
    assert semantic.status.value == "COMPLETED"
    artifact_root = OnlyUserDataLayout(tmp_path).research_artifact_root
    manifest = next(artifact_root.rglob("artifact_manifest.json"))
    payload = manifest.read_bytes()
    manifest.write_bytes(b"[" + payload[1:])
    running = run_store.load(queued.run_id)
    run_store.commit_transition(
        running,
        running.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=2)),
    )
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE research_run_attempt SET lease_expires_at = last_heartbeat_at WHERE attempt_id = %s",
            (claim.attempt.attempt_id.value,),
        )
    store.expire_next(max_attempts=3, run_finished_at=NOW + timedelta(minutes=1))
    failed = _reconciler(postgres_dsn, tmp_path).reconcile_once()
    assert failed is not None and failed.state is OnlyResearchRunState.FAILED
    assert failed.failure is not None
    assert failed.failure.code == "CANCELLATION_RECOVERY_ARTIFACT_VERIFICATION_FAILED"


def test_concurrent_cancellation_reconciliation_has_one_terminal_cas_winner(postgres_dsn: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run_store = OnlyPostgresResearchRunStore(postgres_dsn)
    run_store.create_queued(_queued(327))
    store = OnlyPostgresResearchExecutionStore(postgres_dsn)
    claim = _claim(store, WORKER_1, 87)
    assert claim is not None
    running = run_store.load(claim.attempt.run_id)
    requested = run_store.commit_transition(
        running,
        running.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=2)),
    )
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE research_run_attempt SET lease_expires_at = last_heartbeat_at WHERE attempt_id = %s",
            (claim.attempt.attempt_id.value,),
        )
    store.expire_next(max_attempts=3, run_finished_at=NOW + timedelta(minutes=1))
    inspection = OnlyResearchSemanticCompletionInspection(OnlyResearchSemanticCompletionStatus.ABSENT)
    barrier = Barrier(2)

    def reconcile() -> object:
        actor = OnlyPostgresResearchExecutionStore(postgres_dsn)
        barrier.wait()
        try:
            return actor.reconcile_cancellation(
                expected=requested,
                run_finished_at=NOW + timedelta(minutes=2),
                inspection=inspection,
            )
        except OnlyResearchExecutionOwnershipLostError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(item.result() for item in (executor.submit(reconcile), executor.submit(reconcile)))
    assert sum(isinstance(item, OnlyResearchRun) for item in outcomes) == 1
    assert sum(isinstance(item, OnlyResearchExecutionOwnershipLostError) for item in outcomes) == 1
    assert run_store.load(requested.run_id).state is OnlyResearchRunState.CANCELLED
