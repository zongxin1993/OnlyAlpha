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

    def seed_queued(self, run: OnlyResearchRun) -> OnlyResearchRun:
        if run.state is not OnlyResearchRunState.QUEUED or run.revision != 0:
            raise OnlyResearchRunStateConflictError("seed_queued requires revision-zero QUEUED Run")
        try:
            with psycopg.connect(self._dsn) as connection:
                connection.execute(_insert_run_query(), OnlyPostgresResearchRunStore._values(run))
            return run
        except psycopg.errors.UndefinedColumn as exc:
            if run.authoring_provenance is not None or "authoring_provenance" not in str(exc):
                raise OnlyResearchRunStoreUnavailableError("Research Run seed transaction failed") from exc
            legacy_columns = _COLUMNS[:-1]
            try:
                with psycopg.connect(self._dsn) as connection:
                    connection.execute(
                        _insert_run_query(legacy_columns),
                        OnlyPostgresResearchRunStore._values(run)[:-1],
                    )
                return run
            except psycopg.errors.UndefinedColumn as retry_exc:
                if run.authoring_provenance is not None or "authoring_provenance" not in str(retry_exc):
                    raise OnlyResearchRunStoreUnavailableError("Research Run seed transaction failed") from retry_exc
                with psycopg.connect(self._dsn) as connection:
                    connection.execute(
                        _insert_run_query(_COLUMNS[:-2]),
                        OnlyPostgresResearchRunStore._values(run)[:-2],
                    )
                return run
            except psycopg.errors.UniqueViolation as retry_exc:
                raise OnlyResearchRunIntegrityError(f"Research Run already exists: {run.run_id}") from retry_exc
            except psycopg.Error as retry_exc:
                raise OnlyResearchRunStoreUnavailableError("Research Run seed transaction failed") from retry_exc
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
