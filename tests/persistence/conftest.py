from __future__ import annotations

import os

import psycopg
import pytest

from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from scripts.database_guard import assert_test_database


@pytest.fixture
def postgres_dsn() -> str:
    dsn = os.environ.get("ONLYALPHA_POSTGRES_DSN")
    if not dsn:
        pytest.fail("ONLYALPHA_POSTGRES_DSN is required for the canonical Compose PostgreSQL lane")
    assert_test_database(dsn)
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    OnlyPostgresMigrationAuthority(dsn).migrate()
    return dsn
