"""Actual Strategy Evidence/Freeze technical chain, controlled market inputs only.

These owners run behind the existing isolated PG/CH probes. This is neither a
Shipping route nor Web business acceptance. No cfg seal/value grant is used.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from psycopg.conninfo import make_conninfo

from packages.backend.tests.application.support.native_research_market_fixture import (
    ROOT,
    _build_market_probe,
    probe,
    strategy_preparation_case,
)
from packages.backend.tests.application.support.native_research_market_fixture import (
    database as database,
)
from packages.backend.tests.application.support.native_research_market_fixture import (
    native_environment_case as native_environment_case,
)
from packages.backend.tests.application.support.native_research_market_fixture import (
    native_research_executor as native_research_executor,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.clickhouse, pytest.mark.timeout(300)]


@pytest.fixture(scope="session")
def market_probe() -> Path:
    # This module's full native Science/Backtest chain pins the actual optimized
    # example. Original copy/strip, SDK release sealing and every request stay
    # unchanged; other modules keep their ordinary dev market_probe fixture.
    return _build_market_probe(release=True)


@functools.cache
def _build_strategy_evidence_owner_binary(
    *, release: bool = False, build_timeout: int | None = 120, target_name: str = "strategy_freeze_postgres"
) -> Path:
    from scripts.rust_kernel_check import compiler_environment, prepare_cargo_home

    target = {"aarch64": "aarch64-unknown-linux-gnu", "x86_64": "x86_64-unknown-linux-gnu"}[platform.machine()]
    env = compiler_environment(os.environ, ROOT / "test-results/rust-kernel/target")
    env["RUSTUP_TOOLCHAIN"] = tomllib.loads((ROOT / "rust-toolchain.toml").read_text())["toolchain"]["channel"]
    prepare_cargo_home(Path("/usr/local/cargo/registry"), Path(env["CARGO_HOME"]))
    built = subprocess.run(
        [
            "cargo",
            "test",
            "--frozen",
            "--offline",
            *(["--release"] if release else []),
            "--target",
            target,
            "-j1",
            "-p",
            "onlyalpha-backend",
            "--test",
            target_name,
            "--no-run",
            "--message-format=json",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=build_timeout,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    binaries = [
        row["executable"]
        for line in built.stdout.splitlines()
        if line.startswith("{")
        for row in [json.loads(line)]
        if row.get("reason") == "compiler-artifact" and row["target"]["name"] == target_name and row.get("executable")
    ]
    assert len(binaries) == 1
    return Path(binaries[0])


@pytest.fixture(scope="session")
def strategy_evidence_owner_binary() -> Path:
    return _build_strategy_evidence_owner_binary(release=True)


@pytest.fixture(scope="module")
def backtest_fault_environment(tmp_path_factory: pytest.TempPathFactory, backtest_fault_probe: Path) -> dict[str, Any]:
    from packages.backend.tests.application.test_manual_backtest_validation import _release

    root = tmp_path_factory.mktemp("native-backtest-owner") / "release"
    executable, artifact, _ = _release(backtest_fault_probe, root)
    vector = json.loads((ROOT / "packages/backend/tests/application/fixtures/research_factor.json").read_text())
    return {
        "root": root,
        "runtime": root.parent / "runtime",
        "executable": executable,
        "artifact": artifact,
        "vector": vector,
        "next": 0,
    }


def owner(binary: Path, dsn: str, root: Path, phase: str, request: dict[str, Any]) -> dict[str, Any]:
    path = root.parent / "use_test_evidence_owner_request.json"
    path.write_text(json.dumps(request))
    result = subprocess.run(
        [str(binary), "--exact", "actual_command_boundary", "--nocapture"],
        cwd=ROOT,
        env={
            **os.environ,
            "ONLYALPHA_POSTGRES_DSN": dsn,
            "ONLYALPHA_FREEZE_TEST_ROOT": str(root),
            "ONLYALPHA_FREEZE_TEST_PHASE": "strategy-evidence:" + phase,
            "ONLYALPHA_STRATEGY_EVIDENCE_REQUEST": str(path),
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    values = [
        json.loads(line.removeprefix("STRATEGY_EVIDENCE_VALUE "))
        for line in result.stdout.splitlines()
        if line.startswith("STRATEGY_EVIDENCE_VALUE ")
    ]
    assert len(values) == 1
    return values[0]


def assert_run_transaction_resolved(
    dsn: str,
    phase: str,
    run_id: str,
    *,
    command_ids: tuple[str, ...] = (),
    closed_pids: tuple[int, ...] = (),
) -> None:
    """把"目标 Run 的事务已解决"归因到 Run 自身的正式锁身份，而不是整库 advisory 快照。

    正式实现的 Run 认领锁是 `research_run` 行锁（`lock_run` 用 `FOR UPDATE` /
    `FOR UPDATE SKIP LOCKED`），提交命令的事务护栏是
    `pg_advisory_xact_lock(hashtextextended(command,0))`。所以本观察只用这两个正式
    身份：NOWAIT 取得该 Run 的行锁证明没有未决事务仍持有它；逐命令 try-lock 证明命令
    护栏已随事务结束释放；原提交会话必须已不在 pg_stat_activity 中。三项都是单次有界
    观察，不是按超时猜测。同库其他 backend 的锁与本 Run 身份无关，因此不做整库断言。
    """
    with psycopg.connect(dsn, autocommit=True) as observer:
        for pid in closed_pids:
            assert observer.execute(
                "SELECT NOT EXISTS (SELECT 1 FROM pg_catalog.pg_stat_activity WHERE pid=%s)",
                (int(pid),),
            ).fetchone()[0], f"{phase}: 原提交后端会话 {pid} 仍存活，事务结果未知"
        for command_id in command_ids:
            assert observer.execute(
                "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", (str(command_id),)
            ).fetchone()[0], f"{phase}: 提交命令 {command_id} 的事务护栏仍被持有"
        try:
            observer.execute(
                "SELECT 1 FROM research_run WHERE run_id=%s::text::uuid FOR UPDATE NOWAIT",
                (str(UUID(run_id)),),
            )
        except psycopg.errors.LockNotAvailable as error:
            raise AssertionError(f"{phase}: 目标 Run 的行锁仍被未决事务持有") from error


def assert_run_guard_attribution(dsn: str, run_id: str, command_id: str) -> None:
    """两连接对照：证明上面的命令护栏观察确实按精确键判定，而不是无条件放行。

    另一会话持有不同键时目标必须判定为已释放；持有目标精确键时必须判定为仍被持有；
    释放后必须恢复为已释放。全部使用真实 PostgreSQL advisory 锁，不读文件也不造数据。
    """
    other = str(uuid4())
    holder = psycopg.connect(dsn, autocommit=True)
    try:
        assert holder.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (other,)
        ).fetchone()[0]
        assert_run_transaction_resolved(dsn, "对照：其他键被持有", run_id, command_ids=(command_id,))
        assert holder.execute(
            "SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (other,)
        ).fetchone()[0]
        assert holder.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (command_id,)
        ).fetchone()[0]
        with pytest.raises(AssertionError, match="事务护栏仍被持有"):
            assert_run_transaction_resolved(
                dsn, "对照：目标键被持有", run_id, command_ids=(command_id,)
            )
        assert holder.execute(
            "SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (command_id,)
        ).fetchone()[0]
        assert_run_transaction_resolved(dsn, "对照：目标键已释放", run_id, command_ids=(command_id,))
    finally:
        holder.rollback()
        holder.close()


def assert_run_row_lock_attribution(dsn: str, run_id: str) -> None:
    """两连接对照：另一会话真的持有该 Run 行锁时，终态观察必须判定为未解决。"""
    holder = psycopg.connect(dsn)
    observer = psycopg.connect(dsn, autocommit=True)
    try:
        assert holder.execute(
            "SELECT 1 FROM research_run WHERE run_id=%s::text::uuid FOR UPDATE",
            (str(UUID(run_id)),),
        ).fetchone() == (1,)
        assert observer.execute(
            "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))",
            (str(uuid4()),),
        ).fetchone()[0]
        with pytest.raises(AssertionError, match="行锁仍被未决事务持有"):
            assert_run_transaction_resolved(dsn, "对照：Run 行锁被持有", run_id)
        holder.rollback()
        assert_run_transaction_resolved(dsn, "对照：Run 行锁已释放", run_id)
    finally:
        holder.rollback()
        holder.close()
        observer.close()


def file_tree_digest(root: Path) -> dict[str, str]:
    """目录树的确定性指纹：相对路径 -> 内容 sha256，用于证明一段执行没有在该树内留下任何文件。"""
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def http_json(
    http: Any, method: str, path: str, body: dict[str, Any] | None, headers: dict[str, str]
) -> tuple[int, dict[str, Any]]:
    """对正式 Host 发起一次真实请求，返回实际状态码与解析后的正文。

    失败时保留生产返回的原始错误正文，测试不伪造错误码，也不得用 HTTP 断言
    代替对生产语义的观察；日志只允许落盘已脱敏的本机地址与业务字段。
    """
    from urllib.error import HTTPError
    from urllib.request import Request

    payload = None if body is None else json.dumps(body).encode()
    request = Request(
        f"http://127.0.0.1:5173{path}",
        data=payload,
        headers={"Origin": "http://127.0.0.1:5173", "Accept": "application/json", **headers},
        method=method,
    )
    try:
        with http.open(request, timeout=60) as response:
            return response.status, json.loads(response.read(1024 * 1024))
    except HTTPError as failure:
        raw = failure.read(1024 * 1024)
        try:
            return failure.code, json.loads(raw)
        except json.JSONDecodeError:
            return failure.code, {"raw": raw.decode(errors="replace")}


def formal_strategy_freeze(
    http: Any, run_id: str, candidate: str, idempotency_key: str
) -> dict[str, Any]:
    """以当前已授权 Human 会话调用唯一正式入口 POST /api/v2/strategy-freezes。

    请求体是公开契约 `StrategyFreezeInput` 的三个字段；命令身份由服务端生成，
    测试不得自带命令身份。真实 POST 之后用同一会话 GET
    /api/v2/strategy-freezes/commands/{command_id} 观察原命令，不重发 POST 制造结果。
    Idempotency-Key 在一次用例内生成一次并保留，供失败归因与幂等重放观察。
    """
    status, view = http_json(
        http,
        "POST",
        "/api/v2/strategy-freezes",
        {"research_run_id": str(run_id), "candidate_fingerprint": candidate, "comment": None},
        {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        },
    )
    observed = {"status": status, "view": view, "idempotency_key": idempotency_key}
    command_id = view.get("command_id") if isinstance(view, dict) else None
    if isinstance(command_id, str) and command_id:
        outcome_status, outcome = http_json(
            http, "GET", f"/api/v2/strategy-freezes/commands/{command_id}", None, {}
        )
        observed["outcome_status"] = outcome_status
        observed["outcome"] = outcome
    return observed


def scientific_snapshot(root: Path) -> dict[str, tuple[int, bytes]]:
    selected = [
        "calculation-results",
        "statistics-results",
        "results",
        "calculation-execution-evidence",
        "calculation-equivalence",
        "artifacts",
        "datasets",
    ]
    return {
        str(path.relative_to(root)): (path.stat().st_ino, path.read_bytes())
        for name in selected
        for path in (root / name).rglob("*")
        if path.is_file() and not any(part.startswith(".") for part in path.relative_to(root).parts)
    }


def verify_public_science(root: Path, report: dict[str, Any]) -> tuple[dict[str, Any], list[Path]]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    # These independent wire-identity checks retain the old expected formulas.
    # The later original-Run inspect also exercises the current Rust physical reader.
    def arrow_schema_payload(schema):
        fields = []
        for field in schema:
            if pa.types.is_int64(field.type):
                kind = {"kind": "INTEGER", "bit_width": 64, "signed": True}
            elif pa.types.is_boolean(field.type):
                kind = {"kind": "BOOLEAN"}
            elif pa.types.is_string(field.type):
                kind = {"kind": "STRING"}
            elif pa.types.is_decimal128(field.type):
                kind = {
                    "kind": "DECIMAL",
                    "bit_width": 128,
                    "precision": field.type.precision,
                    "scale": field.type.scale,
                }
            else:
                raise AssertionError(f"unsupported formal calculation column {field.type}")
            fields.append({"name": field.name, "data_type": kind, "nullable": field.nullable})
        return fields

    def partition_fingerprint(node, instrument, table):
        from decimal import Decimal

        rows = [
            {key: format(value, "f") if isinstance(value, Decimal) else value for key, value in row.items()}
            for row in table.to_pylist()
        ]
        header = {
            "schema_version": 1,
            "node_fingerprint": node,
            "instrument_id": instrument,
            "arrow_schema": arrow_schema_payload(table.schema),
            "row_count": len(rows),
        }
        digest = hashlib.sha256()
        for value in [header, *rows]:
            encoded = only_canonical_json(value).encode()
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return digest.hexdigest()

    def calculation_content(partitions):
        records = [
            {
                "node_fingerprint": node,
                "instrument_id": instrument,
                "row_count": count,
                "semantic_fingerprint": semantic,
                "arrow_schema": list(schema),
            }
            for node, instrument, count, semantic, schema in partitions
        ]
        records.sort(key=lambda item: (item["node_fingerprint"], item["instrument_id"]))
        return only_canonical_fingerprint({"schema_version": 1, "partitions": records})

    def read_signed(path, key, domain):
        value = json.loads(path.read_bytes())
        assert path.read_text() == only_canonical_json(value)
        identity = dict(value)
        fingerprint = identity.pop(key)
        identity["domain"] = domain
        assert only_canonical_fingerprint(identity) == fingerprint
        return value

    def required_profile(definition):
        cases = {
            "FLAT_SEQUENCE",
            "NEGATIVE_SLOPE_SEQUENCE",
            "POSITIVE_SLOPE_SEQUENCE",
            "QUANTIZATION_BOUNDARY",
            "WARMUP_AND_STEADY_STATE",
            "ZERO_BOUNDARY",
        }
        if any(port.nullable for port in definition.inputs):
            cases.add("NULLABLE_INPUT_SEMANTICS")
        if any(port.data_type.value == "BOOLEAN" for port in definition.inputs):
            cases.add("BOOLEAN_TRUTH_NULL_SEMANTICS")
        if len(definition.outputs) > 1:
            cases.add("MULTI_OUTPUT_ALIGNMENT")
        ordered = sorted(cases)
        fingerprint = only_canonical_fingerprint(
            {
                "domain": "onlyalpha.calculation.equivalence-certification-profile",
                "schema_version": 1,
                "profile_id": "ONLYALPHA_P9_CALCULATION_EQUIVALENCE_V2",
                "cases": ordered,
                "comparison_contract": "EXACT_TYPED_ORDERED_ROWS_V1",
            }
        )
        return ordered, fingerprint

    def exact_fields(value, fields):
        assert type(value) is dict and set(value) == set(fields)

    plan_fp = report["research_result_plan_fingerprint"]
    result_path = root / "results/sha256" / plan_fp[:2] / plan_fp / "manifest.json"
    result = json.loads(result_path.read_bytes())
    assert result_path.read_text() == only_canonical_json(result)
    exact_fields(
        result,
        [
            "schema_version",
            "plan",
            "research_result_plan_fingerprint",
            "dataset_snapshot_fingerprint",
            "statistics_results",
            "research_result_content_fingerprint",
            "research_result_fingerprint",
            "created_at",
            "calculation_results",
        ],
    )
    exact_fields(
        result["plan"],
        [
            "schema_version",
            "dataset_snapshot_fingerprint",
            "statistics_fingerprints",
            "calculations",
            "candidates",
            "published_series",
            "signals",
        ],
    )
    assert result["plan"]["schema_version"] == 2
    assert result["plan"]["dataset_snapshot_fingerprint"] == result["dataset_snapshot_fingerprint"]
    assert result["schema_version"] == 2
    assert only_canonical_fingerprint(result["plan"]) == plan_fp == result["research_result_plan_fingerprint"]
    result_content = only_canonical_fingerprint(
        {
            "schema_version": 2,
            "statistics_results": result["statistics_results"],
            "calculation_results": result["calculation_results"],
        }
    )
    assert result_content == result["research_result_content_fingerprint"]
    assert (
        only_canonical_fingerprint(
            {
                "schema_version": 2,
                "research_result_plan_fingerprint": plan_fp,
                "research_result_content_fingerprint": result_content,
            }
        )
        == result["research_result_fingerprint"]
    )
    assert result["research_result_fingerprint"] == report["research_result_fingerprint"]
    assert (
        not {"specification", "evaluation_subject", "native_image", "runtime_generation_fingerprint", "producer"}
        & result.keys()
    )
    assert len(result["calculation_results"]) == len(result["statistics_results"]) == 2
    all_paths: list[Path] = [result_path]
    calculations: dict[str, dict[str, Any]] = {}
    definitions: dict[str, Any] = {}
    observed = report["observation"]
    outputs = {
        row["node_fingerprint"]: row["values"] for row in [*observed["research_outputs"], *observed["target_outputs"]]
    }
    from decimal import Decimal

    def decoded(value: dict[str, Any]) -> Any:
        if value["type"] == "NULL":
            return None
        if value["type"] == "DECIMAL":
            return Decimal(value["value"])
        if value["type"] == "INTEGER":
            return int(value["value"])
        return value["value"]

    for reference in result["calculation_results"]:
        exact_fields(reference, ["calculation_fingerprint", "calculation_result_fingerprint"])
        logical = reference["calculation_fingerprint"]
        assert logical not in calculations
        leaf = root / "calculation-results/sha256" / logical[:2] / logical
        manifest = json.loads((leaf / "manifest.json").read_bytes())
        all_paths.append(leaf / "manifest.json")
        assert (leaf / "manifest.json").read_text() == only_canonical_json(manifest)
        exact_fields(
            manifest,
            [
                "schema_version",
                "calculation_fingerprint",
                "dataset_snapshot_fingerprint",
                "calculation_graph_fingerprint",
                "calculation_graph",
                "result_content_fingerprint",
                "calculation_result_fingerprint",
                "partition_count",
                "total_row_count",
                "partitions",
                "created_at",
            ],
        )
        assert manifest["schema_version"] == 1
        assert manifest["calculation_fingerprint"] == logical
        assert (
            only_canonical_fingerprint(
                {
                    "schema_version": 1,
                    "dataset_snapshot_fingerprint": manifest["dataset_snapshot_fingerprint"],
                    "calculation_graph_fingerprint": manifest["calculation_graph_fingerprint"],
                    "backend": "RESEARCH",
                }
            )
            == logical
        )
        assert manifest["calculation_result_fingerprint"] == reference["calculation_result_fingerprint"]
        assert manifest["dataset_snapshot_fingerprint"] == result["dataset_snapshot_fingerprint"]
        partitions = []
        keys = []
        for index, part in enumerate(manifest["partitions"]):
            exact_fields(
                part,
                [
                    "node_fingerprint",
                    "instrument_id",
                    "row_count",
                    "arrow_schema",
                    "semantic_fingerprint",
                    "relative_path",
                    "byte_sha256",
                ],
            )
            path = leaf / part["relative_path"]
            assert part["relative_path"] == f"data/p-{index:06d}.parquet"
            assert path.read_bytes()[:4] == path.read_bytes()[-4:] == b"PAR1"
            assert hashlib.sha256(path.read_bytes()).hexdigest() == part["byte_sha256"]
            table = pq.read_table(path)
            assert table.num_rows == part["row_count"] == 740
            assert table.schema.field(0) == pa.field("ts_event_ns", pa.int64(), nullable=False)
            assert list(arrow_schema_payload(table.schema)) == part["arrow_schema"]
            assert table.column("ts_event_ns").to_pylist() == observed["axis"]
            for name, values in outputs[part["node_fingerprint"]].items():
                assert table.column(name).to_pylist() == [decoded(value) for value in values]
            semantic = partition_fingerprint(part["node_fingerprint"], part["instrument_id"], table)
            assert semantic == part["semantic_fingerprint"]
            partitions.append(
                (
                    part["node_fingerprint"],
                    part["instrument_id"],
                    part["row_count"],
                    semantic,
                    tuple(part["arrow_schema"]),
                )
            )
            keys.append((part["node_fingerprint"], part["instrument_id"]))
            all_paths.append(path)
        assert keys == sorted(set(keys))
        from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition

        graph = OnlyCalculationGraphDefinition.from_dict(manifest["calculation_graph"])
        assert graph.fingerprint == manifest["calculation_graph_fingerprint"]
        assert sorted(node.fingerprint for node in graph.nodes) == sorted(node for node, _instrument in keys)
        definitions.update({node.fingerprint: node.definition for node in graph.nodes})
        assert len({instrument for _node, instrument in keys}) == 1
        content = calculation_content(partitions)
        assert content == manifest["result_content_fingerprint"]
        assert (
            only_canonical_fingerprint(
                {"schema_version": 1, "calculation_fingerprint": logical, "result_content_fingerprint": content}
            )
            == manifest["calculation_result_fingerprint"]
        )
        assert len(manifest["partitions"]) == manifest["partition_count"]
        assert manifest["total_row_count"] == 740 * manifest["partition_count"]
        calculations[logical] = manifest
    expected_schema = pa.schema(
        [
            pa.field("ts_event_ns", pa.int64(), nullable=False),
            pa.field("statistic_value", pa.decimal128(38, 12), nullable=True),
            pa.field("sample_count", pa.int64(), nullable=False),
            pa.field("status", pa.string(), nullable=False),
        ]
    )
    statistic_ids = set()
    for reference in result["statistics_results"]:
        exact_fields(reference, ["statistics_fingerprint", "statistics_result_fingerprint"])
        logical = reference["statistics_fingerprint"]
        assert logical not in statistic_ids
        statistic_ids.add(logical)
        leaf = root / "statistics-results/sha256" / logical[:2] / logical
        manifest = json.loads((leaf / "manifest.json").read_bytes())
        all_paths.append(leaf / "manifest.json")
        assert (leaf / "manifest.json").read_text() == only_canonical_json(manifest)
        assert manifest["schema_version"] == 1
        exact_fields(
            manifest,
            [
                "schema_version",
                "statistics_fingerprint",
                "plan",
                "feature_calculation_result_fingerprint",
                "target_calculation_result_fingerprint",
                "dataset_snapshot_fingerprint",
                "result_content_fingerprint",
                "statistics_result_fingerprint",
                "row_count",
                "arrow_schema",
                "data_byte_sha256",
                "created_at",
            ],
        )
        assert manifest["statistics_fingerprint"] == logical
        assert manifest["dataset_snapshot_fingerprint"] == result["dataset_snapshot_fingerprint"]
        assert only_canonical_fingerprint(manifest["plan"]) == logical
        assert manifest["statistics_result_fingerprint"] == reference["statistics_result_fingerprint"]
        exact_fields(manifest["plan"], ["schema_version", "feature", "target", "definition"])
        assert manifest["plan"]["schema_version"] == 1
        for role in ("feature", "target"):
            selector = manifest["plan"][role]
            exact_fields(selector, ["calculation_fingerprint", "node_fingerprint", "output_name"])
            calculation = calculations[selector["calculation_fingerprint"]]
            assert manifest[role + "_calculation_result_fingerprint"] == calculation["calculation_result_fingerprint"]
            selected_graph = OnlyCalculationGraphDefinition.from_dict(calculation["calculation_graph"])
            assert selector["node_fingerprint"] in {node.fingerprint for node in selected_graph.nodes}
            definition = definitions[selector["node_fingerprint"]]
            assert selector["output_name"] in {port.name for port in definition.outputs}

        path = leaf / "data.parquet"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["data_byte_sha256"]
        table = pq.read_table(path)
        assert table.schema == expected_schema
        assert arrow_schema_payload(table.schema) == manifest["arrow_schema"]
        rows = table.to_pylist()
        assert len(rows) == manifest["row_count"] == 740
        assert rows == next(
            item["rows"] for item in observed["statistics"] if item["statistics_fingerprint"] == logical
        )
        assert [row["ts_event_ns"] for row in rows] == observed["axis"]
        assert all(
            row["statistic_value"] is None
            and row["sample_count"] in (0, 1)
            and row["status"] == "INSUFFICIENT_OBSERVATIONS"
            for row in rows
        )
        content = only_canonical_fingerprint({"schema_version": 1, "rows": rows})
        assert content == manifest["result_content_fingerprint"]
        assert (
            only_canonical_fingerprint(
                {"schema_version": 1, "statistics_fingerprint": logical, "result_content_fingerprint": content}
            )
            == manifest["statistics_result_fingerprint"]
        )
        assert not {"confidence_interval", "bootstrap", "native_time_series"} & manifest.keys()
        all_paths.append(path)
    assert result["plan"]["statistics_fingerprints"] == sorted(statistic_ids)
    expected_calculations = [
        {"calculation_fingerprint": identity, "graph_fingerprint": manifest["calculation_graph_fingerprint"]}
        for identity, manifest in sorted(calculations.items())
    ]
    for reference in result["plan"]["calculations"]:
        exact_fields(reference, ["calculation_fingerprint", "graph_fingerprint"])
    assert result["plan"]["calculations"] == expected_calculations
    assert len(calculations) == 2
    assert statistic_ids == {item["statistics_fingerprint"] for item in observed["statistics"]}
    assert len(report["calculation_execution_evidence_fingerprints"]) == 2
    for identity in report["calculation_execution_evidence_fingerprints"]:
        path = root / "calculation-execution-evidence/sha256" / identity[:2] / identity / "manifest.json"
        execution = read_signed(path, "evidence_fingerprint", "onlyalpha.research.calculation-execution-evidence")
        exact_fields(
            execution,
            [
                "schema_version",
                "calculation_fingerprint",
                "dataset_snapshot_fingerprint",
                "calculation_graph_fingerprint",
                "calculation_result_fingerprint",
                "result_content_fingerprint",
                "research_implementation_bindings",
                "execution_contract_version",
                "evidence_fingerprint",
            ],
        )
        assert execution["schema_version"] == 1
        assert execution["execution_contract_version"] == "RESEARCH_CALCULATION_EXECUTION_V1"
        assert execution["evidence_fingerprint"] == identity
        calculation = calculations[execution["calculation_fingerprint"]]
        for field in (
            "dataset_snapshot_fingerprint",
            "calculation_graph_fingerprint",
            "calculation_result_fingerprint",
            "result_content_fingerprint",
        ):
            assert execution[field] == calculation[field]
        graph = OnlyCalculationGraphDefinition.from_dict(calculation["calculation_graph"])
        expected_bindings = []
        for node in graph.ordered_nodes:
            reference = {
                "kind": node.definition.kind.value,
                "type_id": node.definition.type_id,
                "semantic_version": node.definition.semantic_version,
            }
            prepared = report["prepared_inputs"]
            if node.definition.kind.value == "PREDICATE":
                manifests = prepared["native_implementations"]
            else:
                resolved = [
                    item
                    for item in prepared["algorithm_resolution"]["nodes"]
                    if item["definition_fingerprint"] == node.fingerprint
                ]
                assert len(resolved) == 1 and resolved[0]["definition"] == node.definition.to_dict()
                manifests = resolved[0]["implementations"]
            implementations = [
                item
                for item in manifests
                if item["backend_kind"] == "RESEARCH" and item["calculation_type_reference"] == reference
            ]
            assert len(implementations) == 1
            expected_bindings.append(
                {
                    "node_fingerprint": node.fingerprint,
                    "research_implementation_fingerprint": implementations[0]["implementation_fingerprint"],
                }
            )
        for binding in execution["research_implementation_bindings"]:
            exact_fields(binding, ["node_fingerprint", "research_implementation_fingerprint"])
        expected_bindings.sort(key=lambda binding: binding["node_fingerprint"])
        assert execution["research_implementation_bindings"] == expected_bindings
        all_paths.append(path)
    assert report["equivalence_evidence_fingerprints"] == sorted(set(report["equivalence_evidence_fingerprints"]))
    for identity in report["equivalence_evidence_fingerprints"]:
        actual = read_signed(
            root / "calculation-equivalence/evidence-v2/sha256" / identity[:2] / identity / "manifest.json",
            "evidence_fingerprint",
            "onlyalpha.calculation.equivalence-evidence",
        )
        exact_fields(
            actual,
            [
                "schema_version",
                "calculation_node_fingerprint",
                "calculation_type_reference",
                "research_implementation_fingerprint",
                "trading_implementation_fingerprint",
                "equivalence_contract_version",
                "certification_profile_id",
                "certification_profile_fingerprint",
                "corpus_fingerprint",
                "research_output_fingerprint",
                "trading_output_fingerprint",
                "comparison_fingerprint",
                "verdict",
                "evidence_fingerprint",
            ],
        )
        assert actual["schema_version"] == 2 and actual["verdict"] == "EQUIVALENT"
        assert actual["equivalence_contract_version"] == "P9_CALCULATION_EQUIVALENCE_V2"
        assert actual["evidence_fingerprint"] == identity
        definition = definitions[actual["calculation_node_fingerprint"]]
        assert actual["calculation_type_reference"] == {
            "kind": definition.kind.value,
            "type_id": definition.type_id,
            "semantic_version": definition.semantic_version,
        }
        assert actual["research_output_fingerprint"] == actual["trading_output_fingerprint"]
        assert actual["certification_profile_id"] == "ONLYALPHA_P9_CALCULATION_EQUIVALENCE_V2"
        witness = next(
            node
            for node in observed["node_profiles"]
            if node["node_fingerprint"] == actual["calculation_node_fingerprint"]
        )
        exact_fields(
            witness,
            [
                "node_fingerprint",
                "research_implementation_fingerprint",
                "trading_implementation_fingerprint",
                "cases",
                "profile_covered_cases",
            ],
        )
        required_cases, required_fingerprint = required_profile(definition)
        assert witness["profile_covered_cases"] == required_cases
        assert actual["certification_profile_fingerprint"] == required_fingerprint
        assert [case["case_id"] for case in witness["cases"]] == required_cases
        assert witness["research_implementation_fingerprint"] == actual["research_implementation_fingerprint"]
        assert witness["trading_implementation_fingerprint"] == actual["trading_implementation_fingerprint"]
        from onlyalpha.calculation.definition import only_calculation_scalar_from_dict, only_calculation_scalar_to_dict

        def typed_row(row, ports):
            exact_fields(row, [port.name for port in ports])
            for port in ports:
                value = row[port.name]
                assert only_calculation_scalar_to_dict(only_calculation_scalar_from_dict(value)) == value
                assert (value["type"] == "NULL" and port.nullable) or value["type"] == port.data_type.value

        corpus = []
        for case in witness["cases"]:
            exact_fields(case, ["case_id", "inputs", "research_outputs", "trading_outputs"])
            assert definition.warmup.minimum_observations + 2 <= len(case["inputs"]) <= 8192
            assert len(case["inputs"]) == len(case["research_outputs"]) == len(case["trading_outputs"])
            for row in case["inputs"]:
                typed_row(row, definition.inputs)
            for row in [*case["research_outputs"], *case["trading_outputs"]]:
                typed_row(row, definition.outputs)
            corpus.append(
                {
                    "case_id": case["case_id"],
                    "inputs": {port.name: [row[port.name] for row in case["inputs"]] for port in definition.inputs},
                    "bars": [],
                }
            )
        assert (
            only_canonical_fingerprint(
                {
                    "domain": "onlyalpha.calculation.equivalence-corpus",
                    "schema_version": 2,
                    "calculation_node_fingerprint": actual["calculation_node_fingerprint"],
                    "certification_profile_fingerprint": required_fingerprint,
                    "cases": corpus,
                }
            )
            == actual["corpus_fingerprint"]
        )
        comparison = {
            field: actual[field]
            for field in [
                "calculation_node_fingerprint",
                "research_implementation_fingerprint",
                "trading_implementation_fingerprint",
                "equivalence_contract_version",
                "certification_profile_fingerprint",
                "corpus_fingerprint",
                "research_output_fingerprint",
                "trading_output_fingerprint",
            ]
        }
        comparison.update(
            {
                "domain": "onlyalpha.calculation.equivalence-comparison",
                "schema_version": 2,
                "comparison": "EXACT_TYPED_ORDERED_ROWS",
            }
        )
        assert only_canonical_fingerprint(comparison) == actual["comparison_fingerprint"]
        for role in ["research", "trading"]:
            rows = []
            for case in witness["cases"]:
                assert len(case["inputs"]) == len(case[role + "_outputs"]) > 0
                assert case["research_outputs"] == case["trading_outputs"]
                rows.extend(
                    {"case_id": case["case_id"], "ordinal": ordinal, "outputs": value}
                    for ordinal, value in enumerate(case[role + "_outputs"])
                )
            assert (
                only_canonical_fingerprint(
                    {
                        "domain": "onlyalpha.calculation.equivalence-output",
                        "schema_version": 2,
                        "calculation_node_fingerprint": actual["calculation_node_fingerprint"],
                        "rows": rows,
                    }
                )
                == actual[role + "_output_fingerprint"]
            )
        all_paths.append(
            root / "calculation-equivalence/evidence-v2/sha256" / identity[:2] / identity / "manifest.json"
        )
    assert len(report["equivalence_evidence_fingerprints"]) == len(report["observation"]["node_profiles"])
    assert report["admission_evidence_fingerprint"] == only_canonical_fingerprint(
        {
            "domain": "onlyalpha.strategy.trading-admission-evidence",
            "schema_version": 1,
            "evidence_fingerprints": report["equivalence_evidence_fingerprints"],
        }
    )
    return result, all_paths


def verify_public_science_rejects_rebound_facts(root: Path, report: dict[str, Any]) -> None:
    """The independent reader must reject canonical but false retained evidence."""
    from copy import deepcopy

    def reject_changed_manifest(path: Path, field: str) -> None:
        original = path.read_bytes()
        changed = json.loads(original)
        changed[field] = "0" * 64 if changed[field] != "0" * 64 else "1" * 64
        try:
            path.write_text(only_canonical_json(changed))
            with pytest.raises(AssertionError):
                verify_public_science(root, report)
        finally:
            path.write_bytes(original)
        assert path.read_bytes() == original

    plan = report["research_result_plan_fingerprint"]
    result_path = root / "results/sha256" / plan[:2] / plan / "manifest.json"
    result = json.loads(result_path.read_bytes())
    reject_changed_manifest(result_path, "research_result_plan_fingerprint")
    for tree, refs, field in [
        ("calculation-results", "calculation_results", "calculation_fingerprint"),
        ("statistics-results", "statistics_results", "statistics_fingerprint"),
    ]:
        logical = result[refs][0][field]
        reject_changed_manifest(root / tree / "sha256" / logical[:2] / logical / "manifest.json", field)

    # Re-sign and relocate the forged document so canonical/hash/path checks all
    # pass. Only the reader's own shape or cross-fact checks may reject it.
    for tree, refs, domain, field, value in [
        (
            "calculation-execution-evidence",
            "calculation_execution_evidence_fingerprints",
            "onlyalpha.research.calculation-execution-evidence",
            "calculation_result_fingerprint",
            "0" * 64,
        ),
        (
            "calculation-equivalence/evidence-v2",
            "equivalence_evidence_fingerprints",
            "onlyalpha.calculation.equivalence-evidence",
            "unexpected_test_field",
            True,
        ),
    ]:
        original_id = report[refs][0]
        original_path = root / tree / "sha256" / original_id[:2] / original_id / "manifest.json"
        original = original_path.read_bytes()
        changed = json.loads(original)
        changed[field] = value
        identity = {key: item for key, item in changed.items() if key != "evidence_fingerprint"}
        identity["domain"] = domain
        forged_id = only_canonical_fingerprint(identity)
        assert forged_id != original_id
        changed["evidence_fingerprint"] = forged_id
        target = root / tree / "sha256" / forged_id[:2] / forged_id / "manifest.json"
        assert not target.parent.exists()
        prefix_existed = target.parent.parent.exists()
        target.parent.mkdir(parents=True)
        try:
            target.write_text(only_canonical_json(changed))
            forged_report = deepcopy(report)
            forged_report[refs] = sorted(forged_id if item == original_id else item for item in report[refs])
            with pytest.raises(AssertionError):
                verify_public_science(root, forged_report)
        finally:
            target.unlink(missing_ok=True)
            target.parent.rmdir()
            if not prefix_existed:
                target.parent.parent.rmdir()
        assert original_path.read_bytes() == original


@pytest.mark.parametrize(
    "mode",
    [
        "normal",
        "commit-crash",
        "backtest-preparation",
        "deferred-complete-guard",
        "deferred-complete-pins",
        "deferred-reconcile-guard",
        "deferred-reconcile-pins",
        "worker",
        "worker-deferred-guard",
        "qualification-product",
        "backtest-native",
        "backtest-owner:memory-completion",
        "backtest-owner:queued-cancel",
        "backtest-owner:shutdown-resume",
        "backtest-owner:attempts-exhausted",
        "backtest-owner:expiry-before-finalization",
        "backtest-owner:expiry-before-recovery-publication",
        "backtest-owner:running-cancel",
        "backtest-owner:crash-recover",
        "backtest-owner:lost-guard",
        "backtest-owner:cleanup-busy",
        "backtest-owner:windows",
        "backtest-owner:worker-exit",
        "backtest-owner:worker-exit-before-claim",
        "backtest-owner:worker-exit-during-execution",
        "backtest-owner:worker-exit-after-candidate",
        "backtest-owner:worker-exit-during-insert",
        "backtest-owner:recover-cancel",
        "backtest-owner:missing-program",
        "backtest-owner:missing-market-seal",
        "backtest-owner:missing-market-row",
    ],
)
def test_actual_strategy_science_producer_report_historical_reader_and_freeze(
    database: Any,
    postgres_dsn: str,
    tmp_path: Path,
    mode: str,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.backend.tests.application.backtest_native_host import (
        dump_stages,
        reset_stages,
        set_stage_sink,
        stage,
    )
    from packages.backend.tests.postgres_link import wait_no_advisory_locks

    # 每条业务链路一张绝对时刻表。顺序固定：先把上一链路快照写回它自己的文件，再切换
    # 到本案的追加文件，最后记 case-begin。外层整案预算把 pytest 截杀时 stdout 缓冲会丢，
    # 但已真实发生的边界仍能从 stage-timings.jsonl 逐行读出。
    reset_stages(mode)
    set_stage_sink(tmp_path / "stage-timings.jsonl")
    stage("case-begin")

    if mode.startswith("backtest-owner:"):
        native_environment_case = request.getfixturevalue("backtest_fault_environment")
        market_probe = native_environment_case["executable"]
        strategy_evidence_owner_binary = market_probe
    else:
        native_environment_case = request.getfixturevalue("native_environment_case")
        market_probe = request.getfixturevalue("market_probe")
        strategy_evidence_owner_binary = request.getfixturevalue("strategy_evidence_owner_binary")

    if mode == "backtest-native" or mode.startswith("backtest-owner:"):
        from scripts.factor_build_database import prepare

        # Match the existing contained-development transport contract and the
        # native Web harness: NoTls is permitted only with explicit Disable.
        postgres_dsn = make_conninfo(postgres_dsn, sslmode="disable")
        monkeypatch.setenv("ONLYALPHA_POSTGRES_DSN", postgres_dsn)
        monkeypatch.setenv("ONLYALPHA_FACTOR_BUILD_POSTGRES_DSN", prepare(postgres_dsn, test=True))
    finite_research = mode in {
        "backtest-owner:finite-publication",
        "backtest-owner:queued-cancel",
        "backtest-owner:running-cancel",
        "backtest-owner:shutdown-resume",
        "backtest-owner:attempts-exhausted",
        "backtest-owner:expiry-before-finalization",
        "backtest-owner:expiry-before-recovery-publication",
        "backtest-owner:crash-recover",
        "backtest-owner:lost-guard",
        "backtest-owner:worker-exit",
        "backtest-owner:worker-exit-before-claim",
        "backtest-owner:worker-exit-during-execution",
        "backtest-owner:worker-exit-after-candidate",
        "backtest-owner:worker-exit-during-insert",
        "backtest-owner:recover-cancel",
        "backtest-owner:missing-program",
        "backtest-owner:missing-market-seal",
        "backtest-owner:missing-market-row",
    }
    memory_completion = finite_research or mode == "backtest-owner:memory-completion"
    if memory_completion:
        from copy import deepcopy

        from packages.backend.tests.application.test_finite_job_completion import prepare_runtime_login

        native_environment_case = deepcopy(native_environment_case)
        reference = subprocess.run(
            [str(market_probe)],
            input=json.dumps(
                {
                    "op": "factor-reference",
                    "candidate": native_environment_case["vector"]["candidate"],
                    "factor_id": "private.factor.stage5_backtest_" + uuid4().hex,
                }
            ),
            text=True,
            capture_output=True,
            check=True,
            timeout=20,
        )
        native_environment_case["vector"] = json.loads(reference.stdout)
        prepare_runtime_login(postgres_dsn)
    command = str(uuid4())
    digest = bytearray(
        hashlib.sha256(b"ONLYALPHA_NOVELTY_GATED_RESEARCH_RUN_ID_V4\x1f" + command.encode()).digest()[:16]
    )
    digest[6], digest[8] = (digest[6] & 15) | 64, (digest[8] & 63) | 128
    run_id = str(UUID(bytes=bytes(digest)))
    semantic = tmp_path / "use_test_strategy_semantic"
    semantic.mkdir(mode=0o700)
    provisioned = None
    if mode == "backtest-native" or mode.startswith("backtest-owner:"):
        # Fresh Infrastructure must precede all factor/strategy/Research work.
        provisioned = probe(
            native_environment_case["executable"],
            database,
            "strategy-evidence-provision",
            semantic_root=str(semantic),
            backtest_infrastructure=True,
        )
        assert "error" not in provisioned, provisioned
    case = strategy_preparation_case(
        native_environment_case,
        market_probe,
        database,
        tmp_path,
        "evaluate",
        work_id=run_id,
        runtime_root=semantic / "runtime" if mode == "backtest-native" or mode.startswith("backtest-owner:") else None,
        first_bar_start=datetime(2025, 1, 2, 11, 39, tzinfo=UTC),
        fresh_runtime=mode != "backtest-native" and not mode.startswith("backtest-owner:"),
        coherent_backtest=mode == "backtest-native" or mode.startswith("backtest-owner:"),
    )
    expected_first = int(datetime(2025, 1, 2, 11, 40, tzinfo=UTC).timestamp()) * 1_000_000_000
    assert case["axis_ns"] == [expected_first + minute * 60_000_000_000 for minute in range(740)]
    executable, arguments = case["selected"], case["arguments"]
    if provisioned is None:
        provisioned = probe(executable, database, "strategy-evidence-provision", semantic_root=str(semantic))
    assert "error" not in provisioned, provisioned
    research = semantic / "research"
    arguments.update(
        dataset_root=str(research / "datasets"),
        research_root=str(research),
        semantic_root=str(semantic),
        projection_root=str(research / "experiment-memory"),
        source_roots=provisioned["source_roots"],
        research_command=command,
        strategy_evaluation=False,
        strategy_evidence=True,
    )
    if memory_completion:
        built = probe(
            executable,
            database,
            "strategy-evidence-phase",
            **arguments,
            evidence_phase="memory-build",
            build_instances=[
                {
                    "factor_id": case["vector"]["revision"]["factor_id"],
                    "revision": case["vector"]["revision"]["revision_fingerprint"],
                    "parameters": {"literal_1": "1"},
                }
            ],
        )
        assert "error" not in built, built
    # 研究提交窗口：Run 建立 + 输入准备，是「研究实际执行」之前的独立阶段。
    stage("research-submit-begin")
    submitted = probe(executable, database, "dataset-strategy-prepare", **arguments)
    assert "error" not in submitted, submitted
    assert submitted["run_id"] == run_id
    stage("research-submit-end")
    common = {
        **arguments,
        "run_id": run_id,
        "worker_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "at": "2026-11-02T00:00:00Z",
        "replay_at": "2026-11-02T00:00:10Z",
    }
    # 研究实际执行窗口：worker/execute 真实计算与统计，先于任何发布读回与 Freeze 准入。
    stage("research-execution-begin")
    if mode == "worker":
        inventory = owner(strategy_evidence_owner_binary, postgres_dsn, research, "runtime-work-inventory", common)
        binding = [run_id, submitted["prepared_inputs"]["runtime_generation_fingerprint"], "research"]
        assert inventory["read_only"] is True and inventory["bindings"].count(binding) == 1
    if mode.startswith("deferred-") or mode == "worker-deferred-guard":
        refused = probe(
            executable,
            database,
            "strategy-worker-phase" if mode == "worker-deferred-guard" else "strategy-evidence-phase",
            **common,
            evidence_phase="worker-guard" if mode == "worker-deferred-guard" else mode,
            cancel_command=str(uuid4()),
        )
        assert "error" not in refused and refused["guarded_finalization_refused"] is True, refused
        wait_no_advisory_locks(postgres_dsn, refused["backend_pid"])
        with psycopg.connect(postgres_dsn) as db:
            assert db.execute(
                "SELECT state,research_result_fingerprint,artifact_content_fingerprint FROM research_run WHERE run_id=%s",
                (run_id,),
            ).fetchone() == (refused["expected_state"], None, None)
            assert db.execute("SELECT state FROM research_run_attempt WHERE run_id=%s", (run_id,)).fetchall() == [
                (refused["expected_attempt"],)
            ]
            # The worker owns the initial QUEUED -> RUNNING claim as well. That
            # one committed Run revision precedes its rejected completion.
            expected_frontier = refused["history_frontier_before"] + (1 if mode == "worker-deferred-guard" else 0)
            assert db.execute("SELECT last_index FROM research_source_history_frontier WHERE singleton").fetchone() == (
                expected_frontier,
            )
            assert db.execute(
                "SELECT count(*) FROM research_source_history WHERE source_family='RESEARCH_RUN' AND source_row->>'run_id'=%s AND source_row->>'state'='COMPLETED'",
                (run_id,),
            ).fetchone() == (0,)
            assert db.execute(
                "SELECT count(*) FROM product_command_receipt WHERE command_id=%s", (command,)
            ).fetchone() == (1,)
            assert db.execute("SELECT count(*) FROM strategy_freeze_command_admission").fetchone() == (0,)
        assert (research / "artifacts/research-strategy-v1/runs" / run_id / "manifest.json").is_file(), (
            "original immutable producer facts survive operational rollback"
        )
        return
    if mode == "commit-crash":
        marker = tmp_path / "use_test_after_semantic_commit.json"
        request = {
            "op": "strategy-evidence-phase",
            "database": database.config.database,
            "url": database.config.url,
            **common,
            "evidence_phase": "commit-crash",
            "crash_marker": str(marker),
        }
        crashed = subprocess.run(
            [str(executable)],
            input=json.dumps({"op": "market-storage", "request": request}),
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "ONLYALPHA_CLICKHOUSE_USER": database.config.user,
                "ONLYALPHA_CLICKHOUSE_PASSWORD": database.config.password,
            },
            timeout=120,
        )
        assert crashed.returncode == 86, crashed.stdout + crashed.stderr
        prior = json.loads(marker.read_text())
        wait_no_advisory_locks(postgres_dsn, prior["backend_pid"])
        with psycopg.connect(postgres_dsn) as db:
            assert db.execute(
                "SELECT state,research_result_fingerprint,artifact_content_fingerprint FROM research_run WHERE run_id=%s",
                (run_id,),
            ).fetchone() == ("RUNNING", None, None)
            # Deterministic lease boundary in the disposable namespace; no sleep.
            db.execute(
                "UPDATE research_run_attempt SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE run_id=%s AND state='ACTIVE'",
                (run_id,),
            )
        files = scientific_snapshot(research)
        # Recovery needs the complete original report, not a newly launched SDK.
        algorithm = Path(arguments["algorithm_root"])
        unavailable = algorithm.with_name("use_test_algorithm_unavailable")
        algorithm.rename(unavailable)
        try:
            executed = probe(
                executable,
                database,
                "strategy-evidence-phase",
                **{**common, "attempt_id": str(uuid4()), "evidence_phase": "recover"},
            )
        finally:
            unavailable.rename(algorithm)
        assert executed["recovered_without_evaluation"] is True
        assert scientific_snapshot(research) == files
    elif mode == "worker":
        executed = probe(executable, database, "strategy-worker-phase", **common, evidence_phase="worker")
        assert executed.get("actual_worker") is True, executed
    elif finite_research:
        # The Run created by this case's own submitted command stays QUEUED until the
        # actual finite worker publication path publishes it through the publisher role
        # inside its own transaction. The legacy file-completion owner is removed for
        # this mode before the worker is invoked, so no file completion can be reached.
        with psycopg.connect(postgres_dsn) as db:
            assert db.execute("SELECT state FROM research_run WHERE run_id=%s", (run_id,)).fetchone() == ("QUEUED",)
        # The submitting probe process already exited. This Run's advisory locks live in
        # this test database only, so one bounded observation of that namespace proves
        # there is neither another live backend nor a Run lock before the worker claims it.
        assert_run_transaction_resolved(
            postgres_dsn, "有限 worker 认领前", run_id, command_ids=(command,)
        )
        owner_request = semantic / "research-owner-request.json"
        owner_request.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "mode": "complete",
                    "database": database.config.database,
                    "url": database.config.url,
                    "at": datetime.now(UTC).isoformat(),
                    "runtime_root": str(semantic / "runtime"),
                    "algorithm_root": arguments["algorithm_root"],
                    "research_root": str(semantic / "research"),
                }
            )
        )
        # 认领前的 results 树快照：closed-cuts 源切账本与 .source-cut.lock 等既有产物
        # 都在此记录，worker 之后必须逐字节不变，任何本 Run 的文件结果都会显形。
        results_before = file_tree_digest(research / "results")
        legacy_results = research / "results"
        unavailable_results = research / "use_test_results_unavailable"
        renamed = legacy_results.exists()
        if renamed:
            legacy_results.rename(unavailable_results)
        try:
            worker = subprocess.run(
                [str(executable), "--exact", "actual_command_boundary", "--nocapture"],
                env={
                    **os.environ,
                    "ONLYALPHA_POSTGRES_DSN": postgres_dsn,
                    "ONLYALPHA_FREEZE_TEST_ROOT": str(semantic),
                    "ONLYALPHA_FREEZE_TEST_PHASE": "research-owner:complete",
                    "ONLYALPHA_RESEARCH_OWNER_REQUEST": str(owner_request),
                    "ONLYALPHA_CLICKHOUSE_USER": database.config.user,
                    "ONLYALPHA_CLICKHOUSE_PASSWORD": database.config.password,
                },
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert not legacy_results.exists(), "the scheduler must not recreate a retired result owner"
        finally:
            if renamed:
                unavailable_results.rename(legacy_results)
        worker_log = worker.stdout + worker.stderr
        (tmp_path / "research-worker.log").write_text(worker_log)
        assert worker.returncode == 0, worker_log
        values = [
            json.loads(line.removeprefix("RESEARCH_WORKER_VALUE "))
            for line in worker.stdout.splitlines()
            if line.startswith("RESEARCH_WORKER_VALUE ")
        ]
        assert len(values) == 1, worker_log
        owner_value = values[0]
        assert owner_value["state"] == "COMPLETED", owner_value
        assert owner_value["run_id"] == run_id and owner_value["members"] == 5, owner_value
        assert owner_value["report_reads"] == 2 and owner_value["execution_count"] == 1, owner_value
        with psycopg.connect(postgres_dsn) as db:
            # 方案A 身份收敛：worker 报出的 publication 是发布身份，落库到 artifact_content_fingerprint；
            # research_result_fingerprint 是生产方在同一成员表示上由科学域公式推导的科学结果身份，
            # 与文件证据轨道同一定义，两者相互独立（Constitution §4.1）。
            state, result_column, artifact_column = db.execute(
                "SELECT state,research_result_fingerprint,artifact_content_fingerprint FROM research_run WHERE run_id=%s",
                (run_id,),
            ).fetchone()
            assert state == "COMPLETED" and artifact_column == owner_value["publication"], (
                run_id, state, artifact_column, owner_value,
            )
            assert result_column != artifact_column and all(
                len(value) == 64 and value == value.lower() and all(ch in "0123456789abcdef" for ch in value)
                for value in (result_column, artifact_column)
            ), (result_column, artifact_column)
            assert db.execute(
                "SELECT state,attempt_number FROM research_run_attempt WHERE run_id=%s ORDER BY attempt_number",
                (run_id,),
            ).fetchall() == [("SUCCEEDED", 1)]
            assert db.execute(
                "SELECT count(*) FROM job_result_member WHERE job_kind='RESEARCH' AND run_id=%s",
                (run_id,),
            ).fetchone() == (5,)
        # 有限 worker 进程已以 0 退出，它自己的 backend 会话随之结束；此处只用 Run 自身的
        # 正式锁身份做有界观察：提交命令的 xact 护栏可重新取得，说明该事务已解决（结合上面
        # 已断言的 COMPLETED 终态与恰好一次发布，可判定为提交而非中止）；Run 行锁可 NOWAIT
        # 取得，说明没有任何未决事务仍持有该 Run。随后两组两连接对照证明这两项判定确实按
        # 精确身份生效：不同键/无持有者不误报，真实持有目标键或目标行时必须判定为未解决。
        assert_run_transaction_resolved(
            postgres_dsn, "有限 worker 发布之后", run_id, command_ids=(command,)
        )
        assert_run_guard_attribution(postgres_dsn, run_id, command)
        assert_run_row_lock_attribution(postgres_dsn, run_id)
        executed = {**owner_value}
    else:
        # This technical operation performs two complete observations before
        # concurrent publication. Give each the ordinary probe's 30-second
        # budget; production RPC deadlines and the original lease are unchanged.
        executed = probe(
            executable, database, "strategy-evidence-phase", process_timeout=2 * 30, **common, evidence_phase="execute"
        )
        assert executed.get("semantic_replay") is True and executed.get("concurrent_publication") is True, executed
    assert "error" not in executed, executed
    assert executed["state"] == "COMPLETED", executed
    stage("research-execution-end")
    stage("research-drain-begin")
    if finite_research:
        # 本模式的 owner 是已经返回的有限 worker 进程，终态复核同样只用 Run 自身的锁身份：
        # 命令护栏与 Run 行锁都必须已随事务解决而释放。
        assert_run_transaction_resolved(
            postgres_dsn, "有限 worker 终态复核", run_id, command_ids=(command,)
        )
    else:
        # Every other mode owns a still-live backend inside the probe, so the original
        # per-backend drain stays mandatory: a missing pid here is a failure, not a skip.
        wait_no_advisory_locks(postgres_dsn, executed["backend_pid"])
    stage("research-drain-end")
    if mode == "worker":
        inventory = owner(strategy_evidence_owner_binary, postgres_dsn, research, "runtime-work-inventory", common)
        assert inventory["read_only"] is True and binding not in inventory["bindings"], (
            "released terminal work cannot become pending or receive a new grant"
        )
    with psycopg.connect(postgres_dsn) as db:
        row = db.execute(
            "SELECT state,research_result_fingerprint,artifact_content_fingerprint,specification_fingerprint FROM research_run WHERE run_id=%s",
            (run_id,),
        ).fetchone()
        assert row[0] == "COMPLETED" and row[3] == submitted["specification_fingerprint"]
        assert db.execute(
            "SELECT count(*) FROM product_command_receipt WHERE command_id=%s", (command,)
        ).fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM research_run").fetchone() == (1,)
        assert db.execute(
            "SELECT state FROM research_run_attempt WHERE run_id=%s ORDER BY attempt_number", (run_id,)
        ).fetchall() == ([("EXPIRED",), ("SUCCEEDED",)] if mode == "commit-crash" else [("SUCCEEDED",)])
    if finite_research:
        # 有限 worker 只通过 Run 自己的正式 PG 发布交付事实：必须没有 Run 目录、文件清单
        # 与任何文件结果；发布身份、成员集合与执行证据一律取自发布表本身，
        # 冻结语义身份留给唯一生产入口 POST /api/v2/strategy-freezes 现场证明。
        run_dir = research / "artifacts/research-strategy-v1/runs" / run_id
        assert not run_dir.exists(), f"有限模式不得留下 Run 目录：{run_dir}"
        # research/results 下的 closed-cuts 是提交阶段按内容寻址的源切账本，与本 Run 的
        # 交付无关；本 Run 的文件结果 owner 已退役，因此 results 里既不能有 Run 目录，
        # 也不能出现任何以 Run ID 命名的产物，只允许 closed-cuts 这一类既有源切证据。
        results = research / "results"
        run_files = sorted(str(q.relative_to(results)) for q in results.rglob("*") if run_id in q.parts or q.name == str(run_id))
        assert run_files == [], f"有限模式不得留下本 Run 的文件结果：{run_files}"
        assert file_tree_digest(results) == results_before, (
            "有限 worker 只能在自身事务内写正式 PG 发布，results 树必须逐字节不变："
            f"{sorted(set(file_tree_digest(results)) ^ set(results_before))}"
        )
        # 发布读回窗口：正式 PG 发布、冻结绑定与成员集合，全部在同一个连接事务外读取。
        stage("research-publication-read-begin")
        with psycopg.connect(postgres_dsn) as db:
            publications = db.execute(
                "SELECT run_id::text,publication_fingerprint,binding_fingerprint,manifest_payload "
                "FROM job_publication WHERE job_kind='RESEARCH'"
            ).fetchall()
            bindings = db.execute(
                "SELECT binding_fingerprint,payload FROM job_frozen_binding "
                "WHERE job_kind='RESEARCH' AND run_id=%s",
                (run_id,),
            ).fetchall()
            members = db.execute(
                "SELECT member_key,descriptor,content_fingerprint FROM job_result_member "
                "WHERE job_kind='RESEARCH' AND run_id=%s ORDER BY member_key",
                (run_id,),
            ).fetchall()
            producer = db.execute(
                "SELECT calculation_execution_evidence_fingerprints,research_result_fingerprint,"
                "artifact_content_fingerprint FROM research_run WHERE run_id=%s",
                (run_id,),
            ).fetchone()
        assert len(publications) == 1 and publications[0][0] == run_id, publications
        assert len(bindings) == 1 and bindings[0][0] == publications[0][2], (
            "发布必须绑定提交时冻结的同一结果计划，而不是 worker 自行拟定的计划",
            bindings,
            publications,
        )
        planned = {item["key"]: item for item in json.loads(bindings[0][1])["result_plan"]["members"]}
        published = {item["key"]: item for item in json.loads(publications[0][3])["members"]}
        assert len(planned) == 5 and sorted(planned) == sorted(published) == sorted(m[0] for m in members), {
            "frozen_plan": sorted(planned),
            "publication_manifest": sorted(published),
            "materialised_members": sorted(m[0] for m in members),
        }
        for key, descriptor, content_fingerprint in members:
            # 落库成员的描述符必须逐字段等于冻结计划的成员条目，发布清单引用的内容摘要
            # 必须就是该成员的实际内容摘要；否则发布只是自报计数。
            assert json.loads(descriptor) == planned[key], (key, descriptor, planned[key])
            assert published[key]["content_fingerprint"] == content_fingerprint, (
                key,
                published[key],
                content_fingerprint,
            )
        kinds = sorted({json.loads(item[1])["kind"] for item in members})
        causal = sorted({item[2] for item in members if json.loads(item[1])["kind"] == "CAUSAL_EVIDENCE"})
        assert causal and list(producer[0]) == causal, {
            "producer_column": producer[0],
            "causal_members": causal,
            "member_kinds": kinds,
        }
        # 方案A 身份收敛：发布身份（publication_fingerprint）三处相等——Run 的 artifact 列、
        # job_publication.publication_fingerprint、worker 报出的 publication；科学结果身份独立，
        # 落库在 Run 的 research_result_fingerprint 列，由读取方在成员正文上重算核对（§4.1/§4.5）。
        assert producer[2] == row[2] == publications[0][1] == executed["publication"], (
            producer, row, publications, executed,
        )
        assert producer[1] == row[1], (producer, row)
        assert producer[1] != producer[2] and len(producer[1]) == 64, producer
        stage("research-publication-read-end")
        report = {
            "run_id": run_id,
            "specification_fingerprint": row[3],
            "scientific_specification_fingerprint": submitted["scientific_specification_fingerprint"],
            "prepared_inputs": submitted["prepared_inputs"],
            # 候选身份由策略规格决定，与发布指纹是两个独立身份；正式 Freeze 入口会自行
            # 从发布重算候选并要求一致，因此这里必须提交准入时的候选，不能拿发布指纹顶替。
            "candidate_fingerprint": submitted["candidate_fingerprint"],
            # 方案A：科学结果身份取自 Run 的 research_result_fingerprint 列（生产方在成员正文上
            # 由科学域公式推导，读取方重算核对），发布身份落在 artifact_content_fingerprint 列，两者不再混同。
            "research_result_fingerprint": producer[1],
            "artifact_content_fingerprint": producer[2],
        }
        result = {"research_result_fingerprint": producer[1]}
        evidence_paths = []
        # 冻结必须由已授权 Human 会话经正式入口在生产路径上完成，不在测试内直接调用 Freeze。
        # 这里只传 PG 侧已经证明的正式身份，供生产 Freeze 之后做语义身份交叉核对；
        # 冻结自身的语义身份必须由生产入口现场给出，不能由本用例预先写入。
        frozen = {
            "publication": {
                "run_id": run_id,
                "candidate_fingerprint": report["candidate_fingerprint"],
                "publication_fingerprint": publications[0][1],
                "research_result_fingerprint": report["research_result_fingerprint"],
                "artifact_content_fingerprint": report["artifact_content_fingerprint"],
                "execution_evidence_fingerprints": causal,
            }
        }
    else:
        # 文件泳道同一逻辑阶段：读回发布清单并做公开科学证据核验，独立可归因窗口。
        stage("research-publication-read-begin")
        report_path = research / "artifacts/research-strategy-v1/runs" / run_id / "manifest.json"
        report = json.loads(report_path.read_text())
        assert report_path.read_text() == only_canonical_json(report)
        assert report["artifact_content_fingerprint"] == row[2]
        assert report["run_id"] == run_id and report["specification_fingerprint"] == row[3]
        assert report["scientific_specification_fingerprint"] == submitted["scientific_specification_fingerprint"]
        assert report["prepared_inputs"] == submitted["prepared_inputs"]
        assert report["candidate_fingerprint"] == submitted["candidate_fingerprint"]
        assert (
            report["observation"]["producer"]["native_image"]["artifact"]
            == submitted["prepared_inputs"]["execution_binding"]["executor_artifact_sha256"]
        )
        result, evidence_paths = verify_public_science(research, report)
        if mode == "normal":
            verify_public_science_rejects_rebound_facts(research, report)
        # Different current code image and unavailable installed SDK cannot erase
        # verified historical bytes or grant the released work for execution.
        different = tmp_path / "use_test_other_current_image"
        shutil.copyfile(executable, different)
        different.write_bytes(different.read_bytes() + b"\n# different current image\n")
        different.chmod(0o500)
        algorithm = Path(arguments["algorithm_root"])
        unavailable = algorithm.with_name("use_test_historical_algorithm_unavailable")
        algorithm.rename(unavailable)
        try:
            inspected = probe(different, database, "strategy-evidence-phase", **common, evidence_phase="inspect")
        finally:
            unavailable.rename(algorithm)
        assert "error" not in inspected and inspected["report"] == report, inspected
        wait_no_advisory_locks(postgres_dsn, inspected["backend_pid"])
        missing_runtime = probe(
            different,
            database,
            "strategy-evidence-phase",
            **{**common, "runtime_root": str(tmp_path / "use_test_missing_runtime")},
            evidence_phase="inspect",
        )
        assert "error" in missing_runtime and not (tmp_path / "use_test_missing_runtime").exists()
        projection = json.loads(
            (
                research
                / "experiment-memory/revisions/sha256"
                / inspected["projection"][:2]
                / inspected["projection"]
                / "projection.json"
            ).read_text()
        )
        evaluation = [r for r in projection["records"] if r["kind"] == "EvaluationProjectionRecord"]
        assert any(
            run_id in r["facets"]["research_run_refs"]
            and submitted["scientific_specification_fingerprint"] in r["facets"]["specification_refs"]
            for r in evaluation
        )
        stage("research-publication-read-end")
        # Freeze 可见性窗口：文件泳道由 owner 走生产 Freeze 读取语义身份。
        stage("research-freeze-begin")
        freeze_request = {**common, "freeze_command": str(uuid4())}
        frozen = owner(strategy_evidence_owner_binary, postgres_dsn, research, "freeze", freeze_request)
        assert frozen["result"] == row[1] and frozen["candidate"] == report["candidate_fingerprint"]
        assert frozen["equivalence"] == report["equivalence_evidence_fingerprints"]
        assert frozen["counts"] == [2, 2]
        stage("research-freeze-end")
    if mode == "normal":
        retained = owner(
            strategy_evidence_owner_binary,
            postgres_dsn,
            research,
            "qualification-source-history",
            {
                **common,
                "freeze_command": str(uuid4()),
                "freeze_relation": frozen["freeze"]["freeze_relation_fingerprint"],
                "qualification_history_command": str(uuid4()),
            },
        )
        assert retained["qualification_source_history"] is True
        # Existing complete facts are rejected, never healed, when any retained
        # public/result/producer/V2/Dataset/Runtime physical dependency is damaged.
        generation = json.loads(
            (
                Path(arguments["runtime_root"]) / "runtime-generations" / (arguments["runtime_generation"] + ".json")
            ).read_text()
        )
        native = submitted["prepared_inputs"]["execution_binding"]["executor_artifact_sha256"]
        runtime_elf = Path(arguments["runtime_root"]) / "artifacts" / native[:2] / native / "artifact.elf"
        dataset_files = list((research / "datasets/sha256").rglob("*.parquet"))
        paths = [
            *evidence_paths,
            report_path,
            runtime_elf,
            *dataset_files,
            *list((research / "datasets/sha256").rglob("manifest.json")),
        ]
        assert dataset_files and generation["runtime_generation_fingerprint"] == arguments["runtime_generation"]
        for path in paths:
            before = path.read_bytes()
            mode_bits = path.stat().st_mode
            path.chmod(mode_bits | 0o200)
            path.write_bytes(before[:-1] + bytes([before[-1] ^ 1]))
            snapshot = scientific_snapshot(research)
            refused = probe(different, database, "strategy-evidence-phase", **common, evidence_phase="inspect")
            assert "error" in refused, (path, refused)
            assert path.read_bytes() != before and scientific_snapshot(research) == snapshot
            path.write_bytes(before)
            path.chmod(mode_bits)
        # Case witnesses cannot replace the canonical V2 owner, including when
        # the original report and its immutable content pin remain intact.
        v2 = next(path for path in evidence_paths if "calculation-equivalence" in path.parts)
        retained = v2.with_name("use_test_absent_manifest")
        v2.rename(retained)
        try:
            refused = probe(different, database, "strategy-evidence-phase", **common, evidence_phase="inspect")
            assert "error" in refused
            assert not v2.exists()
        finally:
            retained.rename(v2)
        relation = frozen["freeze"]["freeze_relation_fingerprint"]
        for path in [next(p for p in evidence_paths if p.suffix == ".parquet"), runtime_elf]:
            stale = owner(
                strategy_evidence_owner_binary,
                postgres_dsn,
                research,
                "stale-seal",
                {**common, "freeze_command": str(uuid4()), "freeze_relation": relation, "tamper_path": str(path)},
            )
            assert stale["stale_seal_refused"] is True
        # A completed original Run can never turn a missing final report into
        # an ordinary Absent result and quietly re-execute/re-publish it.
        held = report_path.with_name("use_test_absent_report")
        report_path.rename(held)
        try:
            refused = probe(different, database, "strategy-evidence-phase", **common, evidence_phase="completion-read")
            assert "error" in refused and not report_path.exists()
        finally:
            held.rename(report_path)
    if mode == "normal":
        # A fully rehashed report and matching mutable Run projection cannot
        # replace the original immutable completion occurrence in source history.
        changed = {**report, "created_at": "2026-11-02T00:00:11+00:00"}
        changed.pop("artifact_content_fingerprint")
        changed["artifact_content_fingerprint"] = only_canonical_fingerprint(changed)
        changed_bytes = only_canonical_json(changed).encode()
        original_bytes = report_path.read_bytes()
        with psycopg.connect(postgres_dsn) as db:
            original_events = db.execute(
                "SELECT count(*) FROM research_source_history WHERE source_family='RESEARCH_RUN' AND source_row->>'run_id'=%s",
                (run_id,),
            ).fetchone()[0]
            original_pin = db.execute(
                "SELECT source_row->>'artifact_content_fingerprint' FROM research_source_history WHERE source_family='RESEARCH_RUN' AND source_row->>'run_id'=%s ORDER BY event_index DESC LIMIT 1",
                (run_id,),
            ).fetchone()[0]
            assert original_pin == report["artifact_content_fingerprint"]
            db.execute("ALTER TABLE research_run DISABLE TRIGGER USER")
            db.execute(
                "UPDATE research_run SET artifact_content_fingerprint=%s WHERE run_id=%s",
                (changed["artifact_content_fingerprint"], run_id),
            )
            db.execute("ALTER TABLE research_run ENABLE TRIGGER USER")
        report_path.write_bytes(changed_bytes)
        try:
            refused = probe(different, database, "strategy-evidence-phase", **common, evidence_phase="completion-read")
            assert "error" in refused, "a matching new report hash/Run pin is no original producer binding"
            assert report_path.read_bytes() == changed_bytes
            with psycopg.connect(postgres_dsn) as db:
                assert db.execute(
                    "SELECT artifact_content_fingerprint FROM research_run WHERE run_id=%s", (run_id,)
                ).fetchone() == (changed["artifact_content_fingerprint"],)
                assert db.execute(
                    "SELECT count(*) FROM research_source_history WHERE source_family='RESEARCH_RUN' AND source_row->>'run_id'=%s",
                    (run_id,),
                ).fetchone() == (original_events,)
                assert db.execute(
                    "SELECT source_row->>'artifact_content_fingerprint' FROM research_source_history WHERE source_family='RESEARCH_RUN' AND source_row->>'run_id'=%s ORDER BY event_index DESC LIMIT 1",
                    (run_id,),
                ).fetchone() == (original_pin,)
        finally:
            report_path.write_bytes(original_bytes)
            with psycopg.connect(postgres_dsn) as db:
                db.execute("ALTER TABLE research_run DISABLE TRIGGER USER")
                db.execute(
                    "UPDATE research_run SET artifact_content_fingerprint=%s WHERE run_id=%s",
                    (report["artifact_content_fingerprint"], run_id),
                )
                db.execute("ALTER TABLE research_run ENABLE TRIGGER USER")
    if mode == "backtest-preparation":
        from packages.backend.tests.application.backtest_preparation_queue import exercise_backtest_preparation_queue

        exercise_backtest_preparation_queue(
            strategy_evidence_owner_binary, postgres_dsn, research, common, frozen, report, evidence_paths
        )
    if mode == "backtest-native" or mode.startswith("backtest-owner:"):
        from packages.backend.tests.application.backtest_native_host import exercise_native_backtest_host
        from scripts.node_database import prepare as prepare_node

        # Test setup retains the separate operator connection. The actual Host
        # receives only the approved ordinary Node login; no administrator fallback.
        monkeypatch.setenv("ONLYALPHA_HOST_POSTGRES_DSN", prepare_node(postgres_dsn, test=True))
        stage("native-dispatch-begin")
        exercise_native_backtest_host(
            strategy_evidence_owner_binary,
            postgres_dsn,
            research,
            common,
            frozen,
            case,
            market_probe,
            database,
            tmp_path / "use_test_backtest_native",
            owner_fault=mode.removeprefix("backtest-owner:") if mode.startswith("backtest-owner:") else None,
            web_assets=request.getfixturevalue("backtest_web_assets") if mode.startswith("backtest-owner:") else None,
        )
        stage("native-dispatch-end")
    if mode == "qualification-product":
        from packages.backend.tests.application.qualification_product_owner import exercise_qualification_product

        exercise_qualification_product(strategy_evidence_owner_binary, postgres_dsn, research, common, frozen)
    assert result["research_result_fingerprint"] == report["research_result_fingerprint"]
    stage("case-end")
    # 每案一份完整绝对时刻表：未到达的键保持缺失，即「未达到」而不是「耗时 0」。
    dump_stages(mode)
