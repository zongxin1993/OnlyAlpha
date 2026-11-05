"""Fresh Infrastructure only: an empty owner is no Backtest result or admission."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from packages.backend.tests.application.test_runtime_registry_operator import initialize as initialize_runtime
from packages.backend.tests.application.test_runtime_registry_operator import (
    runtime_fault_binary as runtime_fault_binary,
)
from packages.backend.tests.application.test_runtime_registry_operator import (
    runtime_namespace as runtime_namespace,
)
from packages.backend.tests.application.test_runtime_registry_operator import (
    runtime_operator as runtime_operator,
)
from scripts.native_http_contract import ROOT

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def initialize(backend: Path, dsn: str, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(backend), "--initialize-fresh-backtest-evidence", str(root), str(ROOT / "database/postgres/migrations")],
        env={**os.environ, "ONLYALPHA_POSTGRES_DSN": make_conninfo(dsn, sslmode="disable")},
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_explicit_fresh_evidence_operator_provisions_only_the_empty_owner(
    runtime_operator: Path, postgres_dsn: str, runtime_namespace: Path
) -> None:
    root = runtime_namespace / "backtest"
    assert not root.exists(), "Research deployment must not publish a partial Evidence owner"
    runtime = initialize_runtime(runtime_operator, postgres_dsn, runtime_namespace)
    assert runtime.returncode == 0, runtime.stderr
    result = initialize(runtime_operator, postgres_dsn, runtime_namespace)
    assert result.returncode == 0, result.stderr
    with psycopg.connect(postgres_dsn) as connection:
        row = connection.execute("SELECT semantic_store_id FROM research_deployment_semantic_store_binding").fetchone()
        assert row is not None
        namespace = str(row[0])
        assert connection.execute("SELECT count(*) FROM backtest_run").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM product_command_admission").fetchone() == (0,)
        assert connection.execute("SELECT pg_try_advisory_xact_lock(1329199301,5)").fetchone() == (True,)
    assert json.loads(result.stdout) == {"schema_version": 1, "semantic_store_id": namespace, "initialized": True}
    assert {path.name for path in root.iterdir()} == {"evidence"}
    evidence = root / "evidence"
    assert {path.name for path in evidence.iterdir()} == {"sha256", ".source-cut.lock"}
    assert not list((evidence / "sha256").iterdir())
    assert (evidence / ".source-cut.lock").read_bytes() == b""
    assert evidence.stat().st_mode & 0o777 == 0o700
    assert (evidence / ".source-cut.lock").stat().st_mode & 0o777 == 0o600
    repeated = initialize(runtime_operator, postgres_dsn, runtime_namespace)
    assert repeated.returncode != 0 and repeated.stdout == ""
    assert not list((evidence / "sha256").iterdir())


@pytest.mark.parametrize("damage", ["busy", "binding", "schema", "partial", "file", "symlink", "history"])
def test_evidence_operator_preserves_unproved_or_existing_state(
    runtime_operator: Path, postgres_dsn: str, runtime_namespace: Path, damage: str
) -> None:
    assert initialize_runtime(runtime_operator, postgres_dsn, runtime_namespace).returncode == 0
    root = runtime_namespace / "backtest"
    with psycopg.connect(postgres_dsn) as connection:
        if damage == "busy":
            connection.execute("SELECT pg_advisory_lock(1329199301,5)")
        elif damage == "binding":
            connection.execute(
                "UPDATE research_deployment_semantic_store_binding SET semantic_store_id='22222222-2222-4222-8222-222222222222'"
            )
            connection.commit()
        elif damage == "schema":
            connection.execute(
                "UPDATE onlyalpha_schema_migration SET checksum_sha256=%s WHERE migration_id=(SELECT min(migration_id) FROM onlyalpha_schema_migration)",
                ("0" * 64,),
            )
            connection.commit()
        elif damage == "history":
            connection.execute(
                "INSERT INTO product_command_admission(command_id,command_kind,command_fingerprint,schema_version) VALUES('00000000-0000-4000-8000-000000008905','SAVE_PRIVATE_FACTOR_DRAFT',%s,1)",
                ("a" * 64,),
            )
            connection.commit()
        elif damage == "partial":
            root.mkdir(mode=0o700)
            (root / "original").write_bytes(b"retained partial owner")
        elif damage == "file":
            root.write_bytes(b"original non-directory")
        else:
            root.symlink_to(runtime_namespace / "runtime", target_is_directory=True)
        result = initialize(runtime_operator, postgres_dsn, runtime_namespace)
        assert result.returncode != 0 and result.stdout == ""
        if damage == "partial":
            assert (root / "original").read_bytes() == b"retained partial owner"
            assert {path.name for path in root.iterdir()} == {"original"}
        elif damage == "file":
            assert root.read_bytes() == b"original non-directory"
        elif damage == "symlink":
            assert root.is_symlink()
            assert {path.name for path in root.iterdir()} == {"generation-events.jsonl", ".generation-authority.lock"}
        else:
            assert not root.exists()


@pytest.mark.parametrize("phase", ["readback", "guard"])
def test_evidence_publication_uncertainty_preserves_original_owner_and_revokes_session(
    runtime_fault_binary: Path, runtime_operator: Path, postgres_dsn: str, runtime_namespace: Path, phase: str
) -> None:
    assert initialize_runtime(runtime_operator, postgres_dsn, runtime_namespace).returncode == 0
    result = subprocess.run(
        [str(runtime_fault_binary), "--exact", "actual_command_boundary", "--nocapture", "--test-threads=1"],
        cwd=ROOT,
        env={
            **os.environ,
            "ONLYALPHA_POSTGRES_DSN": make_conninfo(postgres_dsn, sslmode="disable"),
            "ONLYALPHA_FREEZE_TEST_ROOT": str(runtime_namespace),
            "ONLYALPHA_FREEZE_TEST_PHASE": "evidence-initialize:" + phase,
            "ONLYALPHA_RUNTIME_INITIALIZE_TEST_SCHEMA": str(ROOT / "database/postgres/migrations"),
        },
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.stdout.count("BACKTEST_EVIDENCE_INITIALIZATION_PUBLISHED_FAULT: PASS " + phase) == 1
    evidence = runtime_namespace / "backtest/evidence"
    assert (evidence / ".source-cut.lock").read_bytes() == b""
    assert not list((evidence / "sha256").iterdir())
    repeated = initialize(runtime_operator, postgres_dsn, runtime_namespace)
    assert repeated.returncode != 0 and repeated.stdout == ""
    assert not list((evidence / "sha256").iterdir())
