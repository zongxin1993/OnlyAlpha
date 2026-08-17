"""Forward-only checksummed PostgreSQL migration authority."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from onlyalpha.research.run.errors import (
    OnlyPostgresMigrationIntegrityError,
    OnlyPostgresSchemaIncompatibleError,
    OnlyResearchRunStoreUnavailableError,
)

MIGRATION_LOCK_ID = 591_487_210_081
DEFAULT_MIGRATION_ROOT = Path(__file__).resolve().parents[4] / "database/postgres/migrations"


@dataclass(frozen=True, order=True, slots=True)
class OnlyPostgresMigration:
    migration_id: str
    checksum_sha256: str
    sql: str


class OnlyPostgresSchemaVerdict(StrEnum):
    COMPATIBLE = "COMPATIBLE"
    BEHIND = "BEHIND"
    AHEAD = "AHEAD"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    HISTORY_DIVERGED = "HISTORY_DIVERGED"
    LEDGER_MISSING = "LEDGER_MISSING"


@dataclass(frozen=True, slots=True)
class OnlyPostgresSchemaStatus:
    verdict: OnlyPostgresSchemaVerdict
    repository_migrations: tuple[str, ...]
    applied_migrations: tuple[str, ...]
    pending_migrations: tuple[str, ...]
    detail: str

    @property
    def compatible(self) -> bool:
        return self.verdict is OnlyPostgresSchemaVerdict.COMPATIBLE


def only_discover_postgres_migrations(root: Path = DEFAULT_MIGRATION_ROOT) -> tuple[OnlyPostgresMigration, ...]:
    paths = tuple(sorted(root.glob("[0-9][0-9][0-9][0-9]_*.sql")))
    if not paths:
        raise OnlyPostgresMigrationIntegrityError("repository migration history is empty")
    migrations = tuple(
        OnlyPostgresMigration(
            path.stem, hashlib.sha256(path.read_bytes()).hexdigest(), path.read_text(encoding="utf-8")
        )
        for path in paths
    )
    if len({item.migration_id for item in migrations}) != len(migrations):
        raise OnlyPostgresMigrationIntegrityError("duplicate repository migration ID")
    return migrations


class OnlyPostgresMigrationAuthority:
    def __init__(self, dsn: str, *, migration_root: Path = DEFAULT_MIGRATION_ROOT) -> None:
        self._dsn = dsn
        self._migrations = only_discover_postgres_migrations(migration_root)

    @property
    def migrations(self) -> tuple[OnlyPostgresMigration, ...]:
        return self._migrations

    def status(self) -> OnlyPostgresSchemaStatus:
        try:
            with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT to_regclass('public.onlyalpha_schema_migration') AS ledger")
                    ledger = cursor.fetchone()
                    if ledger is None or ledger["ledger"] is None:
                        return OnlyPostgresSchemaStatus(
                            OnlyPostgresSchemaVerdict.LEDGER_MISSING,
                            tuple(item.migration_id for item in self._migrations),
                            (),
                            tuple(item.migration_id for item in self._migrations),
                            "migration ledger is missing; run database migrate",
                        )
                    cursor.execute(
                        "SELECT migration_id, checksum_sha256 FROM onlyalpha_schema_migration ORDER BY migration_id"
                    )
                    applied = tuple(
                        (str(row["migration_id"]), str(row["checksum_sha256"])) for row in cursor.fetchall()
                    )
        except psycopg.Error as exc:
            raise OnlyResearchRunStoreUnavailableError("PostgreSQL schema status unavailable") from exc
        repository = {item.migration_id: item.checksum_sha256 for item in self._migrations}
        applied_ids = tuple(item[0] for item in applied)
        applied_checksums = dict(applied)
        unknown = sorted(set(applied_ids) - set(repository))
        if unknown:
            return self._status(OnlyPostgresSchemaVerdict.AHEAD, applied, f"unknown database migrations: {unknown}")
        mismatched = sorted(key for key in applied_ids if applied_checksums[key] != repository[key])
        if mismatched:
            return self._status(
                OnlyPostgresSchemaVerdict.CHECKSUM_MISMATCH, applied, f"migration checksum mismatch: {mismatched}"
            )
        repository_ids = tuple(repository)
        if applied_ids != repository_ids[: len(applied_ids)]:
            return self._status(
                OnlyPostgresSchemaVerdict.HISTORY_DIVERGED,
                applied,
                f"database migration history is not an exact repository prefix: {list(applied_ids)}",
            )
        pending = repository_ids[len(applied_ids) :]
        if pending:
            return self._status(OnlyPostgresSchemaVerdict.BEHIND, applied, f"pending migrations: {list(pending)}")
        return self._status(OnlyPostgresSchemaVerdict.COMPATIBLE, applied, "schema is compatible")

    def assert_compatible(self) -> None:
        status = self.status()
        if not status.compatible:
            raise OnlyPostgresSchemaIncompatibleError(f"{status.verdict}: {status.detail}")

    def plan(self) -> tuple[OnlyPostgresMigration, ...]:
        status = self.status()
        if status.verdict not in {OnlyPostgresSchemaVerdict.LEDGER_MISSING, OnlyPostgresSchemaVerdict.BEHIND}:
            if status.verdict is OnlyPostgresSchemaVerdict.COMPATIBLE:
                return ()
            raise OnlyPostgresMigrationIntegrityError(status.detail)
        applied_count = len(status.applied_migrations)
        return self._migrations[applied_count:]

    def migrate(self) -> tuple[str, ...]:
        try:
            with psycopg.connect(self._dsn, autocommit=True) as connection:
                connection.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
                try:
                    pending = self.plan()
                    if not pending:
                        return ()
                    with connection.transaction():
                        for migration in pending:
                            connection.execute(migration.sql)
                            connection.execute(
                                "INSERT INTO onlyalpha_schema_migration (migration_id, checksum_sha256) VALUES (%s, %s)",
                                (migration.migration_id, migration.checksum_sha256),
                            )
                    self.assert_compatible()
                    return tuple(item.migration_id for item in pending)
                finally:
                    connection.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))
        except psycopg.OperationalError as exc:
            raise OnlyResearchRunStoreUnavailableError("PostgreSQL migration unavailable") from exc
        except psycopg.Error as exc:
            raise OnlyPostgresMigrationIntegrityError("PostgreSQL migration transaction failed") from exc

    def _status(
        self, verdict: OnlyPostgresSchemaVerdict, applied: tuple[tuple[str, str], ...], detail: str
    ) -> OnlyPostgresSchemaStatus:
        repository = tuple(item.migration_id for item in self._migrations)
        return OnlyPostgresSchemaStatus(
            verdict,
            repository,
            tuple(item[0] for item in applied),
            repository[len(applied) :] if tuple(item[0] for item in applied) == repository[: len(applied)] else (),
            detail,
        )


__all__ = [name for name in globals() if name.startswith(("Only", "only_", "DEFAULT_"))]
