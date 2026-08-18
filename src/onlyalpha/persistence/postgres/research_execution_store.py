"""Explicit-SQL PostgreSQL adapter for Attempt, lease, fencing and recovery."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import cast

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from onlyalpha.research.execution.errors import (
    OnlyResearchExecutionOwnershipLostError,
    OnlyResearchExecutionStoreUnavailableError,
)
from onlyalpha.research.execution.model import (
    OnlyResearchExecutionClaim,
    OnlyResearchRunAttempt,
    OnlyResearchRunAttemptId,
    OnlyResearchRunAttemptState,
    OnlyResearchWorkerInstanceId,
)
from onlyalpha.research.execution.policy import OnlyResearchRetryDecision
from onlyalpha.research.run import (
    OnlyResearchRun,
    OnlyResearchRunFailure,
    OnlyResearchRunFailurePhase,
    OnlyResearchRunId,
    OnlyResearchRunState,
)
from onlyalpha.research.run.errors import OnlyResearchRunIntegrityError

from .research_run_store import _COLUMNS, OnlyPostgresResearchRunStore

_ATTEMPT_COLUMNS = (
    "attempt_id",
    "run_id",
    "attempt_number",
    "state",
    "worker_instance_id",
    "claimed_at",
    "last_heartbeat_at",
    "lease_expires_at",
    "finished_at",
    "failure_phase",
    "failure_code",
    "failure_detail",
)


class OnlyPostgresResearchExecutionStore:
    """PostgreSQL server time is the sole lease coordination clock."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def load_attempt(self, attempt_id: OnlyResearchRunAttemptId) -> OnlyResearchRunAttempt:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT * FROM research_run_attempt WHERE attempt_id = %s", (attempt_id.value,)
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyResearchExecutionStoreUnavailableError("Attempt load failed") from exc
        if row is None:
            raise OnlyResearchExecutionOwnershipLostError(f"Attempt not found: {attempt_id}")
        return _decode_attempt(cast(Mapping[str, object], row))

    def claim_next(
        self,
        *,
        worker_instance_id: OnlyResearchWorkerInstanceId,
        attempt_id: OnlyResearchRunAttemptId,
        lease_duration: timedelta,
        max_attempts: int,
        run_started_at: datetime,
    ) -> OnlyResearchExecutionClaim | None:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    """
                    SELECT r.* FROM research_run AS r
                    WHERE r.state IN ('QUEUED', 'RUNNING')
                      AND NOT EXISTS (
                          SELECT 1 FROM research_run_attempt AS active
                          WHERE active.run_id = r.run_id AND active.state = 'ACTIVE'
                      )
                      AND (SELECT COUNT(*) FROM research_run_attempt AS history
                           WHERE history.run_id = r.run_id) < %s
                    ORDER BY r.queued_at ASC, r.run_id ASC
                    FOR UPDATE OF r SKIP LOCKED LIMIT 1
                    """,
                    (max_attempts,),
                ).fetchone()
                if row is None:
                    return None
                run = OnlyPostgresResearchRunStore._decode(cast(Mapping[str, object], row))
                number_row = connection.execute(
                    "SELECT COALESCE(MAX(attempt_number), 0) + 1 AS next_attempt_number "
                    "FROM research_run_attempt WHERE run_id = %s",
                    (run.run_id.value,),
                ).fetchone()
                assert number_row is not None
                if run.state is OnlyResearchRunState.QUEUED:
                    running = run.transition(OnlyResearchRunState.RUNNING, at=run_started_at)
                    _update_run(connection, run, running)
                    run = running
                lease_row = connection.execute("SELECT clock_timestamp() AS lease_now").fetchone()
                assert lease_row is not None
                lease_now = cast(datetime, lease_row["lease_now"])
                attempt = OnlyResearchRunAttempt(
                    attempt_id,
                    run.run_id,
                    int(number_row["next_attempt_number"]),
                    OnlyResearchRunAttemptState.ACTIVE,
                    worker_instance_id,
                    lease_now,
                    lease_now,
                    lease_now + lease_duration,
                )
                connection.execute(
                    sql.SQL("INSERT INTO research_run_attempt ({}) VALUES ({})").format(
                        sql.SQL(", ").join(map(sql.Identifier, _ATTEMPT_COLUMNS)),
                        sql.SQL(", ").join(sql.Placeholder() for _ in _ATTEMPT_COLUMNS),
                    ),
                    _attempt_values(attempt),
                )
                return OnlyResearchExecutionClaim(attempt)
        except (OnlyResearchRunIntegrityError, ValueError):
            raise
        except psycopg.Error as exc:
            raise OnlyResearchExecutionStoreUnavailableError("Claim transaction failed") from exc

    def heartbeat(
        self,
        *,
        attempt_id: OnlyResearchRunAttemptId,
        worker_instance_id: OnlyResearchWorkerInstanceId,
        lease_duration: timedelta,
    ) -> OnlyResearchRunAttempt:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    """
                    UPDATE research_run_attempt
                    SET last_heartbeat_at = clock_timestamp(),
                        lease_expires_at = clock_timestamp() + %s
                    WHERE attempt_id = %s AND worker_instance_id = %s AND state = 'ACTIVE'
                      AND lease_expires_at > clock_timestamp()
                    RETURNING *
                    """,
                    (lease_duration, attempt_id.value, worker_instance_id.value),
                ).fetchone()
                if row is None:
                    raise OnlyResearchExecutionOwnershipLostError(f"Attempt ownership lost: {attempt_id}")
                return _decode_attempt(cast(Mapping[str, object], row))
        except OnlyResearchExecutionOwnershipLostError:
            raise
        except psycopg.Error as exc:
            raise OnlyResearchExecutionStoreUnavailableError("Heartbeat transaction failed") from exc

    def expire_next(self, *, max_attempts: int, run_finished_at: datetime) -> OnlyResearchRunAttempt | None:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                candidate = connection.execute(
                    """
                    SELECT attempt_id FROM research_run_attempt
                    WHERE state = 'ACTIVE' AND lease_expires_at <= clock_timestamp()
                    ORDER BY lease_expires_at ASC, run_id ASC, attempt_id ASC
                    FOR UPDATE SKIP LOCKED LIMIT 1
                    """
                ).fetchone()
                if candidate is None:
                    return None
                attempt_row = connection.execute(
                    "SELECT * FROM research_run_attempt WHERE attempt_id = %s FOR UPDATE",
                    (candidate["attempt_id"],),
                ).fetchone()
                assert attempt_row is not None
                attempt = _decode_attempt(cast(Mapping[str, object], attempt_row))
                still_expired = connection.execute(
                    "SELECT lease_expires_at <= clock_timestamp() AS expired "
                    "FROM research_run_attempt WHERE attempt_id = %s",
                    (attempt.attempt_id.value,),
                ).fetchone()
                if still_expired is None or not bool(still_expired["expired"]):
                    return None
                run_row = connection.execute(
                    "SELECT * FROM research_run WHERE run_id = %s FOR UPDATE", (attempt.run_id.value,)
                ).fetchone()
                assert run_row is not None
                run = OnlyPostgresResearchRunStore._decode(cast(Mapping[str, object], run_row))
                lease_failure = OnlyResearchRunFailure(
                    OnlyResearchRunFailurePhase.OPERATIONAL,
                    "LEASE_EXPIRED",
                    "Attempt lease expired before operational finalization",
                )
                finished_row = connection.execute("SELECT clock_timestamp() AS finished_at").fetchone()
                assert finished_row is not None
                expired = _terminal_attempt(
                    attempt,
                    OnlyResearchRunAttemptState.EXPIRED,
                    cast(datetime, finished_row["finished_at"]),
                    lease_failure,
                )
                _update_attempt(connection, expired)
                if run.state is OnlyResearchRunState.CANCEL_REQUESTED:
                    _update_run(connection, run, run.transition(OnlyResearchRunState.CANCELLED, at=run_finished_at))
                elif attempt.attempt_number >= max_attempts:
                    exhausted = OnlyResearchRunFailure(
                        OnlyResearchRunFailurePhase.OPERATIONAL,
                        "ATTEMPT_LIMIT_EXHAUSTED",
                        "Attempt budget exhausted after lease expiry",
                    )
                    _update_run(
                        connection,
                        run,
                        run.transition(OnlyResearchRunState.FAILED, at=run_finished_at, failure=exhausted),
                    )
                elif run.state is not OnlyResearchRunState.RUNNING:
                    raise OnlyResearchExecutionOwnershipLostError("Expired Attempt belongs to a non-active Run")
                return expired
        except OnlyResearchExecutionOwnershipLostError:
            raise
        except psycopg.Error as exc:
            raise OnlyResearchExecutionStoreUnavailableError("Lease expiry transaction failed") from exc

    def complete(
        self,
        *,
        claim: OnlyResearchExecutionClaim,
        run_finished_at: datetime,
        research_result_fingerprint: str,
        artifact_content_fingerprint: str,
    ) -> OnlyResearchRun:
        return self._finalize(
            claim,
            OnlyResearchRunAttemptState.SUCCEEDED,
            lambda run: run.transition(
                OnlyResearchRunState.COMPLETED,
                at=run_finished_at,
                research_result_fingerprint=research_result_fingerprint,
                artifact_content_fingerprint=artifact_content_fingerprint,
            ),
        )

    def fail(
        self,
        *,
        claim: OnlyResearchExecutionClaim,
        run_finished_at: datetime,
        failure: OnlyResearchRunFailure,
        retry_decision: OnlyResearchRetryDecision,
    ) -> OnlyResearchRun:
        def transition(run: OnlyResearchRun) -> OnlyResearchRun:
            if retry_decision is OnlyResearchRetryDecision.RETRY and run.state is OnlyResearchRunState.RUNNING:
                return run
            return run.transition(OnlyResearchRunState.FAILED, at=run_finished_at, failure=failure)

        return self._finalize(claim, OnlyResearchRunAttemptState.FAILED, transition, failure)

    def cancel(
        self,
        *,
        claim: OnlyResearchExecutionClaim,
        run_finished_at: datetime,
    ) -> OnlyResearchRun:
        def transition(run: OnlyResearchRun) -> OnlyResearchRun:
            if run.state is not OnlyResearchRunState.CANCEL_REQUESTED:
                raise OnlyResearchExecutionOwnershipLostError("Run has no authoritative cancellation request")
            return run.transition(OnlyResearchRunState.CANCELLED, at=run_finished_at)

        return self._finalize(claim, OnlyResearchRunAttemptState.CANCELLED, transition)

    def _finalize(
        self,
        claim: OnlyResearchExecutionClaim,
        attempt_state: OnlyResearchRunAttemptState,
        transition: Callable[[OnlyResearchRun], OnlyResearchRun],
        failure: OnlyResearchRunFailure | None = None,
    ) -> OnlyResearchRun:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                attempt_row = connection.execute(
                    """
                    SELECT * FROM research_run_attempt
                    WHERE attempt_id = %s AND worker_instance_id = %s AND state = 'ACTIVE'
                      AND lease_expires_at > clock_timestamp()
                    FOR UPDATE
                    """,
                    (claim.attempt.attempt_id.value, claim.attempt.worker_instance_id.value),
                ).fetchone()
                if attempt_row is None:
                    raise OnlyResearchExecutionOwnershipLostError(
                        f"Attempt cannot finalize after ownership loss: {claim.attempt.attempt_id}"
                    )
                current = _decode_attempt(cast(Mapping[str, object], attempt_row))
                if current.run_id != claim.attempt.run_id or current.attempt_number != claim.attempt.attempt_number:
                    raise OnlyResearchExecutionOwnershipLostError("Attempt fencing identity mismatch")
                run_row = connection.execute(
                    "SELECT * FROM research_run WHERE run_id = %s FOR UPDATE", (current.run_id.value,)
                ).fetchone()
                assert run_row is not None
                run = OnlyPostgresResearchRunStore._decode(cast(Mapping[str, object], run_row))
                finished_row = connection.execute("SELECT clock_timestamp() AS finished_at").fetchone()
                assert finished_row is not None
                terminal = _terminal_attempt(
                    current, attempt_state, cast(datetime, finished_row["finished_at"]), failure
                )
                next_run = transition(run)
                _update_attempt(connection, terminal)
                if next_run != run:
                    _update_run(connection, run, next_run)
                return next_run
        except OnlyResearchExecutionOwnershipLostError:
            raise
        except psycopg.Error as exc:
            raise OnlyResearchExecutionStoreUnavailableError("Attempt finalization transaction failed") from exc


