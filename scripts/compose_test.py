"""Run environment-dependent tests against isolated databases in dev Compose."""

from __future__ import annotations

import os
import subprocess
import sys

import psycopg

from onlyalpha.persistence.postgres import only_assert_postgres_test_database


def main() -> int:
    dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
    only_assert_postgres_test_database(dsn)
    admin_dsn = dsn.rsplit("/", 1)[0] + "/postgres"
    database = dsn.rsplit("/", 1)[-1]
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        exists = connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,)).fetchone()
        if exists is None:
            connection.execute(f'CREATE DATABASE "{database}"')
    if len(sys.argv) < 2:
        raise ValueError("COMPOSE_TEST_COMMAND_REQUIRED")
    completed = subprocess.run(sys.argv[1:], check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
