from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
)
from onlyalpha.backtest import (
    OnlyBacktestAdmissionResolution,
    OnlyBacktestAttemptId,
    OnlyBacktestExecutionPolicy,
    OnlyBacktestProfileReference,
    OnlyBacktestRun,
    OnlyBacktestRunFailure,
    OnlyBacktestRunFailurePhase,
    OnlyBacktestRunId,
    OnlyBacktestRunState,
    OnlyBacktestSpecification,
    OnlyBacktestWorkerInstanceId,
)
from onlyalpha.backtest.errors import OnlyBacktestError, OnlyBacktestStateConflictError
from onlyalpha.persistence.postgres.backtest_store import OnlyPostgresBacktestStore
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]
NOW = datetime(2026, 9, 2, tzinfo=UTC)


def _queued(run_id: str = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa") -> OnlyBacktestRun:
    specification = OnlyBacktestSpecification(
        "a" * 64,
        "b" * 64,
        "c" * 64,
        OnlyBacktestProfileReference("fixed-capital", "1"),
        OnlyBacktestProfileReference("default-risk", "1"),
        OnlyBacktestProfileReference("virtual-next-bar", "1"),
        "USDT",
        "10000",
    )
    return OnlyBacktestRun.queued(
        run_id=OnlyBacktestRunId(run_id),
        specification=specification,
        admission_resolution=OnlyBacktestAdmissionResolution(
            1,
            "a" * 64,
            "b" * 64,
            "d" * 64,
            "e" * 64,
            "1" * 64,
            "2" * 64,
            "3" * 64,
            "kernel-v1",
            ("f" * 64,),
        ),
        queued_at=NOW,
    )


def _receipt(
    run: OnlyBacktestRun,
    command_id: str = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    command_fingerprint: str = "9" * 64,
) -> OnlyProductCommandReceipt:
    return OnlyProductCommandReceipt(
        OnlyProductCommandId(command_id),
        OnlyProductCommandKind.CREATE_BACKTEST_RUN,
        command_fingerprint,
        OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.BACKTEST_RUN, run.run_id.value),
        run.queued_at,
    )


def _store(postgres_dsn: str) -> OnlyPostgresBacktestStore:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    return OnlyPostgresBacktestStore(postgres_dsn)


