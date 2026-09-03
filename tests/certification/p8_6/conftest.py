from __future__ import annotations

import os
from pathlib import Path

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


@pytest.fixture(scope="session")
def backtest_product_config() -> Path:
    """Deterministic Product config required by the real HTTP composition root."""

    return Path(__file__).parents[2] / "fixtures" / "legacy_macd" / "cluster.json"
