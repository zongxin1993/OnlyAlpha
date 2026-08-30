"""Repository-controlled explicit ClickHouse schema migration authority."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .client import OnlyClickHouseClient

DEFAULT_CLICKHOUSE_MIGRATION_ROOT = Path(__file__).resolve().parents[4] / "database/clickhouse/migrations"


@dataclass(frozen=True, slots=True)
class OnlyClickHouseMigration:
    migration_id: str
    checksum_sha256: str
    sql: str


def only_discover_clickhouse_migrations(
    root: Path = DEFAULT_CLICKHOUSE_MIGRATION_ROOT,
) -> tuple[OnlyClickHouseMigration, ...]:
    paths = tuple(sorted(root.glob("[0-9][0-9][0-9][0-9]_*.sql")))
    if not paths:
        raise RuntimeError("CLICKHOUSE_MIGRATION_HISTORY_EMPTY")
    return tuple(
        OnlyClickHouseMigration(path.stem, hashlib.sha256(path.read_bytes()).hexdigest(), path.read_text())
        for path in paths
    )


class OnlyClickHouseMigrationAuthority:
    def __init__(self, client: OnlyClickHouseClient) -> None:
        self._client = client
        self._migrations = only_discover_clickhouse_migrations()

    def applied(self) -> tuple[tuple[str, str], ...]:
        ledger = self._client.query_json(
            "SELECT count() AS count FROM system.tables "
            f"WHERE database='{self._client.config.database}' AND name='onlyalpha_schema_migration'",
            database="default",
        )
        if not ledger or int(str(ledger[0]["count"])) == 0:
            return ()
        rows = self._client.query_json(
            "SELECT migration_id, checksum_sha256 FROM onlyalpha_schema_migration ORDER BY migration_id"
        )
        return tuple((str(row["migration_id"]), str(row["checksum_sha256"])) for row in rows)

    def plan(self) -> tuple[OnlyClickHouseMigration, ...]:
        applied = self.applied()
        expected = tuple((item.migration_id, item.checksum_sha256) for item in self._migrations)
        if applied != expected[: len(applied)]:
            raise RuntimeError("CLICKHOUSE_MIGRATION_HISTORY_DIVERGED")
        return self._migrations[len(applied) :]

    def migrate(self) -> tuple[str, ...]:
        self._client.execute(f"CREATE DATABASE IF NOT EXISTS {self._client.config.database}", database="default")
        applied: list[str] = []
        for migration in self.plan():
            rendered = migration.sql.replace("{storage_policy}", self._client.config.storage_policy)
            self._client.execute_script(rendered)
            self._client.execute(
                "INSERT INTO onlyalpha_schema_migration (migration_id, checksum_sha256, applied_at) "
                "SETTINGS async_insert=0 VALUES "
                f"('{migration.migration_id}', '{migration.checksum_sha256}', now64(9))"
            )
            applied.append(migration.migration_id)
        self.validate()
        return tuple(applied)

    def validate(self) -> None:
        if self.plan():
            raise RuntimeError("CLICKHOUSE_SCHEMA_BEHIND")
        rows = self._client.query_json(
            "SELECT name, storage_policy FROM system.tables WHERE database=currentDatabase() "
            "AND name IN ('market_raw_event','market_trade','market_bar','market_reference_price') ORDER BY name"
        )
        if len(rows) != 4 or any(row.get("storage_policy") != self._client.config.storage_policy for row in rows):
            raise RuntimeError("CLICKHOUSE_STORAGE_POLICY_MISMATCH")


__all__ = [name for name in globals() if name.startswith(("Only", "only_", "DEFAULT_"))]
