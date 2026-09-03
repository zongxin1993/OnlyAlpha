"""Test support derived from the ordered repository migration authority."""

from __future__ import annotations

from pathlib import Path

from onlyalpha.persistence.postgres import DEFAULT_MIGRATION_ROOT, only_discover_postgres_migrations


def current_migrations() -> tuple[str, ...]:
    return tuple(item.migration_id for item in only_discover_postgres_migrations(DEFAULT_MIGRATION_ROOT))


def migrations_through(migration_id: str) -> tuple[str, ...]:
    migrations = current_migrations()
    try:
        index = migrations.index(migration_id)
    except ValueError as exc:
        raise ValueError(f"unknown repository migration: {migration_id}") from exc
    return migrations[: index + 1]


def copy_migrations_through(target: Path, migration_id: str) -> tuple[str, ...]:
    migrations = migrations_through(migration_id)
    for current in migrations:
        source = DEFAULT_MIGRATION_ROOT / f"{current}.sql"
        (target / source.name).write_bytes(source.read_bytes())
    return migrations


def tamper_migration(target: Path, migration_id: str) -> None:
    path = target / f"{migration_id}.sql"
    path.write_bytes(path.read_bytes() + b"\n-- deterministic checksum tamper\n")
