"""Explicit database-name fencing for destructive engineering test setup."""

from __future__ import annotations

import psycopg
from psycopg.conninfo import conninfo_to_dict


def assert_test_database(dsn: str, *, restore: bool = False) -> str:
    purpose = "RESTORE_TEST" if restore else "INTEGRATION_TEST"
    code = f"POSTGRES_{purpose}_DATABASE_REQUIRED"
    if not isinstance(dsn, str) or not dsn.strip():
        raise RuntimeError(code)
    try:
        database = conninfo_to_dict(dsn).get("dbname")
    except psycopg.Error:
        raise RuntimeError(code) from None
    suffix = "_restore_test" if restore else "_test"
    if not isinstance(database, str) or not database.endswith(suffix):
        raise RuntimeError(code)
    return database