def _terminal_attempt(
    attempt: OnlyResearchRunAttempt,
    state: OnlyResearchRunAttemptState,
    finished_at: datetime,
    failure: OnlyResearchRunFailure | None,
) -> OnlyResearchRunAttempt:
    return OnlyResearchRunAttempt(
        attempt.attempt_id,
        attempt.run_id,
        attempt.attempt_number,
        state,
        attempt.worker_instance_id,
        attempt.claimed_at,
        attempt.last_heartbeat_at,
        attempt.lease_expires_at,
        finished_at,
        failure,
    )


def _update_attempt(connection: psycopg.Connection[Mapping[str, object]], attempt: OnlyResearchRunAttempt) -> None:
    assignments = tuple(name for name in _ATTEMPT_COLUMNS if name != "attempt_id")
    values = _attempt_values(attempt)
    cursor = connection.execute(
        sql.SQL("UPDATE research_run_attempt SET {} WHERE attempt_id = %s AND state = 'ACTIVE'").format(
            sql.SQL(", ").join(
                sql.Composed([sql.Identifier(name), sql.SQL(" = "), sql.Placeholder()]) for name in assignments
            )
        ),
        tuple(values[_ATTEMPT_COLUMNS.index(name)] for name in assignments) + (attempt.attempt_id.value,),
    )
    if cursor.rowcount != 1:
        raise OnlyResearchExecutionOwnershipLostError("Attempt changed during fenced execution transaction")


