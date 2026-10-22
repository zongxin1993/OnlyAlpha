"""Exact retained Run facts reload in fresh reader processes; no Product API admission."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from onlyalpha.persistence.postgres import only_assert_postgres_test_database
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from tests.research.postgres.test_postgres_authority import _queued
from tests.support.research_run_seeder import OnlyPostgresResearchRunSeeder

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_fresh_reader_processes_reload_same_exact_postgres_run(postgres_dsn: str) -> None:
    only_assert_postgres_test_database(postgres_dsn)
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    run = OnlyPostgresResearchRunSeeder(postgres_dsn).seed_queued(_queued("00000000-0000-4000-8000-000000000017"))
    script = """
import json
import os
import sys
from onlyalpha.persistence.postgres import OnlyPostgresResearchRunStore, only_assert_postgres_test_database
from onlyalpha.research.run import OnlyResearchRunId, OnlyResearchRunState
from tests.research.postgres.test_postgres_authority import _queued

dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
only_assert_postgres_test_database(dsn)
expected = _queued(sys.argv[1])
observed = OnlyPostgresResearchRunStore(dsn).load(OnlyResearchRunId(sys.argv[1]))
assert observed == expected, "Fresh reader did not recover all exact original Run facts"
assert observed.state is OnlyResearchRunState.QUEUED
print(json.dumps({"run_id": observed.run_id.value, "state": observed.state.value}, sort_keys=True))
"""
    environment = os.environ.copy()
    environment["ONLYALPHA_POSTGRES_DSN"] = postgres_dsn
    for _ in range(2):
        process = subprocess.run(
            [sys.executable, "-c", script, run.run_id.value],
            cwd=Path(__file__).parents[3],
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        output = process.stdout + process.stderr
        assert process.returncode == 0, output
        body = json.loads(process.stdout)
        assert body["run_id"] == run.run_id.value and body["state"] == "QUEUED"
        assert "postgresql://" not in output and "onlyalpha_test" not in output
