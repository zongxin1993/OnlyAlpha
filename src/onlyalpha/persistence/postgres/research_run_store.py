"""Thin explicit-SQL PostgreSQL Research Run Store adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import cast

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.command.model import (
    OnlyResearchRunPageCursor,
    OnlyResearchSubmissionKey,
    OnlyResearchSubmissionRecord,
)
from onlyalpha.research.run.errors import (
    OnlyResearchRunIntegrityError,
    OnlyResearchRunNotFoundError,
    OnlyResearchRunRevisionConflictError,
    OnlyResearchRunStateConflictError,
    OnlyResearchRunStoreUnavailableError,
)
from onlyalpha.research.run.model import (
    OnlyResearchRun,
    OnlyResearchRunFailure,
    OnlyResearchRunFailurePhase,
    OnlyResearchRunId,
    OnlyResearchRunState,
)
from onlyalpha.research.specification.model import OnlyResearchSpecification

_COLUMNS = (
    "run_id",
    "revision",
    "state",
    "specification_schema_version",
    "specification_fingerprint",
    "specification_payload",
    "admission_resolution_fingerprint",
    "queued_at",
    "started_at",
    "cancel_requested_at",
    "finished_at",
    "research_result_fingerprint",
    "artifact_content_fingerprint",
    "failure_phase",
    "failure_code",
    "failure_detail",
)


class OnlyPostgresResearchRunStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def create_queued(self, run: OnlyResearchRun) -> OnlyResearchRun:
        if run.state is not OnlyResearchRunState.QUEUED or run.revision != 0:
            raise OnlyResearchRunStateConflictError("create_queued requires revision-zero QUEUED Run")
        query = sql.SQL("INSERT INTO research_run ({}) VALUES ({})").format(
            sql.SQL(", ").join(map(sql.Identifier, _COLUMNS)),
            sql.SQL(", ").join(sql.Placeholder() for _ in _COLUMNS),
        )
        try:
            with psycopg.connect(self._dsn) as connection:
                connection.execute(query, self._values(run))
            return run
        except psycopg.errors.UniqueViolation as exc:
            raise OnlyResearchRunIntegrityError(f"Research Run already exists: {run.run_id}") from exc
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Research Run create transaction failed") from exc

    def load(self, run_id: OnlyResearchRunId) -> OnlyResearchRun:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute("SELECT * FROM research_run WHERE run_id = %s", (run_id.value,)).fetchone()
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Research Run load failed") from exc
        if row is None:
            raise OnlyResearchRunNotFoundError(str(run_id))
        return self._decode(cast(Mapping[str, object], row))

    def find_submission(self, submission_key: OnlyResearchSubmissionKey) -> OnlyResearchSubmissionRecord | None:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT submission_key, command_fingerprint, run_id "
                    "FROM research_run_submission WHERE submission_key = %s",
                    (submission_key.value,),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Research submission load failed") from exc
        if row is None:
            return None
        try:
            return OnlyResearchSubmissionRecord(
                OnlyResearchSubmissionKey(str(row["submission_key"])),
                str(row["command_fingerprint"]),
                OnlyResearchRunId(str(row["run_id"])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlyResearchRunIntegrityError(
                "PostgreSQL Research submission row failed strict verification"
            ) from exc

    def create_queued_submission(
        self,
        run: OnlyResearchRun,
        submission_key: OnlyResearchSubmissionKey,
        command_fingerprint: str,
    ) -> OnlyResearchSubmissionRecord:
        if run.state is not OnlyResearchRunState.QUEUED or run.revision != 0:
            raise OnlyResearchRunStateConflictError("submission requires revision-zero QUEUED Run")
        record = OnlyResearchSubmissionRecord(submission_key, command_fingerprint, run.run_id)
        run_query = sql.SQL("INSERT INTO research_run ({}) VALUES ({})").format(
            sql.SQL(", ").join(map(sql.Identifier, _COLUMNS)),
            sql.SQL(", ").join(sql.Placeholder() for _ in _COLUMNS),
        )
        try:
            with psycopg.connect(self._dsn) as connection:
                connection.execute(run_query, self._values(run))
                connection.execute(
                    "INSERT INTO research_run_submission (submission_key, command_fingerprint, run_id) "
                    "VALUES (%s, %s, %s)",
                    (submission_key.value, command_fingerprint, run.run_id.value),
                )
            return record
        except psycopg.errors.UniqueViolation as exc:
            existing = self.find_submission(submission_key)
            if existing is None:
                raise OnlyResearchRunIntegrityError("Research Run or submission identity already exists") from exc
            return existing
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Research submission transaction failed") from exc

    def list_recent(self, *, limit: int, after: OnlyResearchRunPageCursor | None = None) -> tuple[OnlyResearchRun, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("Research Run list limit must be positive")
        query = "SELECT * FROM research_run"
        parameters: tuple[object, ...]
        if after is None:
            parameters = (limit,)
        else:
            query += " WHERE (queued_at, run_id) < (%s, %s)"
            parameters = (after.queued_at, after.run_id.value, limit)
        query += " ORDER BY queued_at DESC, run_id DESC LIMIT %s"
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                rows = connection.execute(query, parameters).fetchall()
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Research Run list failed") from exc
        return tuple(self._decode(cast(Mapping[str, object], row)) for row in rows)

    def commit_transition(self, previous: OnlyResearchRun, transitioned: OnlyResearchRun) -> OnlyResearchRun:
        if not transitioned.is_exact_successor_of(previous):
            raise OnlyResearchRunStateConflictError("Store accepts only an exact Domain-validated successor")
        allowed_command = (
            previous.state is OnlyResearchRunState.QUEUED and transitioned.state is OnlyResearchRunState.CANCELLED
        ) or (
            previous.state is OnlyResearchRunState.RUNNING
            and transitioned.state is OnlyResearchRunState.CANCEL_REQUESTED
        )
        if not allowed_command:
            raise OnlyResearchRunStateConflictError(
                "Claim and execution outcomes require the fenced Research Execution Store"
            )
        assignments = tuple(name for name in _COLUMNS if name != "run_id")
        query = sql.SQL("UPDATE research_run SET {} WHERE run_id = %s AND revision = %s AND state = %s").format(
            sql.SQL(", ").join(
                sql.Composed([sql.Identifier(name), sql.SQL(" = "), sql.Placeholder()]) for name in assignments
            )
        )
        values = self._values(transitioned)
        parameters = tuple(values[_COLUMNS.index(name)] for name in assignments) + (
            previous.run_id.value,
            previous.revision,
            previous.state.value,
        )
        try:
            with psycopg.connect(self._dsn) as connection:
                cursor = connection.execute(query, parameters)
                if cursor.rowcount != 1:
                    raise OnlyResearchRunRevisionConflictError(
                        f"Run {previous.run_id} revision/state changed concurrently"
                    )
            return transitioned
        except OnlyResearchRunRevisionConflictError:
            raise
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Research Run transition transaction failed") from exc

    @staticmethod
    def _values(run: OnlyResearchRun) -> tuple[object, ...]:
        failure = run.failure
        return (
            run.run_id.value,
            run.revision,
            run.state.value,
            run.specification.schema_version,
            run.specification_fingerprint,
            run.canonical_specification_payload,
            run.admission_resolution_fingerprint,
            run.queued_at,
            run.started_at,
            run.cancel_requested_at,
            run.finished_at,
            run.research_result_fingerprint,
            run.artifact_content_fingerprint,
            None if failure is None else failure.phase.value,
            None if failure is None else failure.code,
            None if failure is None else failure.detail,
        )

    @staticmethod
    def _decode(row: Mapping[str, object]) -> OnlyResearchRun:
        try:
            raw = json.loads(str(row["specification_payload"]))
            if not isinstance(raw, dict):
                raise ValueError("Specification payload is not an object")
            specification = OnlyResearchSpecification.from_dict(raw)
            canonical = only_canonical_json(specification.to_dict())
            if canonical != row["specification_payload"]:
                raise ValueError("Specification payload is not exact canonical JSON")
            if specification.schema_version != row["specification_schema_version"]:
                raise ValueError("Specification schema version mismatch")
            failure = (
                None
                if row["failure_phase"] is None
                else OnlyResearchRunFailure(
                    OnlyResearchRunFailurePhase(str(row["failure_phase"])),
                    str(row["failure_code"]),
                    str(row["failure_detail"]),
                )
            )
            return OnlyResearchRun(
                OnlyResearchRunId(str(row["run_id"])),
                int(cast(int, row["revision"])),
                OnlyResearchRunState(str(row["state"])),
                specification,
                str(row["specification_fingerprint"]),
                canonical,
                str(row["admission_resolution_fingerprint"]),
                cast(datetime, row["queued_at"]),
                cast(datetime | None, row["started_at"]),
                cast(datetime | None, row["cancel_requested_at"]),
                cast(datetime | None, row["finished_at"]),
                cast(str | None, row["research_result_fingerprint"]),
                cast(str | None, row["artifact_content_fingerprint"]),
                failure,
            )
        except (KeyError, TypeError, ValueError, OnlyResearchRunIntegrityError) as exc:
            raise OnlyResearchRunIntegrityError("PostgreSQL Research Run row failed strict verification") from exc


__all__ = ["OnlyPostgresResearchRunStore"]