def test_real_postgres_attempt_lease_fencing_retry_cancellation_and_reconciliation(postgres_dsn: str) -> None:
    store = _store(postgres_dsn)
    presence_id = OnlyBacktestWorkerInstanceId("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    assert not store.has_fresh_worker()
    store.announce_worker(presence_id, "test-version")
    assert store.has_fresh_worker()
    store.heartbeat_worker(presence_id)
    store.mark_worker_draining(presence_id)
    assert not store.has_fresh_worker()
    store.announce_worker(presence_id, "test-version-restarted")
    assert store.has_fresh_worker()
    run = _queued()
    store.create_queued_with_receipt(run, _receipt(run))
    assert store.load(run.run_id) == run

    policy = OnlyBacktestExecutionPolicy(
        lease_duration=timedelta(minutes=1), heartbeat_interval=timedelta(seconds=10), max_attempts=2
    )
    first = store.claim_next(OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), policy)
    assert first is not None
    assert first.run.state is OnlyBacktestRunState.RUNNING
    assert store.claim_next(OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), policy) is None

    with psycopg.connect(postgres_dsn) as connection:
        server_now = connection.execute("SELECT clock_timestamp()").fetchone()
        assert server_now is not None
        assert first.attempt.claimed_at <= server_now[0] <= first.attempt.lease_expires_at

    heartbeated = store.heartbeat(first, policy.lease_duration)
    assert heartbeated.last_heartbeat_at >= first.attempt.last_heartbeat_at
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE backtest_run_attempt SET claimed_at = clock_timestamp() - interval '2 minutes', "
            "last_heartbeat_at = clock_timestamp() - interval '2 minutes', "
            "lease_expires_at = clock_timestamp() - interval '1 minute' "
            "WHERE attempt_id = %s",
            (first.attempt.attempt_id.value,),
        )
    expired = store.expire_next(policy)
    assert expired is not None and expired.attempt_id == first.attempt.attempt_id

    replacement = store.claim_next(OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), policy)
    assert replacement is not None
    assert replacement.attempt.attempt_number == 2
    assert replacement.attempt.fencing_token > first.attempt.fencing_token
    with pytest.raises(OnlyBacktestStateConflictError, match="FENCED"):
        store.complete(
            first,
            evidence_fingerprint="4" * 64,
            result_fingerprint="5" * 64,
            determinism_fingerprint="6" * 64,
        )

    cancel_id = OnlyProductCommandId("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
    cancelled, receipt = store.request_cancellation_with_receipt(
        run.run_id, cancel_id, "8" * 64, NOW + timedelta(seconds=1)
    )
    assert cancelled.state is OnlyBacktestRunState.CANCEL_REQUESTED
    assert receipt.outcome_ref.outcome_id == run.run_id.value
    assert store.cancel(replacement).state is OnlyBacktestRunState.CANCELLED

    second_run = _queued("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    store.create_queued_with_receipt(
        second_run,
        _receipt(second_run, "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
    )
    second_claim = store.claim_next(OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), policy)
    assert second_claim is not None
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "UPDATE backtest_run_attempt SET state = 'EXPIRED', finished_at = clock_timestamp(), "
            "failure_code = 'LEASE_EXPIRED', failure_detail = 'fault injection' WHERE attempt_id = %s",
            (second_claim.attempt.attempt_id.value,),
        )
    candidate = store.load_reconciliation_candidate()
    assert candidate is not None and candidate.run_id == second_run.run_id
    reconciled = store.reconcile_complete(
        candidate,
        evidence_fingerprint="4" * 64,
        result_fingerprint="5" * 64,
        determinism_fingerprint="6" * 64,
    )
    assert reconciled.state is OnlyBacktestRunState.COMPLETED

    retry_run = _queued("12121212-1212-4212-8212-121212121212")
    store.create_queued_with_receipt(
        retry_run,
        _receipt(retry_run, "13131313-1313-4313-8313-131313131313"),
    )
    retry_claim = store.claim_next(OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), policy)
    assert retry_claim is not None
    retained = store.fail(
        retry_claim,
        OnlyBacktestRunFailure(
            OnlyBacktestRunFailurePhase.OPERATIONAL,
            "BACKTEST_STORE_UNAVAILABLE",
            "temporary database failure",
        ),
        policy,
    )
    assert retained.state is OnlyBacktestRunState.RUNNING
    retry_replacement = store.claim_next(OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), policy)
    assert retry_replacement is not None and retry_replacement.attempt.attempt_number == 2


def test_real_postgres_concurrent_command_id_has_one_exact_binding(postgres_dsn: str) -> None:
    store = _store(postgres_dsn)
    command_id = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    first = _queued()
    second = _queued("11111111-1111-4111-8111-111111111111")

    def create(run: OnlyBacktestRun) -> object:
        return store.create_queued_with_receipt(run, _receipt(run, command_id))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(create, first), pool.submit(create, second))
        outcomes: list[object] = []
        errors: list[BaseException] = []
        for future in futures:
            try:
                outcomes.append(future.result())
            except BaseException as exc:  # captured for exact concurrent outcome assertion
                errors.append(exc)

    assert len(outcomes) == 2
    assert not errors
    assert outcomes[0] == outcomes[1]
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM product_command_receipt WHERE command_id = %s", (command_id,)
        ).fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM backtest_run").fetchone() == (1,)

    with pytest.raises(OnlyBacktestError) as conflict:
        store.create_queued_with_receipt(second, _receipt(second, command_id, "8" * 64))
    assert conflict.value.code == "PRODUCT_COMMAND_CONFLICT"
