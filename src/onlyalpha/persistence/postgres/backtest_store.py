"""Explicit-SQL PostgreSQL Backtest Run and Product receipt authority."""

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
from onlyalpha.backtest.errors import (
    OnlyBacktestIntegrityError,
    OnlyBacktestNotFoundError,
    OnlyBacktestStateConflictError,
    OnlyBacktestStoreUnavailableError,
)
from onlyalpha.backtest.model import (
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
            return self.load(run_id), existing
        except psycopg.Error as exc:
            raise OnlyBacktestStoreUnavailableError("Backtest cancellation transaction failed") from exc


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
            admission_resolution_fingerprint=str(row["admission_resolution_fingerprint"]),
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


__all__ = ["OnlyPostgresBacktestStore"]
