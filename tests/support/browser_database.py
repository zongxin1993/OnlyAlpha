"""Owner-approved reset of the fixed local dev Browser test namespaces only."""

from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg

from onlyalpha.persistence.clickhouse import OnlyClickHouseClient
from onlyalpha.persistence.postgres import only_assert_postgres_test_database
from scripts.dev_verification import BROWSER_RESET_FENCE

DEV_TEST_DSN = "postgresql://onlyalpha:onlyalpha@postgres:5432/onlyalpha_dev_validation_test"
RUN_METADATA = Path(__file__).resolve().parents[2] / ".onlyalpha-dev-source-cut.json"
CLICKHOUSE_NAMESPACES = frozenset({"onlyalpha_test_chart_study_browser", "onlyalpha_test_local_read_browser"})


def reset_dev_browser_test_namespace(dsn: str, clickhouse: OnlyClickHouseClient) -> None:
    only_assert_postgres_test_database(dsn)
    if dsn != DEV_TEST_DSN:
        raise ValueError("BROWSER_TEST_RESET_DATABASE_REFUSED")
    if clickhouse.config.database not in CLICKHOUSE_NAMESPACES or clickhouse.config.url != "http://clickhouse:8123":
        raise ValueError("BROWSER_TEST_RESET_CLICKHOUSE_REFUSED")
    # Playwright's child process preserves environment lineage, not arbitrary FDs.
    # The canonical launcher holds its host/container locks for the entire suite.
    operation = os.environ.get("ONLYALPHA_DEV_VERIFICATION_OPERATION_ID")
    source_root = os.environ.get("ONLYALPHA_DEV_SOURCE_ROOT")
    if not operation or not source_root:
        raise ValueError("BROWSER_TEST_RESET_OPERATION_REQUIRED")
    metadata = json.loads(RUN_METADATA.read_text())
    if metadata.get("operation_id") != operation or metadata.get("source_root") != source_root:
        raise ValueError("BROWSER_TEST_RESET_OPERATION_REFUSED")
    fence = RUN_METADATA.parent / BROWSER_RESET_FENCE
    if fence.exists():
        raise ValueError("BROWSER_TEST_RESET_UNKNOWN_REQUIRES_OWNER_RECOVERY")
    with psycopg.connect(dsn) as connection:
        locked = connection.execute("SELECT pg_try_advisory_xact_lock(71493012)").fetchone()
        if locked != (True,):
            raise ValueError("BROWSER_TEST_RESET_BUSY")
        fence.parent.mkdir(parents=True, exist_ok=True)
        with fence.open("x") as stream:
            json.dump(
                {
                    "operation_id": operation,
                    "source_root": source_root,
                    "postgres_database": "onlyalpha_dev_validation_test",
                    "clickhouse_namespace": clickhouse.config.database,
                    "outcome": "UNKNOWN",
                },
                stream,
            )
            stream.flush()
            os.fsync(stream.fileno())
        # Complete all context/lock checks before either Authority is modified.
        # These are disposable fixture inputs, never a business recovery operation.
        clickhouse.execute(f"DROP DATABASE IF EXISTS {clickhouse.config.database} SYNC", database="default")
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    # Only observed CH completion AND observed PG commit settle the reservation.
    # Transport/commit failure keeps it UNKNOWN; process exit is not remote proof.
    fence.unlink()
