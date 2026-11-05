"""真实原生执行环境与封存 Dataset 准入；不授予产品操作或交易权限。"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from packages.backend.tests.application.support.research_admission_reference import build, call
from packages.backend.tests.application.test_schema_postgres import migration_backend as migration_backend
from packages.backend.tests.application.test_schema_postgres import schema_db as schema_db
from scripts.native_web_e2e import clickhouse_namespace

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.clickhouse, pytest.mark.timeout(120)]
ROOT = Path(__file__).resolve().parents[4]
AT = "2026-10-29T00:00:00Z"
SCOPE_FIELDS = (
    "source_id",
    "market",
    "instrument_id",
    "data_kind",
    "start_ns",
    "end_ns",
    "data_version",
    "bar_type",
    "first_sequence",
    "last_sequence",
    "bar_construction",
)


def market_call(binary: Path, database: str, op: str, **fields: Any) -> dict[str, Any]:
    environment = {
        **os.environ,
        "ONLYALPHA_CLICKHOUSE_USER": os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_USER", "default"),
        "ONLYALPHA_CLICKHOUSE_PASSWORD": os.environ.get("ONLYALPHA_TEST_CLICKHOUSE_PASSWORD", ""),
    }
    request = {
        "op": "market-storage",
        "request": {
            "op": op,
            "at": AT,
            "database": database,
            "url": os.environ["ONLYALPHA_TEST_CLICKHOUSE_URL"],
            **fields,
        },
    }
    result = subprocess.run(
        [str(binary)],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=30,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert type(value) is dict, value
    return value


def event_iso(ns: int) -> str:
    seconds, remainder = divmod(ns, 1_000_000_000)
    assert remainder == 0
    return datetime.fromtimestamp(seconds, UTC).isoformat().replace("+00:00", "Z")


def test_native_executable_input_admission_retains_exact_runtime_and_sealed_dataset(
    native_release_probe: Path,
    migration_backend: Path,
    schema_db: str,
    tmp_path: Path,
) -> None:
    # The same final stripped image builds the exact Runtime and performs every
    # Dataset/admission call. The ordinary main executable supplies only DDL.
    factor = build(tmp_path / "runtime", native_release_probe)
    binary = Path(factor["runtime_root"]) / "native-executor"
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == factor["executor_sha256"]
    database = "onlyalpha_test_research_input_admission_" + uuid4().hex
    clickhouse_namespace(migration_backend, database, initialize=True)
    try:
        retained = market_call(
            binary,
            database,
            "retained-source-prerequisite",
            fixture_profile="RESEARCH_INPUT_ADMISSION_V1",
            user_data=str(tmp_path / "user-data"),
            selected_backend=str(binary),
            selected_backend_sha256=factor["executor_sha256"],
            integration_id=str(uuid4()),
            create_command=str(uuid4()),
            publish_command=str(uuid4()),
            source_trust="/etc/ssl/certs/ca-certificates.crt",
        )
        assert "error" not in retained, retained
        segment = retained["segment"]
        assert segment["canonical_count"] == 2
        scope = {key: segment[key] for key in SCOPE_FIELDS}
        # Wal::seal emits numeric nanoseconds; retain that native JSON type.
        assert type(scope["start_ns"]) is int
        assert type(scope["end_ns"]) is int
        assert scope["end_ns"] - scope["start_ns"] == 120_000_000_000
        drained = market_call(
            binary,
            database,
            "drain",
            root=retained["wal_root"],
            ids=[segment["segment_id"]],
            scope=scope,
        )
        assert "error" not in drained and drained["revision"] is not None, drained
        composed = market_call(
            binary,
            database,
            "compose",
            scope=scope,
            refs=[[segment["segment_id"], segment["content_hash"]]],
        )
        assert "error" not in composed and composed["revision"] is not None, composed
        definition = {
            "schema_version": 2,
            "dataset_type": "HISTORICAL_BAR",
            "instruments": [scope["instrument_id"]],
            "bar_semantic": scope["bar_construction"]["plan"]["target_semantic"],
            "time_range": {
                "start": event_iso(scope["start_ns"] + 60_000_000_000),
                "end": event_iso(scope["end_ns"] + 60_000_000_000),
            },
            "quality_policy": "STRICT",
            "closed_only": True,
        }
        dataset_root = tmp_path / "datasets"
        dataset_root.mkdir()
        args = {
            "id": composed["revision"]["revision_id"],
            "definition": definition,
            "scope": scope,
            "dataset_root": str(dataset_root),
            "factor": factor,
            "observation_start_ns": str(scope["start_ns"] + 60_000_000_000),
            "observation_end_ns": str(scope["end_ns"] + 60_000_000_000),
        }
        sealed = market_call(binary, database, "dataset-materialize", **args)
        assert "error" not in sealed, sealed
        prepared = market_call(binary, database, "dataset-admit", **args)
        assert "error" not in prepared, prepared
        assert prepared["schema_version"] == 2
        assert prepared["contract"] == "ONLYALPHA_RESEARCH_PREPARED_INPUTS_V2"
        assert prepared["runtime_generation_fingerprint"] == factor["generation"]
        assert prepared["factor_revision_fingerprint"] == factor["revision"]["revision_fingerprint"]
        assert prepared["dataset_materialization"] == sealed["lineage"]
        assert (
            prepared["dataset_materialization"]["dataset_snapshot_fingerprint"]
            == prepared["dataset_snapshot_fingerprint"]
        )
        assert market_call(binary, database, "dataset-admit", **args) == prepared
        execution = prepared["execution_binding"]
        assert execution["executor_artifact_sha256"] == factor["executor_sha256"]
        assert execution["core_execution_fingerprint"] == factor["core_execution_fingerprint"]
        backend_version = tomllib.loads((ROOT / "packages/backend/Cargo.toml").read_text())["package"]["version"]
        assert execution["executor_version"] == backend_version
        assert len(prepared["authoring_generation_fingerprint"]) == 64
        wrong_scope = copy.deepcopy(args)
        wrong_scope["scope"]["data_version"] = "foreign-version"
        assert "error" in market_call(binary, database, "dataset-admit", **wrong_scope)
        # Even a valid sealed Dataset cannot bless different archived ELF bytes.
        digest = factor["executor_sha256"]
        executable = Path(factor["runtime_root"]) / "artifacts" / digest[:2] / digest / "artifact.elf"
        original = executable.read_bytes()
        mode = stat.S_IMODE(executable.stat().st_mode)
        try:
            executable.chmod(mode | stat.S_IWUSR)
            executable.write_bytes(original + b"tamper")
            executable.chmod(mode)
            assert "error" in market_call(binary, database, "dataset-admit", **args)
        finally:
            executable.chmod(mode | stat.S_IWUSR)
            executable.write_bytes(original)
            executable.chmod(mode)
        assert market_call(binary, database, "dataset-admit", **args) == prepared
        released = call(
            binary,
            {
                "op": "runtime-work-release",
                "runtime_root": factor["runtime_root"],
                "work_id": "research-input-fixture",
                "owner": "research",
                "generation": factor["generation"],
                "at": AT,
            },
        )
        assert released["event"]["work_id"] == "research-input-fixture"
        assert "error" in market_call(binary, database, "dataset-admit", **args)
        # The independently materialized sealed Dataset remains exactly readable.
        assert market_call(binary, database, "dataset-materialize", **args) == sealed
    finally:
        clickhouse_namespace(migration_backend, database, initialize=False)
