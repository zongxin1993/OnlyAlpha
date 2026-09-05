"""Explicit-SQL PostgreSQL Backtest Run and Product receipt authority."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import cast

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
)
from onlyalpha.backtest.errors import (
    OnlyBacktestError,
    OnlyBacktestErrorPhase,
    OnlyBacktestIntegrityError,
    OnlyBacktestNotFoundError,
    OnlyBacktestStateConflictError,
    OnlyBacktestStoreUnavailableError,
)
from onlyalpha.backtest.execution import (
    OnlyBacktestAttempt,
    OnlyBacktestAttemptId,
    OnlyBacktestAttemptState,
    OnlyBacktestExecutionClaim,
    OnlyBacktestExecutionPolicy,
    OnlyBacktestWorkerInstanceId,
)
from onlyalpha.backtest.model import (
    OnlyBacktestAdmissionResolution,
    OnlyBacktestRun,
    OnlyBacktestRunFailure,
    OnlyBacktestRunFailurePhase,
    OnlyBacktestRunId,
    OnlyBacktestRunState,
    OnlyBacktestSpecification,
)
from onlyalpha.canonical import only_canonical_json

from .config import OnlyPostgresOperationalConnectionOptions

_COLUMNS = (
    "run_id",
    "revision",
    "state",
    "specification_schema_version",
    "specification_fingerprint",
    "specification_payload",
    "admission_resolution_fingerprint",
    "admission_resolution_schema_version",
    "admission_resolution_payload",
    "queued_at",
    "started_at",
    "cancel_requested_at",
    "finished_at",
    "evidence_fingerprint",
    "result_fingerprint",
    "determinism_fingerprint",
    "failure_phase",
    "failure_code",
    "failure_detail",
)


class OnlyPostgresBacktestStore:
    def __init__(self, dsn: str, options: OnlyPostgresOperationalConnectionOptions | None = None) -> None:
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)

    def announce_worker(self, worker_id: OnlyBacktestWorkerInstanceId, service_version: str) -> None:
        if not service_version.strip():
            raise ValueError("BACKTEST_WORKER_SERVICE_VERSION_INVALID")
        try:
            with psycopg.connect(self._dsn) as connection:
                connection.execute(
                    """INSERT INTO backtest_worker_presence
                    (worker_instance_id, service_version, status, started_at, last_seen_at)
                    VALUES (%s, %s, 'ACTIVE', clock_timestamp(), clock_timestamp())
                    ON CONFLICT (worker_instance_id) DO UPDATE
                    SET service_version = EXCLUDED.service_version, status = 'ACTIVE',
                        started_at = clock_timestamp(), last_seen_at = clock_timestamp()""",
                    (worker_id.value, service_version),
                )
        except psycopg.Error as exc:
            raise OnlyBacktestStoreUnavailableError("Backtest Worker presence announce failed") from exc

    def heartbeat_worker(self, worker_id: OnlyBacktestWorkerInstanceId) -> None:
        self._update_worker_presence(worker_id, "ACTIVE")

    def mark_worker_draining(self, worker_id: OnlyBacktestWorkerInstanceId) -> None:
        self._update_worker_presence(worker_id, "DRAINING")

    def has_fresh_worker(self, freshness: timedelta = timedelta(seconds=45)) -> bool:
        if freshness <= timedelta(0):
            raise ValueError("BACKTEST_WORKER_FRESHNESS_INVALID")
        try:
            with psycopg.connect(self._dsn) as connection:
                row = connection.execute(
                    """SELECT EXISTS (
                        SELECT 1 FROM backtest_worker_presence
                        WHERE status = 'ACTIVE'
                          AND last_seen_at >= clock_timestamp() - make_interval(secs => %s)
                    )""",
                    (freshness.total_seconds(),),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyBacktestStoreUnavailableError("Backtest Worker presence query failed") from exc
        if row is None or not isinstance(row[0], bool):
            raise OnlyBacktestIntegrityError("BACKTEST_WORKER_PRESENCE_CORRUPT", "query")
        return row[0]

    def _update_worker_presence(self, worker_id: OnlyBacktestWorkerInstanceId, status: str) -> None:
        try:
            with psycopg.connect(self._dsn) as connection:
                cursor = connection.execute(
                    """UPDATE backtest_worker_presence
                    SET status = %s, last_seen_at = clock_timestamp()
                    WHERE worker_instance_id = %s""",
                    (status, worker_id.value),
                )
                if cursor.rowcount != 1:
                    raise OnlyBacktestIntegrityError("BACKTEST_WORKER_PRESENCE_NOT_FOUND", worker_id.value)
        except OnlyBacktestIntegrityError:
            raise
        except psycopg.Error as exc:
            raise OnlyBacktestStoreUnavailableError("Backtest Worker presence update failed") from exc

    def find_product_command_receipt(self, command_id: OnlyProductCommandId) -> OnlyProductCommandReceipt | None:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT * FROM product_command_receipt WHERE command_id = %s",
                    (command_id.value,),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyBacktestStoreUnavailableError("Product Command Receipt load failed") from exc
        return None if row is None else _decode_receipt(cast(Mapping[str, object], row))

    def create_queued_with_receipt(
        self,
        run: OnlyBacktestRun,
        receipt: OnlyProductCommandReceipt,
    ) -> OnlyProductCommandReceipt:
        if run.state is not OnlyBacktestRunState.QUEUED or run.revision != 0:
            raise OnlyBacktestStateConflictError("create requires revision-zero QUEUED Backtest")
        if (
            receipt.command_kind is not OnlyProductCommandKind.CREATE_BACKTEST_RUN
            or receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.BACKTEST_RUN
            or receipt.outcome_ref.outcome_id != run.run_id.value
            or receipt.accepted_at != run.queued_at
        ):
            raise OnlyBacktestIntegrityError("BACKTEST_RECEIPT_CORRUPT", "Create receipt does not bind Run")
        query = sql.SQL("INSERT INTO backtest_run ({}) VALUES ({})").format(
            sql.SQL(", ").join(map(sql.Identifier, _COLUMNS)),
            sql.SQL(", ").join(sql.Placeholder() for _ in _COLUMNS),
        )
        try:
            with psycopg.connect(self._dsn) as connection:
                connection.execute(query, _values(run))
                _insert_receipt(connection, receipt)
            return receipt
        except psycopg.errors.UniqueViolation as exc:
            existing = self.find_product_command_receipt(receipt.command_id)
            if existing is None:
                raise OnlyBacktestIntegrityError(
                    "BACKTEST_IDENTITY_CONFLICT", "Backtest Run identity already exists"
                ) from exc
            _assert_receipt_binding(
                existing,
                receipt.command_fingerprint,
                OnlyProductCommandKind.CREATE_BACKTEST_RUN,
                OnlyProductCommandOutcomeKind.BACKTEST_RUN,
                None,
            )
            return existing
        except psycopg.Error as exc:
            raise OnlyBacktestStoreUnavailableError("Backtest create transaction failed") from exc

    def load(self, run_id: OnlyBacktestRunId) -> OnlyBacktestRun:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute("SELECT * FROM backtest_run WHERE run_id = %s", (run_id.value,)).fetchone()
        except psycopg.Error as exc:
            raise OnlyBacktestStoreUnavailableError("Backtest Run load failed") from exc
        if row is None:
            raise OnlyBacktestNotFoundError(run_id.value)
        return _decode_run(cast(Mapping[str, object], row))

    def request_cancellation_with_receipt(
        self,
        run_id: OnlyBacktestRunId,
        command_id: OnlyProductCommandId,
        command_fingerprint: str,
        at: datetime,
    ) -> tuple[OnlyBacktestRun, OnlyProductCommandReceipt]:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                existing_row = connection.execute(
                    "SELECT * FROM product_command_receipt WHERE command_id = %s FOR UPDATE",
                    (command_id.value,),
                ).fetchone()
                if existing_row is not None:
                    receipt = _decode_receipt(cast(Mapping[str, object], existing_row))
                    _assert_receipt_binding(
                        receipt,
                        command_fingerprint,
                        OnlyProductCommandKind.CANCEL_BACKTEST_RUN,
                        OnlyProductCommandOutcomeKind.BACKTEST_RUN,
                        run_id.value,
                    )
                    return self.load(run_id), receipt
                row = connection.execute(
                    "SELECT * FROM backtest_run WHERE run_id = %s FOR UPDATE",
                    (run_id.value,),
                ).fetchone()
                if row is None:
                    raise OnlyBacktestNotFoundError(run_id.value)
                current = _decode_run(cast(Mapping[str, object], row))
                if current.state is OnlyBacktestRunState.QUEUED:
                    updated = current.transition(OnlyBacktestRunState.CANCELLED, at=at)
                elif current.state is OnlyBacktestRunState.RUNNING:
                    updated = current.transition(OnlyBacktestRunState.CANCEL_REQUESTED, at=at)
                elif current.state in {OnlyBacktestRunState.CANCEL_REQUESTED, OnlyBacktestRunState.CANCELLED}:
                    updated = current
                else:
                    raise OnlyBacktestStateConflictError(f"Backtest is terminal: {current.state.value}")
                if updated != current:
                    _update_run(connection, current, updated)
                receipt = OnlyProductCommandReceipt(
                    command_id=command_id,
                    command_kind=OnlyProductCommandKind.CANCEL_BACKTEST_RUN,
                    command_fingerprint=command_fingerprint,
                    outcome_ref=OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.BACKTEST_RUN, run_id.value),
                    accepted_at=at,
                )
                _insert_receipt(connection, receipt)
            return updated, receipt
        except (OnlyBacktestNotFoundError, OnlyBacktestStateConflictError):
            raise
        except psycopg.errors.UniqueViolation as exc:
            existing = self.find_product_command_receipt(command_id)
            if existing is None:
                raise OnlyBacktestIntegrityError("BACKTEST_IDENTITY_CONFLICT", run_id.value) from exc
            _assert_receipt_binding(
                existing,
                command_fingerprint,
                OnlyProductCommandKind.CANCEL_BACKTEST_RUN,
                OnlyProductCommandOutcomeKind.BACKTEST_RUN,
                run_id.value,
            )
            return self.load(run_id), existing
        except psycopg.Error as exc:
            raise OnlyBacktestStoreUnavailableError("Backtest cancellation transaction failed") from exc

    def claim_next(
        self,
        worker_instance_id: OnlyBacktestWorkerInstanceId,
        attempt_id: OnlyBacktestAttemptId,
        policy: OnlyBacktestExecutionPolicy,
        eligible_run_ids: tuple[str, ...] | None = None,
    ) -> OnlyBacktestExecutionClaim | None:
        if eligible_run_ids == ():
            return None
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                work_predicate = "TRUE" if eligible_run_ids is None else "run.run_id = ANY(%s)"
                parameters: tuple[object, ...] = (
                    (policy.max_attempts,)
                    if eligible_run_ids is None
                    else (list(eligible_run_ids), policy.max_attempts)
                )
                row = connection.execute(
                    f"""SELECT run.* FROM backtest_run AS run
                    WHERE run.state IN ('QUEUED', 'RUNNING')
                      AND {work_predicate}
                      AND NOT EXISTS (
                        SELECT 1 FROM backtest_run_attempt AS active
                        WHERE active.run_id = run.run_id AND active.state = 'ACTIVE'
                      )
                      AND (
                        SELECT count(*) FROM backtest_run_attempt AS history
                        WHERE history.run_id = run.run_id
                      ) < %s
                    ORDER BY run.queued_at, run.run_id
                    FOR UPDATE OF run SKIP LOCKED
                    LIMIT 1""",
                    parameters,
                ).fetchone()
                if row is None:
                    return None
                run = _decode_run(cast(Mapping[str, object], row))
                sequence = connection.execute(
                    """SELECT COALESCE(MAX(attempt_number), 0) + 1 AS attempt_number,
                              COALESCE(MAX(fencing_token), 0) + 1 AS fencing_token,
                              clock_timestamp() AS server_now
                       FROM backtest_run_attempt WHERE run_id = %s""",
                    (run.run_id.value,),
                ).fetchone()
                if sequence is None:
                    raise OnlyBacktestIntegrityError("BACKTEST_ATTEMPT_SEQUENCE_CORRUPT", run.run_id.value)
                claimed_at = cast(datetime, sequence["server_now"])
                if run.state is OnlyBacktestRunState.QUEUED:
                    running = run.transition(OnlyBacktestRunState.RUNNING, at=claimed_at)
                    _update_run(connection, run, running)
                    run = running
                inserted = connection.execute(
                    """INSERT INTO backtest_run_attempt
                    (attempt_id, run_id, attempt_number, state, worker_instance_id, fencing_token,
                     claimed_at, last_heartbeat_at, lease_expires_at)
                    VALUES (%s, %s, %s, 'ACTIVE', %s, %s, %s, %s, %s)
                    RETURNING *""",
                    (
                        attempt_id.value,
                        run.run_id.value,
                        int(sequence["attempt_number"]),
                        worker_instance_id.value,
                        int(sequence["fencing_token"]),
                        claimed_at,
                        claimed_at,
                        claimed_at + policy.lease_duration,
                    ),
                ).fetchone()
                if inserted is None:
                    raise OnlyBacktestIntegrityError("BACKTEST_ATTEMPT_CREATE_FAILED", run.run_id.value)
                return OnlyBacktestExecutionClaim(run, _decode_attempt(cast(Mapping[str, object], inserted)))
        except (OnlyBacktestIntegrityError, OnlyBacktestStateConflictError):
            raise
        except psycopg.errors.UniqueViolation as exc:
            raise OnlyBacktestStateConflictError("Backtest Attempt ownership conflict") from exc
        except psycopg.Error as exc:
            raise OnlyBacktestStoreUnavailableError("Backtest claim transaction failed") from exc

    def heartbeat(self, claim: OnlyBacktestExecutionClaim, lease_duration: timedelta) -> OnlyBacktestAttempt:
        if lease_duration <= timedelta(0):
            raise ValueError("BACKTEST_LEASE_DURATION_INVALID")
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    """UPDATE backtest_run_attempt
                    SET last_heartbeat_at = clock_timestamp(),
                        lease_expires_at = clock_timestamp() + %s
                    WHERE attempt_id = %s AND run_id = %s AND attempt_number = %s
                      AND worker_instance_id = %s AND fencing_token = %s
                      AND state = 'ACTIVE' AND lease_expires_at > clock_timestamp()
                    RETURNING *""",
                    (
                        lease_duration,
                        claim.attempt.attempt_id.value,
                        claim.run.run_id.value,
                        claim.attempt.attempt_number,
                        claim.attempt.worker_instance_id.value,
                        claim.attempt.fencing_token,
                    ),
                ).fetchone()
                if row is None:
                    raise OnlyBacktestStateConflictError("BACKTEST_ATTEMPT_FENCED")
                return _decode_attempt(cast(Mapping[str, object], row))
        except OnlyBacktestStateConflictError:
            raise
        except psycopg.Error as exc:
            raise OnlyBacktestStoreUnavailableError("Backtest heartbeat failed") from exc

    def load_attempt(self, attempt_id: OnlyBacktestAttemptId) -> OnlyBacktestAttempt:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT * FROM backtest_run_attempt WHERE attempt_id = %s",
                    (attempt_id.value,),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyBacktestStoreUnavailableError("Backtest Attempt load failed") from exc
        if row is None:
            raise OnlyBacktestNotFoundError(attempt_id.value)
        return _decode_attempt(cast(Mapping[str, object], row))

    def expire_next(
        self,
        policy: OnlyBacktestExecutionPolicy,
        eligible_run_ids: tuple[str, ...] | None = None,
    ) -> OnlyBacktestAttempt | None:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                generation_predicate = "TRUE" if eligible_run_ids is None else "run_id = ANY(%s::uuid[])"
                row = connection.execute(
                    f"""SELECT * FROM backtest_run_attempt
                    WHERE state = 'ACTIVE' AND lease_expires_at <= clock_timestamp()
                      AND {generation_predicate}
                    ORDER BY lease_expires_at, attempt_id
                    FOR UPDATE SKIP LOCKED LIMIT 1""",
                    () if eligible_run_ids is None else (list(eligible_run_ids),),
                ).fetchone()
                if row is None:
                    return None
                attempt = _decode_attempt(cast(Mapping[str, object], row))
                server_row = connection.execute("SELECT clock_timestamp() AS server_now").fetchone()
                if server_row is None:
                    raise OnlyBacktestIntegrityError("POSTGRES_SERVER_CLOCK_UNAVAILABLE", attempt.run_id.value)
                finished_at = cast(datetime, server_row["server_now"])
                expired_row = connection.execute(
                    """UPDATE backtest_run_attempt
                    SET state = 'EXPIRED', finished_at = %s,
                        failure_code = 'LEASE_EXPIRED', failure_detail = 'Backtest Attempt lease expired'
                    WHERE attempt_id = %s AND state = 'ACTIVE'
                    RETURNING *""",
                    (finished_at, attempt.attempt_id.value),
                ).fetchone()
                if expired_row is None:
                    raise OnlyBacktestStateConflictError("BACKTEST_ATTEMPT_FENCED")
                run_row = connection.execute(
                    "SELECT * FROM backtest_run WHERE run_id = %s FOR UPDATE",
                    (attempt.run_id.value,),
                ).fetchone()
                if run_row is None:
                    raise OnlyBacktestIntegrityError("BACKTEST_ATTEMPT_RUN_MISSING", attempt.run_id.value)
                run = _decode_run(cast(Mapping[str, object], run_row))
                if attempt.attempt_number >= policy.max_attempts and run.state is OnlyBacktestRunState.RUNNING:
                    failure = OnlyBacktestRunFailure(
                        OnlyBacktestRunFailurePhase.OPERATIONAL,
                        "ATTEMPT_LIMIT_EXHAUSTED",
                        "Backtest retry budget was exhausted",
                    )
                    _update_run(
                        connection,
                        run,
                        run.transition(OnlyBacktestRunState.FAILED, at=finished_at, failure=failure),
                    )
                elif run.state not in {OnlyBacktestRunState.RUNNING, OnlyBacktestRunState.CANCEL_REQUESTED}:
                    raise OnlyBacktestIntegrityError("BACKTEST_ACTIVE_ATTEMPT_RUN_STATE_INVALID", run.state.value)
                return _decode_attempt(cast(Mapping[str, object], expired_row))
        except (OnlyBacktestIntegrityError, OnlyBacktestStateConflictError):
            raise
        except psycopg.Error as exc:
            raise OnlyBacktestStoreUnavailableError("Backtest expiry transaction failed") from exc

    def load_reconciliation_candidate(
        self,
        eligible_run_ids: tuple[str, ...] | None = None,
    ) -> OnlyBacktestRun | None:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                generation_predicate = "TRUE" if eligible_run_ids is None else "run.run_id = ANY(%s::uuid[])"
                row = connection.execute(
                    f"""SELECT run.* FROM backtest_run AS run
                    WHERE run.state IN ('RUNNING', 'CANCEL_REQUESTED')
                      AND {generation_predicate}
                      AND NOT EXISTS (
                        SELECT 1 FROM backtest_run_attempt AS attempt
                        WHERE attempt.run_id = run.run_id AND attempt.state = 'ACTIVE'
                      )
                    ORDER BY run.queued_at, run.run_id LIMIT 1""",
                    () if eligible_run_ids is None else (list(eligible_run_ids),),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyBacktestStoreUnavailableError("Backtest reconciliation query failed") from exc
        return None if row is None else _decode_run(cast(Mapping[str, object], row))

    def reconcile_complete(
        self,
        run: OnlyBacktestRun,
        *,
        evidence_fingerprint: str,
        result_fingerprint: str,
        determinism_fingerprint: str,
    ) -> OnlyBacktestRun:
        return self._reconcile(
            run,
            OnlyBacktestRunState.COMPLETED,
            evidence_fingerprint=evidence_fingerprint,
            result_fingerprint=result_fingerprint,
            determinism_fingerprint=determinism_fingerprint,
        )

    def reconcile_fail(self, run: OnlyBacktestRun, failure: OnlyBacktestRunFailure) -> OnlyBacktestRun:
        return self._reconcile(run, OnlyBacktestRunState.FAILED, failure=failure)

    def reconcile_cancel(self, run: OnlyBacktestRun) -> OnlyBacktestRun:
        if run.state is not OnlyBacktestRunState.CANCEL_REQUESTED:
            raise OnlyBacktestStateConflictError("Backtest reconciliation cancellation was not requested")
        return self._reconcile(run, OnlyBacktestRunState.CANCELLED)

    def _reconcile(
        self,
        expected: OnlyBacktestRun,
        target: OnlyBacktestRunState,
        *,
        evidence_fingerprint: str | None = None,
        result_fingerprint: str | None = None,
        determinism_fingerprint: str | None = None,
        failure: OnlyBacktestRunFailure | None = None,
    ) -> OnlyBacktestRun:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT * FROM backtest_run WHERE run_id = %s FOR UPDATE",
                    (expected.run_id.value,),
                ).fetchone()
                if row is None:
                    raise OnlyBacktestNotFoundError(expected.run_id.value)
                current = _decode_run(cast(Mapping[str, object], row))
                if (
                    current.revision != expected.revision
                    or current.state != expected.state
                    or current.state not in {OnlyBacktestRunState.RUNNING, OnlyBacktestRunState.CANCEL_REQUESTED}
                ):
                    raise OnlyBacktestStateConflictError("Backtest reconciliation CAS failed")
                active = connection.execute(
                    "SELECT 1 FROM backtest_run_attempt WHERE run_id = %s AND state = 'ACTIVE'",
                    (expected.run_id.value,),
                ).fetchone()
                if active is not None:
                    raise OnlyBacktestStateConflictError("Backtest reconciliation found ACTIVE ownership")
                server_row = connection.execute("SELECT clock_timestamp() AS server_now").fetchone()
                if server_row is None:
                    raise OnlyBacktestIntegrityError("POSTGRES_SERVER_CLOCK_UNAVAILABLE", expected.run_id.value)
                at = cast(datetime, server_row["server_now"])
                updated = current.transition(
                    target,
                    at=at,
                    evidence_fingerprint=evidence_fingerprint,
                    result_fingerprint=result_fingerprint,
                    determinism_fingerprint=determinism_fingerprint,
                    failure=failure,
                )
                _update_run(connection, current, updated)
                return updated
        except (OnlyBacktestIntegrityError, OnlyBacktestNotFoundError, OnlyBacktestStateConflictError):
            raise
        except psycopg.Error as exc:
            raise OnlyBacktestStoreUnavailableError("Backtest reconciliation transaction failed") from exc

    def complete(
        self,
        claim: OnlyBacktestExecutionClaim,
        *,
        evidence_fingerprint: str,
        result_fingerprint: str,
        determinism_fingerprint: str,
    ) -> OnlyBacktestRun:
        return self._terminalize(
            claim,
            attempt_state=OnlyBacktestAttemptState.SUCCEEDED,
            target=OnlyBacktestRunState.COMPLETED,
            evidence_fingerprint=evidence_fingerprint,
            result_fingerprint=result_fingerprint,
            determinism_fingerprint=determinism_fingerprint,
        )

    def fail(
        self,
        claim: OnlyBacktestExecutionClaim,
        failure: OnlyBacktestRunFailure,
        policy: OnlyBacktestExecutionPolicy,
    ) -> OnlyBacktestRun:
        retry = failure.code in policy.retryable_failure_codes and claim.attempt.attempt_number < policy.max_attempts
        return self._terminalize(
            claim,
            attempt_state=OnlyBacktestAttemptState.FAILED,
            target=None if retry else OnlyBacktestRunState.FAILED,
            failure=failure,
        )

    def cancel(self, claim: OnlyBacktestExecutionClaim) -> OnlyBacktestRun:
        return self._terminalize(
            claim,
            attempt_state=OnlyBacktestAttemptState.CANCELLED,
            target=OnlyBacktestRunState.CANCELLED,
        )

    def _terminalize(
        self,
        claim: OnlyBacktestExecutionClaim,
        *,
        attempt_state: OnlyBacktestAttemptState,
        target: OnlyBacktestRunState | None,
        evidence_fingerprint: str | None = None,
        result_fingerprint: str | None = None,
        determinism_fingerprint: str | None = None,
        failure: OnlyBacktestRunFailure | None = None,
    ) -> OnlyBacktestRun:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                attempt_row = _lock_owned_attempt(connection, claim)
                at = cast(datetime, attempt_row["server_now"])
                run_row = connection.execute(
                    "SELECT * FROM backtest_run WHERE run_id = %s FOR UPDATE",
                    (claim.run.run_id.value,),
                ).fetchone()
                if run_row is None:
                    raise OnlyBacktestIntegrityError("BACKTEST_ATTEMPT_RUN_MISSING", claim.run.run_id.value)
                run = _decode_run(cast(Mapping[str, object], run_row))
                if target is OnlyBacktestRunState.CANCELLED and run.state is not OnlyBacktestRunState.CANCEL_REQUESTED:
                    raise OnlyBacktestStateConflictError("Backtest cancellation was not requested")
                updated = run
                if target is not None:
                    updated = run.transition(
                        target,
                        at=at,
                        evidence_fingerprint=evidence_fingerprint,
                        result_fingerprint=result_fingerprint,
                        determinism_fingerprint=determinism_fingerprint,
                        failure=failure,
                    )
                    _update_run(connection, run, updated)
                connection.execute(
                    """UPDATE backtest_run_attempt
                    SET state = %s, finished_at = %s, failure_code = %s, failure_detail = %s
                    WHERE attempt_id = %s AND state = 'ACTIVE'""",
                    (
                        attempt_state.value,
                        at,
                        None if failure is None else failure.code,
                        None if failure is None else failure.detail,
                        claim.attempt.attempt_id.value,
                    ),
                )
                return updated
        except (OnlyBacktestIntegrityError, OnlyBacktestStateConflictError):
            raise
        except psycopg.Error as exc:
            raise OnlyBacktestStoreUnavailableError("Backtest terminalization failed") from exc


def _lock_owned_attempt(connection, claim: OnlyBacktestExecutionClaim) -> Mapping[str, object]:  # type: ignore[no-untyped-def]
    row = connection.execute(
        """SELECT attempt.*, clock_timestamp() AS server_now
        FROM backtest_run_attempt AS attempt
        WHERE attempt.attempt_id = %s AND attempt.run_id = %s AND attempt.attempt_number = %s
          AND attempt.worker_instance_id = %s AND attempt.fencing_token = %s
          AND attempt.state = 'ACTIVE' AND attempt.lease_expires_at > clock_timestamp()
        FOR UPDATE OF attempt""",
        (
            claim.attempt.attempt_id.value,
            claim.run.run_id.value,
            claim.attempt.attempt_number,
            claim.attempt.worker_instance_id.value,
            claim.attempt.fencing_token,
        ),
    ).fetchone()
    if row is None:
        raise OnlyBacktestStateConflictError("BACKTEST_ATTEMPT_FENCED")
    return cast(Mapping[str, object], row)


def _insert_receipt(connection, receipt: OnlyProductCommandReceipt) -> None:  # type: ignore[no-untyped-def]
    connection.execute(
        """INSERT INTO product_command_receipt
        (command_id, command_kind, command_fingerprint, outcome_kind, outcome_id, accepted_at, schema_version)
        VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (
            receipt.command_id.value,
            receipt.command_kind.value,
            receipt.command_fingerprint,
            receipt.outcome_ref.kind.value,
            receipt.outcome_ref.outcome_id,
            receipt.accepted_at,
            receipt.schema_version,
        ),
    )


