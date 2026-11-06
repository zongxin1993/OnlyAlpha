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


@pytest.fixture(scope="session")
def backtest_fault_probe() -> Path:
    # The canonical lane compiles this exact target before launching pytest.
    # The session fixture only resolves the already-built current frozen target.
    return _build_strategy_evidence_owner_binary(release=True, target_name="backtest_owner_probe")


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
        "backtest-owner:full-interval-evidence",
        "backtest-owner:pause-cancel",
        "backtest-owner:queued-cancel",
        "backtest-owner:shutdown-resume",
        "backtest-owner:running-cancel",
        "backtest-owner:crash-recover",
        "backtest-owner:lost-guard",
        "backtest-owner:cleanup-busy",
        "backtest-owner:windows",
    ],
)
def test_actual_strategy_science_producer_report_historical_reader_and_freeze(
    native_environment_case: dict[str, Any],
    market_probe: Path,
    database: Any,
    postgres_dsn: str,
    strategy_evidence_owner_binary: Path,
    tmp_path: Path,
    mode: str,
    request: pytest.FixtureRequest,
) -> None:
    from packages.backend.tests.postgres_link import wait_no_advisory_locks

    if mode.startswith("backtest-owner:"):
        native_environment_case = request.getfixturevalue("backtest_fault_environment")
        market_probe = native_environment_case["executable"]
        strategy_evidence_owner_binary = native_environment_case["executable"]

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
    submitted = probe(executable, database, "dataset-strategy-prepare", **arguments)
    assert "error" not in submitted, submitted
    assert submitted["run_id"] == run_id
    common = {
        **arguments,
        "run_id": run_id,
        "worker_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "at": "2026-11-02T00:00:00Z",
        "replay_at": "2026-11-02T00:00:10Z",
    }
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
    else:
        # This technical operation performs two complete observations before
        # concurrent publication. Give each the ordinary probe's 30-second
        # budget; production RPC deadlines and the original lease are unchanged.
        executed = probe(
            executable, database, "strategy-evidence-phase", process_timeout=2 * 30, **common, evidence_phase="execute"
        )
        assert executed.get("semantic_replay") is True and executed.get("concurrent_publication") is True, executed
    assert "error" not in executed and executed["state"] == "COMPLETED", executed
    wait_no_advisory_locks(postgres_dsn, executed["backend_pid"])
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
    freeze_request = {**common, "freeze_command": str(uuid4())}
    frozen = owner(strategy_evidence_owner_binary, postgres_dsn, research, "freeze", freeze_request)
    assert frozen["result"] == row[1] and frozen["candidate"] == report["candidate_fingerprint"]
    assert frozen["equivalence"] == report["equivalence_evidence_fingerprints"]
    assert frozen["counts"] == [2, 2]
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
        )
    if mode == "qualification-product":
        from packages.backend.tests.application.qualification_product_owner import exercise_qualification_product

        exercise_qualification_product(strategy_evidence_owner_binary, postgres_dsn, research, common, frozen)
    assert result["research_result_fingerprint"] == report["research_result_fingerprint"]
