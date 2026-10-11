"""Narrow Research Chart SQL connection, not Source/Host/scientific Authority."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import cast

import psycopg

from onlyalpha.application.chart_calculation import OnlyChartCalculationOperationV1
from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationCompilationV1
from onlyalpha.application.chart_calculation_run_admission import only_require_chart_calculation_new_admission
from onlyalpha.application.runtime_generation import OnlyRuntimeGenerationWorkAuthority
from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.execution.errors import (
    OnlyResearchExecutionOwnershipLostError,
    OnlyResearchExecutionStoreUnavailableError,
)
from onlyalpha.research.execution.model import (
    OnlyResearchExecutionClaim,
    OnlyResearchRunAttempt,
    OnlyResearchRunAttemptId,
    OnlyResearchWorkerInstanceId,
)
from onlyalpha.research.run.model import OnlyResearchRun, OnlyResearchRunState

from .chart_calculation_compilation_store import OnlyPostgresChartCalculationCompilationStore
from .config import OnlyPostgresOperationalConnectionOptions
from .research_execution_store import _ATTEMPT_COLUMNS, OnlyPostgresResearchExecutionStore, _decode_attempt
from .research_run_store import OnlyPostgresResearchRunStore


class OnlyPostgresChartNativeExecutionStore:
    """SQL-only Claim seam; no production EXECUTE grant or Native consumer yet.

    The caller must separately complete Source/installed Host preflight. Runtime
    proof spans actual COMMIT, never computation. The read credential is separate
    from the execute-only credential and cannot mutate either operational owner.
    """

    def __init__(
        self,
        dsn: str,
        *,
        reader_dsn: str,
        runtime_generations: OnlyRuntimeGenerationWorkAuthority,
        options: OnlyPostgresOperationalConnectionOptions | None = None,
    ) -> None:
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)
        self._runtime = runtime_generations
        self._compilations = OnlyPostgresChartCalculationCompilationStore(reader_dsn, options)
        self._runs = OnlyPostgresResearchRunStore(reader_dsn, options)
        self._attempts = OnlyPostgresResearchExecutionStore(reader_dsn, options)

    def claim(
        self,
        operation: OnlyChartCalculationOperationV1,
        frozen: OnlyChartCalculationCompilationV1,
        *,
        expected_revision: int,
        attempt_id: OnlyResearchRunAttemptId,
        worker_instance_id: OnlyResearchWorkerInstanceId,
        lease_duration: timedelta,
        max_attempts: int,
        run_started_at: datetime,
    ) -> OnlyResearchExecutionClaim | None:
        if (
            type(expected_revision) is not int
            or expected_revision not in {0, 1}
            or type(max_attempts) is not int
            or max_attempts < 1
            or lease_duration <= timedelta(0)
        ):
            raise ValueError("CHART_NATIVE_SQL_REQUEST_INVALID")
        if self._compilations.load_verified(operation) != frozen:
            raise ValueError("CHART_NATIVE_OPERATIONAL_RELATION_INVALID")
        expected = self._runs.load(operation.reserved_run_id)
        if expected.revision != expected_revision or expected.state not in {
            OnlyResearchRunState.QUEUED,
            OnlyResearchRunState.RUNNING,
        }:
            raise OnlyResearchExecutionOwnershipLostError("CHART_NATIVE_OWNERSHIP_LOST")
        running = (
            expected.transition(OnlyResearchRunState.RUNNING, at=run_started_at)
            if expected.state is OnlyResearchRunState.QUEUED
            else expected
        )
        issued: OnlyResearchRunAttempt | None = None
        try:
            # No PG row/frontier is held while waiting for this filesystem owner.
            # Runtime lifecycle writers must never acquire PG locks under EX.
            with self._runtime.hold_work_binding_evidence(operation.reserved_run_id.value) as binding:
                frozen.runtime_binding_reference.verifies(binding, require_active=True)
                only_require_chart_calculation_new_admission(self._runtime, operation, frozen)
                with psycopg.connect(self._dsn) as connection:
                    row = connection.execute(
                        "SELECT public.chart_native_claim_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            1,
                            operation.operation_id.value,
                            operation.reserved_run_id.value,
                            expected_revision,
                            frozen.compilation_fingerprint,
                            frozen.runtime_generation_fingerprint,
                            only_canonical_json(frozen.to_dict()),
                            attempt_id.value,
                            worker_instance_id.value,
                            lease_duration,
                            max_attempts,
                            run_started_at,
                        ),
                    ).fetchone()
                    if row is None or row[0] is None:
                        return None  # No Claim; no semantic/historical absence conclusion.
                    payload = row[0]
                    if type(payload) is not dict or set(payload) != {"schema_version", "run", "attempt"}:
                        raise ValueError("CHART_NATIVE_SQL_RESPONSE_INVALID")
                    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
                        raise ValueError("CHART_NATIVE_SQL_RESPONSE_INVALID")
                    run_payload = _timestamps(
                        payload["run"], ("queued_at", "started_at", "cancel_requested_at", "finished_at")
                    )
                    if OnlyPostgresResearchRunStore._decode(run_payload) != running:
                        raise ValueError("CHART_NATIVE_SQL_RESPONSE_INVALID")
                    attempt_payload = _timestamps(
                        payload["attempt"], ("claimed_at", "last_heartbeat_at", "lease_expires_at", "finished_at")
                    )
                    if set(attempt_payload) != set(_ATTEMPT_COLUMNS):
                        raise ValueError("CHART_NATIVE_SQL_RESPONSE_INVALID")
                    issued = _decode_attempt(attempt_payload)
                    if (
                        issued.attempt_id != attempt_id
                        or issued.worker_instance_id != worker_instance_id
                        or issued.run_id != running.run_id
                    ):
                        raise ValueError("CHART_NATIVE_SQL_RESPONSE_INVALID")
                    connection.commit()  # Explicitly inside the original Work proof.
        except psycopg.Error as exc:
            if issued is None:
                raise OnlyResearchExecutionStoreUnavailableError("Chart Claim SQL failed") from exc
            # A lost COMMIT ACK permits observation of this exact Attempt only.
            # No retry, second identity, Work release or compensation is permitted.
            try:
                return self._ack(operation, frozen, running, issued)
            except (ValueError, OnlyResearchExecutionOwnershipLostError) as ack_error:
                raise OnlyResearchExecutionStoreUnavailableError("CHART_NATIVE_CLAIM_COMMIT_UNKNOWN") from ack_error
        assert issued is not None
        return self._ack(operation, frozen, running, issued)

    def _ack(
        self,
        operation: OnlyChartCalculationOperationV1,
        frozen: OnlyChartCalculationCompilationV1,
        running: OnlyResearchRun,
        issued: OnlyResearchRunAttempt,
    ) -> OnlyResearchExecutionClaim:
        # Fresh owning connections: a clean context exit or SQL result is not ACK.
        if self._compilations.load_verified(operation) != frozen or self._runs.load(running.run_id) != running:
            raise OnlyResearchExecutionOwnershipLostError("CHART_NATIVE_CLAIM_COMMIT_UNKNOWN")
        attempt = self._attempts.load_attempt(issued.attempt_id)
        if attempt != issued or attempt.state.value != "ACTIVE":
            raise OnlyResearchExecutionOwnershipLostError("CHART_NATIVE_CLAIM_COMMIT_UNKNOWN")
        return OnlyResearchExecutionClaim(attempt)


def _timestamps(payload: object, names: tuple[str, ...]) -> Mapping[str, object]:
    if type(payload) is not dict:
        raise ValueError("CHART_NATIVE_SQL_RESPONSE_INVALID")
    row = dict(cast(dict[str, object], payload))
    for name in names:
        value = row[name]
        if value is not None:
            if type(value) is not str:
                raise ValueError("CHART_NATIVE_SQL_RESPONSE_INVALID")
            row[name] = datetime.fromisoformat(value)
    return row
