"""Thin explicit-SQL PostgreSQL Research Run Store adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
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
from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.command.errors import OnlyResearchCancellationConflictError
from onlyalpha.research.command.model import OnlyResearchRunPageCursor
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

from .config import OnlyPostgresOperationalConnectionOptions

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
    "calculation_execution_evidence_fingerprints",
    "failure_phase",
    "failure_code",
    "failure_detail",
)


class OnlyPostgresResearchRunStore:
    def __init__(self, dsn: str, options: OnlyPostgresOperationalConnectionOptions | None = None) -> None:
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)

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

    def find_product_command_receipt(self, command_id: OnlyProductCommandId) -> OnlyProductCommandReceipt | None:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT * FROM product_command_receipt WHERE command_id = %s",
                    (command_id.value,),
                ).fetchone()
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Product Command Receipt load failed") from exc
        if row is None:
            return None
        return self._decode_receipt(cast(Mapping[str, object], row))

    def create_queued_with_receipt(
        self,
        run: OnlyResearchRun,
        receipt: OnlyProductCommandReceipt,
    ) -> OnlyProductCommandReceipt:
        if run.state is not OnlyResearchRunState.QUEUED or run.revision != 0:
            raise OnlyResearchRunStateConflictError("submission requires revision-zero QUEUED Run")
        if (
            receipt.command_kind is not OnlyProductCommandKind.CREATE_RESEARCH_RUN
            or receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.RESEARCH_RUN
            or receipt.outcome_ref.outcome_id != run.run_id.value
            or receipt.accepted_at != run.queued_at
        ):
            raise OnlyResearchRunIntegrityError("Create Research Run receipt does not bind the prepared Run")
        run_query = sql.SQL("INSERT INTO research_run ({}) VALUES ({})").format(
            sql.SQL(", ").join(map(sql.Identifier, _COLUMNS)),
            sql.SQL(", ").join(sql.Placeholder() for _ in _COLUMNS),
        )
        try:
            with psycopg.connect(self._dsn) as connection:
                connection.execute(run_query, self._values(run))
                self._insert_receipt(connection, receipt)
            return receipt
        except psycopg.errors.UniqueViolation as exc:
            existing = self.find_product_command_receipt(receipt.command_id)
            if existing is None:
                raise OnlyResearchRunIntegrityError("Research Run or Product Command identity already exists") from exc
            return existing
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Create Research Run transaction failed") from exc

    def request_cancellation_with_receipt(
        self,
        run_id: OnlyResearchRunId,
        receipt: OnlyProductCommandReceipt,
    ) -> OnlyProductCommandReceipt:
        if (
            receipt.command_kind is not OnlyProductCommandKind.CANCEL_RESEARCH_RUN
            or receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.RESEARCH_RUN
            or receipt.outcome_ref.outcome_id != run_id.value
        ):
            raise OnlyResearchRunIntegrityError("Cancel Research Run receipt does not bind the target Run")
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                existing_row = connection.execute(
                    "SELECT * FROM product_command_receipt WHERE command_id = %s",
                    (receipt.command_id.value,),
                ).fetchone()
                if existing_row is not None:
                    return self._decode_receipt(cast(Mapping[str, object], existing_row))
                row = connection.execute(
                    "SELECT * FROM research_run WHERE run_id = %s FOR UPDATE",
                    (run_id.value,),
                ).fetchone()
                if row is None:
                    raise OnlyResearchRunNotFoundError(str(run_id))
                current = self._decode(cast(Mapping[str, object], row))
                if current.state in {OnlyResearchRunState.COMPLETED, OnlyResearchRunState.FAILED}:
                    raise OnlyResearchCancellationConflictError()
                if current.state not in {OnlyResearchRunState.CANCEL_REQUESTED, OnlyResearchRunState.CANCELLED}:
                    target = (
                        OnlyResearchRunState.CANCELLED
                        if current.state is OnlyResearchRunState.QUEUED
                        else OnlyResearchRunState.CANCEL_REQUESTED
                    )
                    transitioned = current.transition(target, at=receipt.accepted_at)
                    assignments = tuple(name for name in _COLUMNS if name != "run_id")
                    query = sql.SQL(
                        "UPDATE research_run SET {} WHERE run_id = %s AND revision = %s AND state = %s"
                    ).format(
                        sql.SQL(", ").join(
                            sql.Composed([sql.Identifier(name), sql.SQL(" = "), sql.Placeholder()])
                            for name in assignments
                        )
                    )
                    values = self._values(transitioned)
                    parameters = tuple(values[_COLUMNS.index(name)] for name in assignments) + (
                        current.run_id.value,
                        current.revision,
                        current.state.value,
                    )
                    if connection.execute(query, parameters).rowcount != 1:
                        raise OnlyResearchRunRevisionConflictError(
                            f"Run {current.run_id} revision/state changed concurrently"
                        )
                self._insert_receipt(connection, receipt)
            return receipt
        except (OnlyResearchCancellationConflictError, OnlyResearchRunNotFoundError):
            raise
        except psycopg.errors.UniqueViolation as exc:
            existing = self.find_product_command_receipt(receipt.command_id)
            if existing is None:
                raise OnlyResearchRunIntegrityError("Product Command identity conflict has no authority") from exc
            return existing
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Cancel Research Run transaction failed") from exc

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
            list(run.calculation_execution_evidence_fingerprints),
            None if failure is None else failure.phase.value,
            None if failure is None else failure.code,
            None if failure is None else failure.detail,
        )

    @staticmethod
    def _insert_receipt(connection: psycopg.Connection[object], receipt: OnlyProductCommandReceipt) -> None:
        connection.execute(
            "INSERT INTO product_command_receipt "
            "(command_id, command_kind, command_fingerprint, outcome_kind, outcome_id, accepted_at, schema_version) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
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

    @staticmethod
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
                schema_version=int(cast(int, row["schema_version"])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlyResearchRunIntegrityError(
                "PostgreSQL Product Command Receipt row failed strict verification"
            ) from exc

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
            raw_evidence = row["calculation_execution_evidence_fingerprints"]
            if raw_evidence is None:
                evidence: tuple[str, ...] = ()
            elif isinstance(raw_evidence, list) and all(isinstance(item, str) for item in raw_evidence):
                evidence = tuple(cast(list[str], raw_evidence))
            else:
                raise ValueError("Execution Evidence references must be an array or null")
            return OnlyResearchRun(
                run_id=OnlyResearchRunId(str(row["run_id"])),
                revision=int(cast(int, row["revision"])),
                state=OnlyResearchRunState(str(row["state"])),
                specification=specification,
                specification_fingerprint=str(row["specification_fingerprint"]),
                canonical_specification_payload=canonical,
                admission_resolution_fingerprint=str(row["admission_resolution_fingerprint"]),
                queued_at=cast(datetime, row["queued_at"]),
                started_at=cast(datetime | None, row["started_at"]),
                cancel_requested_at=cast(datetime | None, row["cancel_requested_at"]),
                finished_at=cast(datetime | None, row["finished_at"]),
                research_result_fingerprint=cast(str | None, row["research_result_fingerprint"]),
                artifact_content_fingerprint=cast(str | None, row["artifact_content_fingerprint"]),
                failure=failure,
                calculation_execution_evidence_fingerprints=evidence,
            )
        except (KeyError, TypeError, ValueError, OnlyResearchRunIntegrityError) as exc:
            raise OnlyResearchRunIntegrityError("PostgreSQL Research Run row failed strict verification") from exc


__all__ = ["OnlyPostgresResearchRunStore"]