def _assert_receipt_binding(
    receipt: OnlyProductCommandReceipt,
    command_fingerprint: str,
    command_kind: OnlyProductCommandKind,
    outcome_kind: OnlyProductCommandOutcomeKind,
    outcome_id: str | None,
) -> None:
    if (
        receipt.command_fingerprint != command_fingerprint
        or receipt.command_kind is not command_kind
        or receipt.outcome_ref.kind is not outcome_kind
        or (outcome_id is not None and receipt.outcome_ref.outcome_id != outcome_id)
    ):
        raise OnlyBacktestError(
            OnlyBacktestErrorPhase.COMMAND,
            "PRODUCT_COMMAND_CONFLICT",
            "Product Command ID is already bound to another intent",
        )


def _update_run(connection, previous: OnlyBacktestRun, updated: OnlyBacktestRun) -> None:  # type: ignore[no-untyped-def]
    assignments = sql.SQL(", ").join(
        sql.SQL("{} = {}").format(sql.Identifier(name), sql.Placeholder()) for name in _COLUMNS[1:]
    )
    query = sql.SQL("UPDATE backtest_run SET {} WHERE run_id = %s AND revision = %s AND state = %s").format(assignments)
    values = _values(updated)[1:] + (previous.run_id.value, previous.revision, previous.state.value)
    cursor = connection.execute(query, values)
    if cursor.rowcount != 1:
        raise OnlyBacktestStateConflictError("Backtest Run CAS failed")


