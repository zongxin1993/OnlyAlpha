"""Frozen PostgreSQL server/client major policy for operational recovery."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

from onlyalpha.research.run.errors import OnlyResearchRunStoreUnavailableError

ONLYALPHA_POSTGRES_SERVER_MAJOR = 16
ONLYALPHA_POSTGRES_CLIENT_MAJOR = 16


@dataclass(frozen=True, slots=True)
class OnlyPostgresServerVersion:
    version: str
    major: int


def only_postgres_server_version(dsn: str) -> OnlyPostgresServerVersion:
    try:
        with psycopg.connect(dsn) as connection:
            row = connection.execute(
                "SELECT current_setting('server_version'), current_setting('server_version_num')"
            ).fetchone()
    except psycopg.Error as exc:
        raise OnlyResearchRunStoreUnavailableError("PostgreSQL version inspection unavailable") from exc
    if row is None:
        raise OnlyResearchRunStoreUnavailableError("PostgreSQL version inspection returned no result")
    return OnlyPostgresServerVersion(str(row[0]), int(str(row[1])) // 10000)


def only_assert_supported_postgres_server(dsn: str) -> OnlyPostgresServerVersion:
    inspected = only_postgres_server_version(dsn)
    if inspected.major != ONLYALPHA_POSTGRES_SERVER_MAJOR:
        raise RuntimeError(
            f"POSTGRES_SERVER_MAJOR_UNSUPPORTED: expected {ONLYALPHA_POSTGRES_SERVER_MAJOR}, got {inspected.major}"
        )
    return inspected


__all__ = [name for name in globals() if name.startswith(("Only", "only_", "ONLYALPHA_"))]
