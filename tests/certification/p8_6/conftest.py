from __future__ import annotations

import os

import psycopg
import pytest


@pytest.fixture
def postgres_dsn() -> str:
    dsn = os.environ.get("ONLYALPHA_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.fail("ONLYALPHA_TEST_POSTGRES_DSN is required for the P8.6 product certification lane")
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    return dsn