def _values(run: OnlyBacktestRun) -> tuple[object, ...]:
    return (
        run.run_id.value,
        run.revision,
        run.state.value,
        run.specification.schema_version,
        run.specification_fingerprint,
        run.canonical_specification_payload,
        run.admission_resolution_fingerprint,
        run.admission_resolution.schema_version,
        run.canonical_admission_resolution_payload,
        run.queued_at,
        run.started_at,
        run.cancel_requested_at,
        run.finished_at,
        run.evidence_fingerprint,
        run.result_fingerprint,
        run.determinism_fingerprint,
        None if run.failure is None else run.failure.phase.value,
        None if run.failure is None else run.failure.code,
        None if run.failure is None else run.failure.detail,
    )


def _decode_run(row: Mapping[str, object]) -> OnlyBacktestRun:
    try:
        payload = row["specification_payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, Mapping):
            raise ValueError("Backtest Specification payload must be an object")
        specification = OnlyBacktestSpecification.from_dict(payload)
        if only_canonical_json(specification.to_dict()) != only_canonical_json(payload):
            raise ValueError("Backtest Specification payload is not canonical")
        if row["specification_fingerprint"] != specification.specification_fingerprint:
            raise ValueError("Backtest Specification fingerprint differs")
        resolution_payload = row["admission_resolution_payload"]
        if isinstance(resolution_payload, str):
            resolution_payload = json.loads(resolution_payload)
        if not isinstance(resolution_payload, Mapping):
            raise ValueError("Backtest Admission Resolution payload must be an object")
        resolution = OnlyBacktestAdmissionResolution.from_dict(resolution_payload)
        if only_canonical_json(resolution.to_dict()) != only_canonical_json(resolution_payload):
            raise ValueError("Backtest Admission Resolution payload is not canonical")
        if row["admission_resolution_schema_version"] != resolution.schema_version:
            raise ValueError("Backtest Admission Resolution schema version differs")
        if row["admission_resolution_fingerprint"] != resolution.admission_resolution_fingerprint:
            raise ValueError("Backtest Admission Resolution fingerprint differs")
        failure = None
        if row["failure_phase"] is not None:
            failure = OnlyBacktestRunFailure(
                OnlyBacktestRunFailurePhase(str(row["failure_phase"])),
                str(row["failure_code"]),
                str(row["failure_detail"]),
            )
        return OnlyBacktestRun(
            run_id=OnlyBacktestRunId(str(row["run_id"])),
            revision=int(str(row["revision"])),
            state=OnlyBacktestRunState(str(row["state"])),
            specification=specification,
            canonical_specification_payload=only_canonical_json(specification.to_dict()),
            admission_resolution=resolution,
            canonical_admission_resolution_payload=only_canonical_json(resolution.to_dict()),
            queued_at=cast(datetime, row["queued_at"]),
            started_at=cast(datetime | None, row["started_at"]),
            cancel_requested_at=cast(datetime | None, row["cancel_requested_at"]),
            finished_at=cast(datetime | None, row["finished_at"]),
            evidence_fingerprint=cast(str | None, row["evidence_fingerprint"]),
            result_fingerprint=cast(str | None, row["result_fingerprint"]),
            determinism_fingerprint=cast(str | None, row["determinism_fingerprint"]),
            failure=failure,
        )
    except Exception as exc:
        if isinstance(exc, OnlyBacktestIntegrityError):
            raise
        raise OnlyBacktestIntegrityError("BACKTEST_RUN_CORRUPT", str(row.get("run_id", "unknown"))) from exc


def _decode_receipt(row: Mapping[str, object]) -> OnlyProductCommandReceipt:
    try:
        return OnlyProductCommandReceipt(
            command_id=OnlyProductCommandId(str(row["command_id"])),
            command_kind=OnlyProductCommandKind(str(row["command_kind"])),
            command_fingerprint=str(row["command_fingerprint"]),
            outcome_ref=OnlyProductCommandOutcomeRef(
                OnlyProductCommandOutcomeKind(str(row["outcome_kind"])),
                str(row["outcome_id"]),
            ),
            accepted_at=cast(datetime, row["accepted_at"]),
            schema_version=int(str(row["schema_version"])),
        )
    except Exception as exc:
        raise OnlyBacktestIntegrityError("PRODUCT_COMMAND_RECEIPT_CORRUPT", str(row.get("command_id"))) from exc


def _decode_attempt(row: Mapping[str, object]) -> OnlyBacktestAttempt:
    try:
        return OnlyBacktestAttempt(
            attempt_id=OnlyBacktestAttemptId(str(row["attempt_id"])),
            run_id=OnlyBacktestRunId(str(row["run_id"])),
            attempt_number=int(str(row["attempt_number"])),
            state=OnlyBacktestAttemptState(str(row["state"])),
            worker_instance_id=OnlyBacktestWorkerInstanceId(str(row["worker_instance_id"])),
            fencing_token=int(str(row["fencing_token"])),
            claimed_at=cast(datetime, row["claimed_at"]),
            last_heartbeat_at=cast(datetime, row["last_heartbeat_at"]),
            lease_expires_at=cast(datetime, row["lease_expires_at"]),
            finished_at=cast(datetime | None, row["finished_at"]),
            failure_code=cast(str | None, row["failure_code"]),
            failure_detail=cast(str | None, row["failure_detail"]),
        )
    except Exception as exc:
        raise OnlyBacktestIntegrityError("BACKTEST_ATTEMPT_CORRUPT", str(row.get("attempt_id"))) from exc


__all__ = ["OnlyPostgresBacktestStore"]
