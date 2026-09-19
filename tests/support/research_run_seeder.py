"""Explicit test and historical-fixture Research Run seeding."""

from __future__ import annotations

import psycopg

from onlyalpha.application.product_command_authority import OnlyProductCommandConflictError
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandReceipt,
)
from onlyalpha.persistence.postgres.config import OnlyPostgresOperationalConnectionOptions
from onlyalpha.persistence.postgres.product_command_authority import OnlyPostgresProductCommandAuthority
from onlyalpha.persistence.postgres.research_run_store import (
    _COLUMNS,
    OnlyPostgresResearchRunStore,
    _insert_run_query,
)
from onlyalpha.research.run.errors import (
    OnlyResearchRunIntegrityError,
    OnlyResearchRunStateConflictError,
    OnlyResearchRunStoreUnavailableError,
)
from onlyalpha.research.run.model import OnlyResearchRun, OnlyResearchRunState


class OnlyPostgresResearchRunSeeder:
    """Raw insertion capability available only to test and historical fixtures."""

    def __init__(self, dsn: str, options: OnlyPostgresOperationalConnectionOptions | None = None) -> None:
        self._dsn = (options or OnlyPostgresOperationalConnectionOptions()).apply(dsn)

    def seed_queued(self, run: OnlyResearchRun, *, columns: tuple[str, ...] = _COLUMNS) -> OnlyResearchRun:
        if run.state is not OnlyResearchRunState.QUEUED or run.revision != 0:
            raise OnlyResearchRunStateConflictError("seed_queued requires revision-zero QUEUED Run")
        if tuple(columns) != _COLUMNS[: len(columns)]:
            raise OnlyResearchRunIntegrityError("Historical Research Run columns must be an ordered prefix")
        values = OnlyPostgresResearchRunStore._values(run)
        value_by_column = dict(zip(_COLUMNS, values, strict=True))
        optional_tail = (
            "authoring_provenance",
            "strategy_research_composition_fingerprint",
            "origin_kind",
        )
        try:
            with psycopg.connect(self._dsn) as connection:
                available = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'research_run'"
                    ).fetchall()
                }
                missing = tuple(column for column in columns if column not in available)
                if missing:
                    first_missing = columns.index(missing[0])
                    if columns[first_missing:] != missing or any(column not in optional_tail for column in missing):
                        raise OnlyResearchRunIntegrityError("Historical Research Run columns are not available")
                    columns = columns[:first_missing]
                for column in optional_tail:
                    if (
                        column not in columns
                        and value_by_column[column] is not None
                        and not (column == "origin_kind" and value_by_column[column] == "GENERAL")
                    ):
                        raise OnlyResearchRunIntegrityError(f"Historical schema cannot seed {column}")
                connection.execute(
                    _insert_run_query(columns),
                    tuple(value_by_column[column] for column in columns),
                )
            return run
        except psycopg.errors.UniqueViolation as exc:
            raise OnlyResearchRunIntegrityError(f"Research Run already exists: {run.run_id}") from exc
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Research Run seed transaction failed") from exc

    def seed_queued_with_receipt(
        self,
        run: OnlyResearchRun,
        receipt: OnlyProductCommandReceipt,
    ) -> OnlyProductCommandReceipt:
        if run.state is not OnlyResearchRunState.QUEUED or run.revision != 0:
            raise OnlyResearchRunStateConflictError("historical submission requires revision-zero QUEUED Run")
        if (
            receipt.command_kind is not OnlyProductCommandKind.CREATE_RESEARCH_RUN
            or receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.RESEARCH_RUN
            or receipt.outcome_ref.outcome_id != run.run_id.value
            or receipt.accepted_at != run.queued_at
        ):
            raise OnlyResearchRunIntegrityError("Historical Research Run receipt does not bind the prepared Run")
        try:
            with psycopg.connect(self._dsn) as connection:
                authority = OnlyPostgresProductCommandAuthority
                authority.insert_or_verify_admission(
                    connection,
                    OnlyProductCommandAdmissionV1(
                        receipt.command_id,
                        receipt.command_kind,
                        receipt.command_fingerprint,
                    ),
                )
                existing = authority.load_verified_receipt_in_transaction(connection, receipt.command_id)
                if existing is not None:
                    return existing
                connection.execute(_insert_run_query(), OnlyPostgresResearchRunStore._values(run))
                OnlyPostgresResearchRunStore._insert_receipt(connection, receipt)
            return receipt
        except OnlyProductCommandConflictError as exc:
            raise OnlyResearchRunIntegrityError(
                f"Product Command identity already exists: {receipt.command_id}"
            ) from exc
        except psycopg.errors.UniqueViolation as exc:
            existing = OnlyPostgresResearchRunStore(self._dsn).find_product_command_receipt(receipt.command_id)
            if existing is None:
                raise OnlyResearchRunIntegrityError("Research Run or Product Command identity already exists") from exc
            return existing
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("Historical Research Run transaction failed") from exc


__all__ = ["OnlyPostgresResearchRunSeeder"]
