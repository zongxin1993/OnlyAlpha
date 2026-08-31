from __future__ import annotations

import os

import psycopg
import pytest

from onlyalpha.persistence.postgres import only_assert_postgres_test_database


@pytest.fixture
def postgres_dsn() -> str:
    dsn = os.environ.get("ONLYALPHA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.fail("ONLYALPHA_TEST_POSTGRES_DSN is required for the canonical research-postgres lane")
    only_assert_postgres_test_database(dsn)
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    return dsn
