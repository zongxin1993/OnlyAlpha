"""Controlled market inputs through the existing Rust Source, WAL and Dataset owners."""

from __future__ import annotations

import functools
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

from packages.backend.tests.application.test_runtime_installation_postgres import (
    native_environment_case as native_environment_case,
)
from packages.backend.tests.application.test_schema_postgres import DEFAULT_MIGRATION_ROOT, migrate
from scripts.native_http_contract import native_executable
from scripts.native_web_e2e import clickhouse_namespace

ROOT = Path(__file__).resolve().parents[5]
AT = datetime(2026, 10, 22, tzinfo=UTC)
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


@dataclass(frozen=True)
class ClickHouseConfiguration:
    url: str
    database: str
    user: str
    password: str


@dataclass(frozen=True)
class MarketStorageInputs:
    config: ClickHouseConfiguration


@contextmanager
def market_database(postgres_dsn: str) -> Iterator[MarketStorageInputs]:
    backend = native_executable(release=True)
    result = migrate(backend, postgres_dsn, DEFAULT_MIGRATION_ROOT)
    assert result.returncode == 0, result.stderr
    name = "onlyalpha_test_native_market_storage_" + uuid4().hex
    config = ClickHouseConfiguration(
        os.environ["ONLYALPHA_TEST_CLICKHOUSE_URL"],
        name,
        os.environ["ONLYALPHA_TEST_CLICKHOUSE_USER"],
        os.environ["ONLYALPHA_TEST_CLICKHOUSE_PASSWORD"],
    )
    clickhouse_namespace(backend, name, initialize=True)
    try:
        yield MarketStorageInputs(config)
    finally:
        clickhouse_namespace(backend, name, initialize=False)


@pytest.fixture
def database(postgres_dsn: str) -> Iterator[MarketStorageInputs]:
    with market_database(postgres_dsn) as inputs:
        yield inputs


