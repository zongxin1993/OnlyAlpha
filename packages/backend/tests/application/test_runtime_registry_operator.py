"""Real Infrastructure initialization only; no Generation or business workflow is seeded."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from scripts.database import _initialize_deployment
from scripts.native_http_contract import ROOT, native_executable

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture(scope="session")
def runtime_operator() -> Path:
    return native_executable(release=True)


@pytest.fixture
def runtime_namespace(runtime_operator: Path, postgres_dsn: str, tmp_path: Path) -> Path:
    subprocess.run(
        ["python", "-m", "scripts.database", "migrate"],
        env={**os.environ, "ONLYALPHA_POSTGRES_DSN": postgres_dsn},
        check=True,
        capture_output=True,
        text=True,
    )
    _initialize_deployment(postgres_dsn, tmp_path, runtime_operator)
    return tmp_path


def initialize(backend: Path, dsn: str, root: Path, *, sslmode: str = "disable") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(backend), "--initialize-fresh-runtime-registry", str(root), str(ROOT / "database/postgres/migrations")],
        env={**os.environ, "ONLYALPHA_POSTGRES_DSN": make_conninfo(dsn, sslmode=sslmode)},
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_runtime_operator_creates_only_an_empty_registry_and_releases_its_original_session(
    runtime_operator: Path, postgres_dsn: str, runtime_namespace: Path
) -> None:
    result = initialize(runtime_operator, postgres_dsn, runtime_namespace)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"schema_version": 1, "active_for_new_work": None, "states": {}}
    runtime = runtime_namespace / "runtime"
    assert {path.name for path in runtime.iterdir()} == {"generation-events.jsonl", ".generation-authority.lock"}
    assert all(path.read_bytes() == b"" and path.stat().st_mode & 0o777 == 0o600 for path in runtime.iterdir())
    assert runtime.stat().st_mode & 0o777 == 0o700
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT pg_try_advisory_xact_lock(1329199301,5)").fetchone() == (True,)
        assert connection.execute("SELECT count(*) FROM research_run").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM backtest_run").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM research_preparation").fetchone() == (0,)
    before = {path.name: path.read_bytes() for path in runtime.iterdir()}
    repeated = initialize(runtime_operator, postgres_dsn, runtime_namespace)
    assert repeated.returncode != 0 and repeated.stdout == ""
    assert {path.name: path.read_bytes() for path in runtime.iterdir()} == before


@pytest.mark.parametrize("damage", ["busy", "binding", "schema", "partial", "file", "symlink"])
def test_runtime_operator_never_repairs_or_replaces_an_unproved_deployment(
    runtime_operator: Path, postgres_dsn: str, runtime_namespace: Path, damage: str
) -> None:
    root = runtime_namespace / "runtime"
    with psycopg.connect(postgres_dsn) as connection:
        if damage == "busy":
            connection.execute("SELECT pg_advisory_lock(1329199301,5)")
        elif damage == "binding":
            connection.execute(
                "UPDATE research_deployment_semantic_store_binding SET semantic_store_id=%s",
                ("22222222-2222-4222-8222-222222222222",),
            )
            connection.commit()
        elif damage == "schema":
            connection.execute(
                "UPDATE onlyalpha_schema_migration SET checksum_sha256=%s WHERE migration_id=(SELECT min(migration_id) FROM onlyalpha_schema_migration)",
                ("0" * 64,),
            )
            connection.commit()
        elif damage == "partial":
            root.mkdir(mode=0o700)
            (root / "generation-events.jsonl").write_bytes(b"original partial history")
        elif damage == "file":
            root.write_bytes(b"original non-directory")
        else:
            target = runtime_namespace / "original-runtime"
            target.mkdir(mode=0o700)
            root.symlink_to(target, target_is_directory=True)
        before = sorted(path.name for path in runtime_namespace.iterdir())
        result = initialize(runtime_operator, postgres_dsn, runtime_namespace)
        assert result.returncode != 0 and result.stdout == ""
        assert sorted(path.name for path in runtime_namespace.iterdir()) == before
        if damage == "partial":
            assert (root / "generation-events.jsonl").read_bytes() == b"original partial history"
        elif damage == "file":
            assert root.read_bytes() == b"original non-directory"
        elif damage == "symlink":
            assert root.is_symlink() and not list(root.iterdir())
        else:
            assert not root.exists()


def test_unresolved_backtest_history_without_preparation_forbids_a_fresh_registry(
    runtime_operator: Path, postgres_dsn: str, runtime_namespace: Path
) -> None:
    # Adversarial retained bytes, not a claim of usable admission or a Product Run.
    # Even unresolvable positive history must never be reinterpreted as absence.
    run = "00000000-0000-4000-8000-000000008901"
    specification = {"schema_version": 3, "runtime_generation_fingerprint": "c" * 64}
    resolution = {"runtime_work_binding": {"work_id": run, "generation_fingerprint": "c" * 64}}

    def digest(value: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "INSERT INTO backtest_run(run_id,revision,state,specification_schema_version,specification_fingerprint,specification_payload,admission_resolution_schema_version,admission_resolution_fingerprint,admission_resolution_payload,queued_at) VALUES(%s,0,'QUEUED',3,%s,%s,2,%s,%s,'2025-01-03T12:00:00Z')",
            (run, digest(specification), Jsonb(specification), digest(resolution), Jsonb(resolution)),
        )
    result = initialize(runtime_operator, postgres_dsn, runtime_namespace)
    assert result.returncode != 0 and result.stdout == ""
    assert "RESEARCH_RUNTIME_HISTORY_UNAVAILABLE" in result.stderr
    assert not (runtime_namespace / "runtime").exists()
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_preparation").fetchone() == (0,)
        assert connection.execute(
            "SELECT specification_payload,admission_resolution_payload FROM backtest_run"
        ).fetchone() == (specification, resolution)


@pytest.mark.parametrize("sslmode", ["prefer", "require"])
def test_runtime_operator_never_downgrades_postgres_tls(
    runtime_operator: Path, postgres_dsn: str, runtime_namespace: Path, sslmode: str
) -> None:
    result = initialize(runtime_operator, postgres_dsn, runtime_namespace, sslmode=sslmode)
    assert result.returncode != 0 and result.stdout == ""
    assert "OPERATOR_POSTGRES_TRANSPORT_DENIED" in result.stderr
    assert not (runtime_namespace / "runtime").exists()


@pytest.fixture(scope="session")
def runtime_fault_binary() -> Path:
    import platform

    from scripts.rust_kernel_check import compiler_environment, prepare_cargo_home

    environment = compiler_environment(os.environ, ROOT / "test-results/rust-kernel/target")
    prepare_cargo_home(Path("/usr/local/cargo/registry"), Path(environment["CARGO_HOME"]))
    target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
    built = subprocess.run(
        [
            "cargo",
            "test",
            "-p",
            "onlyalpha-backend",
            "--test",
            "strategy_freeze_postgres",
            "--release",
            "--frozen",
            "--offline",
            "--target",
            target,
            "-j1",
            "--no-run",
            "--message-format=json",
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    binaries = {
        row["executable"]
        for line in built.stdout.splitlines()
        if (row := json.loads(line)).get("reason") == "compiler-artifact"
        and row.get("executable") is not None
        and row["target"]["name"] == "strategy_freeze_postgres"
    }
    assert len(binaries) == 1
    return Path(binaries.pop())


@pytest.mark.parametrize("phase", ["readback", "guard"])
def test_published_registry_is_preserved_after_readback_or_original_guard_failure(
    runtime_fault_binary: Path, runtime_operator: Path, postgres_dsn: str, runtime_namespace: Path, phase: str
) -> None:
    result = subprocess.run(
        [str(runtime_fault_binary), "--exact", "actual_command_boundary", "--nocapture", "--test-threads=1"],
        cwd=ROOT,
        env={
            **os.environ,
            "ONLYALPHA_POSTGRES_DSN": make_conninfo(postgres_dsn, sslmode="disable"),
            "ONLYALPHA_FREEZE_TEST_ROOT": str(runtime_namespace),
            "ONLYALPHA_FREEZE_TEST_PHASE": "runtime-initialize:" + phase,
            "ONLYALPHA_RUNTIME_INITIALIZE_TEST_SCHEMA": str(ROOT / "database/postgres/migrations"),
        },
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.stdout.count("RUNTIME_INITIALIZATION_PUBLISHED_FAULT: PASS " + phase) == 1
    runtime = runtime_namespace / "runtime"
    assert runtime.is_dir() and (runtime / "generation-events.jsonl").read_bytes() == b""
    # A second request cannot adopt the surviving namespace as another fresh operation.
    repeated = initialize(runtime_operator, postgres_dsn, runtime_namespace)
    assert repeated.returncode != 0 and repeated.stdout == ""
    assert (runtime / "generation-events.jsonl").read_bytes() == b""


@pytest.mark.parametrize(
    "history",
    [
        "old-research",
        "symbolic-admission",
        "parameter-admission",
        "factor-admission",
        "preparation-without-environment",
        "chart-operation",
        "chart-bound",
        "chart-compilation",
    ],
)
def test_fresh_registry_requires_a_deployment_without_prior_commands_or_work(
    runtime_operator: Path, postgres_dsn: str, runtime_namespace: Path, history: str
) -> None:
    # These are unresolved positive records, not usable business admission. Their
    # presence must never be decoded as proof that no Runtime side effect occurred.
    command = "00000000-0000-4000-8000-000000008903"
    reserved = "00000000-0000-4000-8000-000000008904"
    with psycopg.connect(postgres_dsn) as connection:
        if history == "old-research":
            connection.execute(
                "INSERT INTO research_run(run_id,revision,state,specification_schema_version,specification_fingerprint,specification_payload,admission_resolution_fingerprint,queued_at) VALUES(%s,0,'QUEUED',1,%s,'{}',%s,'2025-01-03T12:00:00Z')",
                (command, "a" * 64, "b" * 64),
            )
        elif history in {
            "symbolic-admission",
            "parameter-admission",
            "factor-admission",
            "preparation-without-environment",
        }:
            kind = {
                "symbolic-admission": "CREATE_SYMBOLIC_SEARCH_EXPERIMENT",
                "parameter-admission": "CREATE_PARAMETER_SEARCH_EXPERIMENT",
                "factor-admission": "SAVE_PRIVATE_FACTOR_DRAFT",
                "preparation-without-environment": "PREPARE_BACKTEST",
            }[history]
            connection.execute(
                "INSERT INTO product_command_admission(command_id,command_kind,command_fingerprint,schema_version) VALUES(%s,%s,%s,1)",
                (command, kind, "a" * 64),
            )
            if history == "preparation-without-environment":
                connection.execute(
                    "INSERT INTO product_command_receipt(command_id,command_kind,command_fingerprint,outcome_kind,outcome_id,accepted_at,schema_version) VALUES(%s,%s,%s,'RESEARCH_PREPARATION_OPERATION',%s,'2025-01-03T12:00:00Z',1)",
                    (command, kind, "a" * 64, "c" * 64),
                )
                connection.execute(
                    "INSERT INTO research_preparation(command_id,owner,accepted_fingerprint,accepted_payload,revision,state,phase,outputs_payload,detail_payload,preparation_kind) VALUES(%s,'controlled-existing-operation',%s,%s,0,'ACCEPTED','ACCEPTED','{}','null','BACKTEST_PREPARATION')",
                    (
                        command,
                        "c" * 64,
                        json.dumps(
                            {
                                "contract": "ONLYALPHA_ACCEPTED_BACKTEST_PREPARATION_V1",
                                "input": {"backtest_command_id": reserved},
                            }
                        ),
                    ),
                )
        else:
            connection.execute(
                "INSERT INTO chart_calculation_operation(operation_id,product_command_id,reserved_run_id,command_fingerprint,intent_fingerprint,intent_json,catalog_witness_json,catalog_witness_fingerprint,operation_fingerprint,accepted_at,schema_version,state,preparation_revision) VALUES(%s,%s,%s,%s,%s,'{}','{}',%s,%s,'2025-01-03T12:00:00Z',1,'ADMITTED',0)",
                (command, command, reserved, "a" * 64, "b" * 64, "c" * 64, "d" * 64),
            )
            if history == "chart-bound":
                connection.execute(
                    "INSERT INTO chart_calculation_preparation_fact(operation_id,revision,fence,kind,fact_json,fact_fingerprint) VALUES(%s,1,1,'RUNTIME_BOUND',%s,%s)",
                    (command, json.dumps({"runtime_generation_fingerprint": "c" * 64}), "e" * 64),
                )
            elif history == "chart-compilation":
                connection.execute(
                    "INSERT INTO chart_calculation_compilation(operation_id,input_preparation_revision,input_preparation_fence,input_selection_fingerprint,dataset_snapshot_fingerprint,dataset_materialization_id,runtime_generation_fingerprint,runtime_work_id,runtime_binding_event_fingerprint,catalog_witness_fingerprint,catalog_implementation_fingerprint,specification_fingerprint,result_plan_fingerprint,graph_fingerprint,calculation_fingerprint,implementation_fingerprint,compilation_json,compilation_fingerprint,schema_version) VALUES(%s,1,1,%s,%s,'retained-unresolved-materialization',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'{}',%s,1)",
                    (command, "a" * 64, "b" * 64, "c" * 64, reserved, *["d" * 64] * 9),
                )
    result = initialize(runtime_operator, postgres_dsn, runtime_namespace)
    assert result.returncode != 0 and result.stdout == ""
    assert "RUNTIME_REGISTRY_FRESH_DEPLOYMENT_REQUIRED" in result.stderr
    assert not (runtime_namespace / "runtime").exists()
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM backtest_run").fetchone() == (0,)
        if history.endswith("admission"):
            assert connection.execute("SELECT count(*) FROM product_command_receipt").fetchone() == (0,)
            assert connection.execute("SELECT command_kind FROM product_command_admission").fetchone() == (kind,)
        elif history == "preparation-without-environment":
            assert connection.execute("SELECT outputs_payload FROM research_preparation").fetchone() == ("{}",)
        elif history == "old-research":
            assert connection.execute("SELECT specification_schema_version FROM research_run").fetchone() == (1,)
        else:
            assert connection.execute("SELECT count(*) FROM research_run").fetchone() == (0,)
            assert connection.execute("SELECT count(*) FROM chart_calculation_operation").fetchone() == (1,)