def _update_run(
    connection: psycopg.Connection[Mapping[str, object]],
    previous: OnlyResearchRun,
    transitioned: OnlyResearchRun,
) -> None:
    if not transitioned.is_exact_successor_of(previous):
        raise OnlyResearchRunIntegrityError("Execution transaction requires an exact Run successor")
    assignments = tuple(name for name in _COLUMNS if name != "run_id")
    values = OnlyPostgresResearchRunStore._values(transitioned)
    cursor = connection.execute(
        sql.SQL("UPDATE research_run SET {} WHERE run_id = %s AND revision = %s AND state = %s").format(
            sql.SQL(", ").join(
                sql.Composed([sql.Identifier(name), sql.SQL(" = "), sql.Placeholder()]) for name in assignments
            )
        ),
        tuple(values[_COLUMNS.index(name)] for name in assignments)
        + (previous.run_id.value, previous.revision, previous.state.value),
    )
    if cursor.rowcount != 1:
        raise OnlyResearchExecutionOwnershipLostError("Run changed during fenced execution transaction")


def _attempt_values(attempt: OnlyResearchRunAttempt) -> tuple[object, ...]:
    failure = attempt.failure
    return (
        attempt.attempt_id.value,
        attempt.run_id.value,
        attempt.attempt_number,
        attempt.state.value,
        attempt.worker_instance_id.value,
        attempt.claimed_at,
        attempt.last_heartbeat_at,
        attempt.lease_expires_at,
        attempt.finished_at,
        None if failure is None else failure.phase.value,
        None if failure is None else failure.code,
        None if failure is None else failure.detail,
    )


def _decode_attempt(row: Mapping[str, object]) -> OnlyResearchRunAttempt:
    failure = (
        None
        if row["failure_phase"] is None
        else OnlyResearchRunFailure(
            OnlyResearchRunFailurePhase(str(row["failure_phase"])), str(row["failure_code"]), str(row["failure_detail"])
        )
    )
    return OnlyResearchRunAttempt(
        OnlyResearchRunAttemptId(str(row["attempt_id"])),
        OnlyResearchRunId(str(row["run_id"])),
        int(cast(int, row["attempt_number"])),
        OnlyResearchRunAttemptState(str(row["state"])),
        OnlyResearchWorkerInstanceId(str(row["worker_instance_id"])),
        cast(datetime, row["claimed_at"]),
        cast(datetime, row["last_heartbeat_at"]),
        cast(datetime, row["lease_expires_at"]),
        cast(datetime | None, row["finished_at"]),
        failure,
    )


__all__ = ["OnlyPostgresResearchExecutionStore"]