@functools.cache
def _build_market_probe(*, release: bool = False) -> Path:
    # A formal frozen-source process can prepare this producer before pytest's
    # scenario budget, then reuse that same build. Never reuse a persisted binary.
    from scripts.rust_kernel_check import compiler_environment, prepare_cargo_home

    target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
    output = ROOT / "test-results/rust-kernel/target"
    env = compiler_environment(os.environ, output)
    env["RUSTUP_TOOLCHAIN"] = tomllib.loads((ROOT / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    prepare_cargo_home(Path("/usr/local/cargo/registry"), Path(env["CARGO_HOME"]))
    subprocess.run(
        [
            "cargo",
            "build",
            "--frozen",
            "--offline",
            *(["--release"] if release else []),
            "--target",
            target,
            "-j1",
            "-p",
            "onlyalpha-backend",
            "--example",
            "command-postgres-probe",
        ],
        cwd=ROOT,
        env=env,
        check=True,
    )
    return output / target / ("release" if release else "debug") / "examples/command-postgres-probe"


@pytest.fixture(scope="session")
def market_probe() -> Path:
    # Ordinary DB/storage tests retain their original dev producer.
    return _build_market_probe()


def _strategy_probe_diagnostics(stderr: str | bytes | None) -> None:
    import sys

    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    # Only bounded static phase/line labels from the existing source diagnostics.
    # Never dump the request, stdout, environment, arbitrary child errors or IDs.
    for line in (stderr or "").splitlines()[-256:]:
        if re.fullmatch(
            r"\[strategy-(?:evaluation|evidence)\] (?:phase=[a-z][a-z0-9-]{0,63}|invalid line=[0-9]{1,10}|input-pin=[a-z][a-z0-9-]{0,63})",
            line,
        ):
            print(line, file=sys.stderr, flush=True)


def probe(
    binary: Path, client: MarketStorageInputs, op: str, *, process_timeout: int = 30, **values: Any
) -> dict[str, Any]:
    request = {"op": op, "at": AT.isoformat(), "database": client.config.database, "url": client.config.url, **values}
    env = dict(os.environ)
    env.update(ONLYALPHA_CLICKHOUSE_USER=client.config.user, ONLYALPHA_CLICKHOUSE_PASSWORD=client.config.password)
    try:
        result = subprocess.run(
            [str(binary)],
            input=json.dumps({"op": "market-storage", "request": request}),
            text=True,
            capture_output=True,
            timeout=process_timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as error:
        if op in {"strategy-evidence-phase", "strategy-worker-phase"}:
            _strategy_probe_diagnostics(error.stderr)
        raise
    assert result.returncode == 0, result.stderr
    parsed = cast(dict[str, Any], json.loads(result.stdout))
    if op == "strategy-evidence-phase" and "error" in parsed:
        # Preserve the exact returned error/old assertions and the same safe
        # phase surface for both ordinary errors and outer-harness timeouts.
        _strategy_probe_diagnostics(result.stderr)
    if op == "dataset-research" and "error" in parsed:
        parsed["worker_stderr"] = result.stderr
    return parsed


@pytest.fixture(scope="session")
def native_research_executor(market_probe: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Prepare the selected executable once; every Runtime still pins its bytes."""
    executable = tmp_path_factory.mktemp("native-research-executor") / "executor"
    shutil.copyfile(market_probe, executable)
    subprocess.run(["strip", "--strip-debug", str(executable)], check=True, timeout=30)
    executable.chmod(0o500)
    return executable


def strategy_preparation_case(
    native_environment_case: dict[str, Any],
    market_probe: Path,
    database: MarketStorageInputs,
    tmp_path: Path,
    fault: str = "normal",
    work_id: str = "use_test_strategy_prepare",
    runtime_root: Path | None = None,
    first_bar_start: datetime | None = None,
    manual_only: bool = False,
    fresh_runtime: bool = True,
) -> dict[str, Any]:
    from uuid import uuid4

    from packages.backend.tests.application.test_private_strategy_authoring_postgres import call as author

    # Reuse the real sealed-release producer, rather than a caller-authored
    # Runtime manifest or a value-test preparation grant.
    case = native_environment_case
    executable, release, artifact, vector = (case[k] for k in ["executable", "root", "artifact", "vector"])
    runtime = runtime_root if runtime_root is not None else tmp_path / "use_test_strategy_runtime"
    generation = None
    if not manual_only:
        try:
            result = subprocess.run(
                [str(executable)],
                input=json.dumps(
                    {
                        "op": "runtime-environment",
                        "preparation_kind": "STRATEGY",
                        "factor": vector,
                        "release_root": str(release),
                        "runtime_root": str(runtime),
                        "algorithm_artifact": artifact,
                        "fresh": fresh_runtime,
                        "bind_work": work_id,
                        "activation_command": str(uuid4()),
                        "at": "2026-11-01T01:00:00Z",
                    }
                ),
                text=True,
                capture_output=True,
                check=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as error:
            # Preserve the original deadline and expose only the probe's bounded
            # phase markers; the request and deployment environment are not logged.
            for line in (error.stderr or b"").decode("utf-8", errors="replace").splitlines():
                if line.startswith("[runtime-environment] phase="):
                    print(line, flush=True)
            raise
        environment = json.loads(result.stdout)
        assert "error" not in environment, (environment, result.stderr)
        generation = environment["manifest"]["runtime_generation_fingerprint"]
        assert environment["snapshot"]["active_for_new_work"] == generation
    saved = author(
        market_probe,
        vector["draft"]["factor_id"],
        "save",
        op="factor-authoring",
        factor_id=vector["draft"]["factor_id"],
        draft=vector["draft"],
        expected=None,
    )
    assert "error" not in saved, saved
    published = author(
        market_probe,
        vector["draft"]["factor_id"],
        "publish",
        op="factor-authoring",
        factor_id=vector["draft"]["factor_id"],
        expected=saved["result"]["draft_fingerprint"],
    )
    assert published["result"]["revision"] == vector["revision"]

    # Controlled market inputs enter through existing WAL/seal/catalog owners.
    # They are technical inputs, never claimed as real Binance observations.
    evaluating = manual_only or fault == "evaluate" or fault.startswith("eval-")
    row_count = 740 if evaluating else 28
    first_start = first_bar_start or datetime(2026, 1, 1, tzinfo=UTC)
    profile = {
        (datetime(2025, 1, 2, 11, 39, tzinfo=UTC), 740): "STRATEGY_RESEARCH_EVIDENCE_V1",
        (datetime(2025, 1, 2, 23, 40, tzinfo=UTC), 740): "MANUAL_BACKTEST_VALIDATION_V1",
        (datetime(2026, 1, 1, tzinfo=UTC), 740): "STRATEGY_PREPARATION_EVALUATION_V1",
        (datetime(2026, 1, 1, tzinfo=UTC), 28): "STRATEGY_PREPARATION_V1",
    }[(first_start, row_count)]
    retained = probe(
        executable,
        database,
        "retained-source-prerequisite",
        fixture_profile=profile,
        user_data=str(tmp_path / "source-inputs"),
        selected_backend=str(executable),
        selected_backend_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
        integration_id=str(uuid4()),
        create_command=str(uuid4()),
        publish_command=str(uuid4()),
        source_trust="/etc/ssl/certs/ca-certificates.crt",
    )
    assert "error" not in retained, retained
    segment = retained["segment"]
    assert segment["canonical_count"] == row_count
    scope = {key: segment[key] for key in SCOPE_FIELDS}
    drained = probe(executable, database, "drain", root=retained["wal_root"], ids=[segment["segment_id"]], scope=scope)
    assert "error" not in drained, drained
    composed = probe(
        executable, database, "compose", scope=scope, refs=[[segment["segment_id"], segment["content_hash"]]]
    )
    assert "error" not in composed, composed
    bars = retained["canonical_bars"]
    axis = retained["event_axis_ns"]
    assert len(bars) == len(axis) == row_count
    first_ns = axis[0]
    assert first_ns % 1_000_000_000 == 0
    first = datetime.fromtimestamp(first_ns // 1_000_000_000, UTC)
    definition = {
        "schema_version": 2,
        "dataset_type": "HISTORICAL_BAR",
        "instruments": [scope["instrument_id"]],
        "bar_semantic": scope["bar_construction"]["plan"]["target_semantic"],
        "time_range": {"start": first.isoformat(), "end": (first + timedelta(minutes=row_count)).isoformat()},
        "quality_policy": "STRICT",
        "closed_only": True,
    }
    dataset_root = tmp_path / "datasets"
    dataset_root.mkdir()

    native = subprocess.run(
        [str(executable), "--describe-native-runtime"], env={}, text=True, capture_output=True, check=True, timeout=30
    )
    descriptor = json.loads(native.stdout)
    assert descriptor["image"]["artifact"] == hashlib.sha256(executable.read_bytes()).hexdigest()
    versions = {}
    for type_id in ["onlyalpha.operator.delay", "onlyalpha.operator.rolling_mean"]:
        records = [
            item for item in descriptor["implementations"] if item["calculation_type_reference"]["type_id"] == type_id
        ]
        assert len(records) == 2 and {item["backend_kind"] for item in records} == {"RESEARCH", "TRADING"}
        references = [item["calculation_type_reference"] for item in records]
        assert references[0] == references[1] and references[0]["kind"] == "INDICATOR"
        versions[type_id] = references[0]["semantic_version"]
    instances = []
    for key, operator, source in [("delay", "delay", "bar.close"), ("mean", "rolling_mean", "bar.volume")]:
        type_id = "onlyalpha.operator." + operator
        instances.append(
            {
                "instance_key": key,
                "type_reference": {"kind": "INDICATOR", "type_id": type_id, "semantic_version": versions[type_id]},
                "parameters": {"period": {"kind": "FIXED", "value": {"type": "INTEGER", "value": 20}}},
                "published_outputs": ["value"],
                "primary_output": "value",
                "input_bindings": [{"input_name": "value", "source": source}],
            }
        )
    instances.append(
        {
            "instance_key": "momentum",
            "type_reference": {
                "kind": "FACTOR",
                "type_id": vector["revision"]["factor_id"],
                "semantic_version": vector["revision"]["semantic_version"],
            },
            "parameters": {"literal_1": {"kind": "FIXED", "value": {"type": "DECIMAL", "value": "1"}}},
            "published_outputs": ["value"],
            "primary_output": "value",
            "input_bindings": [
                {"input_name": "close", "source": "bar.close"},
                {"input_name": "volume", "source": "bar.volume"},
                {
                    "input_name": "close_lag_20",
                    "source": {"kind": "VARIABLE", "instance_key": "delay", "output_name": "value"},
                },
                {
                    "input_name": "volume_mean_20",
                    "source": {"kind": "VARIABLE", "instance_key": "mean", "output_name": "value"},
                },
            ],
        }
    )
    seed_strategy = json.loads((ROOT / "examples/private-assets/strategy/simple_momentum/strategy.json").read_text())[
        "strategy"
    ]["definition"]
    seed_strategy["calculations"] = instances
    seed_strategy["factor_revision_dependencies"] = [
        {
            "factor_id": vector["revision"]["factor_id"],
            "revision_fingerprint": vector["revision"]["revision_fingerprint"],
        }
    ]
    seed_strategy["signals"]["entry"]["operator"] = ">="
    seed_strategy["signals"]["entry"]["right"]["value"]["value"] = "0.001"
    seed_strategy["universe"] = {"kind": "SINGLE_INSTRUMENT", "instruments": [scope["instrument_id"]]}
    seed_strategy["market_input"]["bar_semantic"] = definition["bar_semantic"]
    seed_strategy["market_input"]["construction_requirement"]["recipe"] = scope["bar_construction"]["plan"][
        "resolved_recipe"
    ]
    strategy_id = "private.strategy.use_test_s" + uuid4().hex
    strategy = {
        "schema_version": 1,
        "strategy_id": strategy_id,
        "base_revision_fingerprint": None,
        "semantic_version": "1",
        "description": "Actual input proof",
        "tags": [],
        "definition": seed_strategy,
    }
    saved = author(market_probe, strategy_id, "save", draft=strategy, expected=None)
    assert "error" not in saved, saved
    revision = author(market_probe, strategy_id, "publish", expected=saved["result"]["draft_fingerprint"])["result"][
        "revision"
    ]
    context = None
    if not manual_only:
        reference = json.loads(
            (ROOT / "packages/backend/tests/application/fixtures/strategy_specification.json").read_text()
        )
        context = {
            "schema_version": 1,
            "start": (first + timedelta(minutes=20)).isoformat(),
            "end": (first + timedelta(minutes=29 if fault == "window" else row_count)).isoformat(),
            "targets": [
                {
                    "instance_key": "forward_return",
                    "type_reference": {
                        "kind": "TARGET",
                        "type_id": "onlyalpha.target.forward_return",
                        "semantic_version": "1",
                    },
                    "parameters": {"exit_offset": {"kind": "FIXED", "value": {"type": "INTEGER", "value": 5}}},
                    "published_outputs": ["target_value"],
                    "primary_output": None,
                    "input_bindings": [
                        {"input_name": "entry_price", "source": "bar.close"},
                        {"input_name": "exit_price", "source": "bar.close"},
                    ],
                }
            ],
            "statistics": [
                {
                    "variable": {"kind": "VARIABLE", "instance_key": "momentum", "output_name": "value"},
                    "target_instance_key": "forward_return",
                    "definition": reference["specification"]["statistics"][0]["definition"],
                }
            ],
            "display_metadata": {},
        }
        if evaluating:
            rank = context["statistics"][0]
            context["statistics"].append({**rank, "definition": {**rank["definition"], "method": "RANK_IC"}})
    selected = executable
    if fault == "native":
        selected = tmp_path / "different-backend-image"
        selected.write_bytes(executable.read_bytes() + b"\n# different actual loaded native image\n")
        selected.chmod(0o500)
    arguments = dict(
        id=composed["revision"]["revision_id"],
        definition=definition,
        scope=scope,
        dataset_root=str(dataset_root),
        strategy_id=strategy_id,
        strategy_revision=revision["revision_fingerprint"],
        strategy_context=context,
        strategy_fault=fault,
        strategy_evaluation=evaluating,
        runtime_root=str(runtime),
        runtime_generation=generation,
        algorithm_root=str(release / "algorithms"),
        algorithm_artifact=artifact,
    )
    return dict(
        selected=selected,
        arguments=arguments,
        vector=vector,
        revision=revision,
        strategy_id=strategy_id,
        evaluating=evaluating,
        bars=bars,
        axis_ns=axis,
    )
