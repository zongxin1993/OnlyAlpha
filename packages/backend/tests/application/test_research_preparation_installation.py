"""Actual native Runtime/Calculation preparation; no Human or Product acceptance."""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from onlyalpha.canonical import only_canonical_fingerprint

from packages.backend.tests.application.support.research_admission_reference import build
from packages.backend.tests.application.test_schema_postgres import migration_backend as migration_backend
from packages.backend.tests.application.test_schema_postgres import schema_db as schema_db

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.fixture
def prepared_runtime(tmp_path: Path, native_release_probe: Path, schema_db: str) -> dict[str, Any]:
    # The historical fixture contributes a candidate expression only. All current
    # source/Definition/implementation identities come from the actual Rust owner.
    candidate = json.loads((Path(__file__).parent / "fixtures/research_factor.json").read_text())["candidate"]
    runtime = tmp_path / "runtime"
    selected = build(
        runtime, native_release_probe, candidate_record=candidate, work_id="work", preparation_kind="FACTOR"
    )
    selected["executable"] = runtime / "native-executor"
    selected["release"] = Path(selected["installation"]).parent
    assert hashlib.sha256(selected["executable"].read_bytes()).hexdigest() == selected["executor_sha256"]
    proofs = list((runtime / "runtime-generation-installed-proof" / selected["generation"]).glob("*.json"))
    assert len(proofs) == 1
    selected["proof"] = json.loads(proofs[0].read_text())
    return selected


def native_call(selected: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    result = subprocess.run(
        [str(selected["executable"])], input=json.dumps(request), text=True, capture_output=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    return value


def exchange(selected: dict[str, Any], payload: dict[str, Any], action: str = "resolve") -> dict[str, Any]:
    return native_call(
        selected,
        {
            "op": "research-calculations",
            "action": action,
            "installation": selected["installation"],
            "algorithm_artifact": selected["algorithm_artifact"],
            "generation": selected["generation"],
            "request": payload,
        },
    )


def prepare_again(selected: dict[str, Any], root: Path, kind: str) -> dict[str, Any]:
    return native_call(
        selected,
        {
            "op": "runtime-environment",
            "preparation_kind": kind,
            "release_root": str(selected["release"]),
            "runtime_root": str(root),
            "factor": {key: selected[key] for key in ("candidate", "draft", "revision")},
            "algorithm_artifact": selected["algorithm_artifact"],
            "fresh": True,
            "at": "2026-10-29T00:00:00Z",
        },
    )


def wheel(selected: dict[str, Any], pattern: str) -> dict[str, Any]:
    path = next((selected["release"] / "wheels").glob(pattern))
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
        "distribution_version": path.name.split("-")[1],
    }


def rehash_release(selected: dict[str, Any], path: Path) -> None:
    manifest = selected["release"] / "manifest.json"
    record = json.loads(manifest.read_text())
    record["files"][str(path.relative_to(selected["release"]))] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(record))


def target_instance() -> dict[str, Any]:
    return {
        "instance_key": "target",
        "type_reference": {"kind": "TARGET", "type_id": "onlyalpha.target.forward_return", "semantic_version": "1"},
        "parameters": {"exit_offset": {"kind": "FIXED", "value": {"type": "INTEGER", "value": 5}}},
        "published_outputs": ["target_value"],
        "primary_output": None,
        "input_bindings": [
            {"input_name": "entry_price", "source": "bar.close"},
            {"input_name": "exit_price", "source": "bar.close"},
        ],
    }


def resolution(selected: dict[str, Any], instances: list[dict[str, Any]], *, private: bool = False) -> dict[str, Any]:
    source_keys = (
        "factor_id",
        "semantic_version",
        "revision_fingerprint",
        "source_text",
        "source_sha256",
        "factor_api_version",
        "factor_api_contract_fingerprint",
        "input_contract",
        "parameter_contract",
        "output_contract",
    )
    return {
        "schema_version": 1,
        "contract": "ONLYALPHA_CALCULATION_INSTANCES_RESOLVE_V1",
        "sources": [{key: selected["revision"][key] for key in source_keys}] if private else [],
        "instances": instances,
        "core_artifact": wheel(selected, "onlyalpha-*.whl"),
        "operator_artifact": {"sha256": selected["executor_sha256"], "distribution_version": "0.11.1"},
        "target_artifact": wheel(selected, "onlyalpha_backend_algorithms-*.whl"),
    }


def feature_instances(selected: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for key, operator, source in [("delay", "delay", "bar.close"), ("mean", "rolling_mean", "bar.volume")]:
        result.append(
            {
                "instance_key": key,
                "type_reference": {
                    "kind": "INDICATOR",
                    "type_id": f"onlyalpha.operator.{operator}",
                    "semantic_version": "2",
                },
                "parameters": {"period": {"kind": "FIXED", "value": {"type": "INTEGER", "value": 20}}},
                "published_outputs": ["value"],
                "primary_output": "value",
                "input_bindings": [{"input_name": "value", "source": source}],
            }
        )
    result.append(
        {
            "instance_key": "momentum",
            "type_reference": {"kind": "FACTOR", "type_id": selected["revision"]["factor_id"], "semantic_version": "1"},
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
    return result


def test_selected_installed_preparation_rejects_rehashed_foreign_operator_resources(
    prepared_runtime: dict[str, Any], tmp_path: Path
) -> None:
    selected = prepared_runtime
    proof = selected["proof"]
    actual = proof["algorithm_observation"]
    assert actual["contract"] == "ONLYALPHA_FACTOR_EXECUTABLE_PREPARATION_V1"
    assert actual["operator_artifact_sha256"] == selected["executor_sha256"]
    assert actual["operator_provider_manifest"]["source"] == {
        "kind": "DISTRIBUTION",
        "distribution_name": "onlyalpha-backend",
        "distribution_version": proof["native_descriptor"]["image"]["version"],
    }
    assert actual["operator_resources_fingerprint"] == only_canonical_fingerprint(
        [{"relative_path": "bin/onlyalpha-backend", "byte_sha256": selected["executor_sha256"]}]
    )
    assert proof["native_descriptor"]["image"]["artifact"] == selected["executor_sha256"]
    assert actual["source_artifact"]["source_sha256"] == selected["revision"]["source_sha256"]
    assert (
        actual["source_artifact"]["factor_api_contract_fingerprint"]
        == selected["revision"]["factor_api_contract_fingerprint"]
    )
    assert actual["equivalence_evidence"]["disposition"] == "PASS"
    assert (
        actual["equivalence_evidence"]["research_output_fingerprint"]
        == actual["equivalence_evidence"]["trading_output_fingerprint"]
    )
    assert actual["equivalence_evidence"]["test_vector_set_fingerprint"] == only_canonical_fingerprint(
        actual["certification_vectors"]
    )
    assert actual["certification_policy"] == "ONLYALPHA_PRIVATE_FACTOR_ABI_VECTORS_V1"
    assert actual["certification_vectors"]["parameters"] == {"literal_1": "1"}
    assert len(actual["certification_vectors"]["vectors"]) == 8
    assert all(row["type"]["semantic_version"] == "2" for row in actual["operator_calculations"])
    assert not list((selected["release"] / "wheels").glob("onlyalpha_plugin_operators-*.whl"))
    foreign = selected["release"] / "bin/onlyalpha-backend"
    raw = bytearray(foreign.read_bytes())
    raw[15] ^= 1  # ELF padding preserves the envelope; the selected bytes changed.
    foreign.chmod(0o700)
    foreign.write_bytes(raw)
    foreign.chmod(0o500)
    rehash_release(selected, foreign)
    assert hashlib.sha256(foreign.read_bytes()).hexdigest() != selected["executor_sha256"]
    root = tmp_path / "foreign-runtime"
    denied = prepare_again(selected, root, "FACTOR")
    assert "error" in denied and "OUTCOME_UNKNOWN" not in denied["error"], denied
    assert not root.exists(), "foreign image must fail before publishing Runtime authority"


def test_installed_calculation_resolution_uses_exact_target_and_operator_resources(
    prepared_runtime: dict[str, Any],
) -> None:
    selected = prepared_runtime
    request = resolution(selected, [target_instance()])
    actual = exchange(selected, request)
    assert "error" not in actual, actual
    assert actual["contract"] == request["contract"] and actual["source_artifacts"] == []
    assert actual["nodes"][0]["definition"]["type_id"] == "onlyalpha.target.forward_return"
    assert actual["target_artifact_sha256"] == request["target_artifact"]["sha256"]
    assert actual["operator_artifact_sha256"] == selected["executor_sha256"]
    assert actual["isolation"] == "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
    assert "equivalence_evidence" not in actual and "runtime_generation_fingerprint" not in actual
    observed = exchange(
        selected,
        {
            "contract": "ONLYALPHA_CALCULATION_PLANES_OBSERVATION_V1",
            "resolution": request,
            "rows": [{"at_ns": i * 60_000_000_000, "values": {"close": str(10 + i)}} for i in range(8)],
        },
        "evaluate",
    )
    assert "error" not in observed, observed
    evaluation = observed["evaluation"]
    assert evaluation["targets"]["outputs"][0]["values"]["target_value"] == [
        "0.500000000000",
        "0.454545454545",
        "0.416666666667",
        None,
        None,
        None,
        None,
        None,
    ]
    assert evaluation["feature"] is None and evaluation["trading_capabilities"] == []
    for name in ("core_artifact", "operator_artifact", "target_artifact"):
        changed = json.loads(json.dumps(request))
        changed[name]["sha256"] = "f" * 64
        assert exchange(selected, changed) == {"error": "RESEARCH_ALGORITHM_UNAVAILABLE"}


def test_installed_strategy_preparation_retains_actual_target_capabilities_and_refuses_foreign_bytes(
    prepared_runtime: dict[str, Any], tmp_path: Path
) -> None:
    selected = prepared_runtime
    legacy = selected["proof"]["algorithm_observation"]
    assert legacy["contract"] == "ONLYALPHA_FACTOR_EXECUTABLE_PREPARATION_V1"
    assert "target_calculations" not in legacy and "target_artifact_sha256" not in legacy
    prepared = prepare_again(selected, tmp_path / "strategy-runtime", "STRATEGY")
    assert "error" not in prepared, prepared
    actual = prepared["proof"]["algorithm_observation"]
    assert actual["contract"] == "ONLYALPHA_STRATEGY_EXECUTABLE_PREPARATION_V1"
    assert actual["target_artifact_sha256"] == wheel(selected, "onlyalpha_backend_algorithms-*.whl")["sha256"]
    assert len(actual["target_resources_fingerprint"]) == 64
    capabilities = actual["target_calculations"]
    assert capabilities and all(
        row["type"]["kind"] == "TARGET" and row["backend"] == "RESEARCH" for row in capabilities
    )
    assert all(row["state_capability"] is None and row["checkpoint_schema_version"] is None for row in capabilities)
    assert "target_provider_manifest" not in actual and "runtime_generation_fingerprint" not in actual
    assert prepared["snapshot"]["active_for_new_work"] is None
    assert actual["isolation"] == "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
    resolved = exchange(selected, resolution(selected, [target_instance()]))
    manifest = resolved["nodes"][0]["implementations"][0]
    assert any(row["implementation_fingerprint"] == manifest["implementation_fingerprint"] for row in capabilities)
    for key, value in legacy.items():
        if key != "contract":
            assert actual[key] == value, key
    original = wheel(selected, "onlyalpha_backend_algorithms-*.whl")
    for change in ({"distribution_version": "missing"}, {"sha256": "f" * 64}):
        request = resolution(selected, [target_instance()])
        request["target_artifact"] = {**original, **change}
        assert exchange(selected, request) == {"error": "RESEARCH_ALGORITHM_UNAVAILABLE"}
    target = Path(original["path"])
    foreign = target.with_suffix(".foreign")
    with zipfile.ZipFile(target) as source, zipfile.ZipFile(foreign, "w") as output:
        for name in source.namelist():
            raw = source.read(name)
            output.writestr(name, raw + b"\n# foreign resource\n" if name.endswith("/registration.py") else raw)
    target.write_bytes(foreign.read_bytes())
    foreign.unlink()
    rehash_release(selected, target)
    root = tmp_path / "foreign-target-runtime"
    denied = prepare_again(selected, root, "STRATEGY")
    assert "error" in denied and "OUTCOME_UNKNOWN" not in denied["error"], denied
    assert not root.exists()


def _actual_node_profile_request(selected: dict[str, Any]) -> dict[str, Any]:
    """Profile actual Rust/SDK-resolved Definitions; no upgraded historical wire."""
    request = resolution(selected, feature_instances(selected), private=True)
    actual = exchange(selected, request)
    assert "error" not in actual, actual
    nodes = []
    for resolved in actual["nodes"]:
        definition = resolved["definition"]
        period = int(definition["parameters"].get("period", {}).get("value", 0))
        count = max(definition["warmup"]["minimum_observations"], period + 1) + 22
        quantum = Decimal(definition["numeric"]["output_quantum"])
        cases = []
        for name in (
            "FLAT_SEQUENCE",
            "NEGATIVE_SLOPE_SEQUENCE",
            "POSITIVE_SLOPE_SEQUENCE",
            "QUANTIZATION_BOUNDARY",
            "WARMUP_AND_STEADY_STATE",
            "ZERO_BOUNDARY",
            "NULLABLE_INPUT_SEMANTICS",
        ):
            rows = []
            for index in range(count):
                value = {
                    "FLAT_SEQUENCE": Decimal(100),
                    "NEGATIVE_SLOPE_SEQUENCE": Decimal(100 - index),
                    "POSITIVE_SLOPE_SEQUENCE": Decimal(100 + index),
                    "WARMUP_AND_STEADY_STATE": Decimal(10 + index % 5),
                    "ZERO_BOUNDARY": Decimal(0),
                    "NULLABLE_INPUT_SEMANTICS": Decimal(2),
                    "QUANTIZATION_BOUNDARY": quantum * Decimal("0.5" if index % 2 == 0 else "1.5"),
                }[name]
                row = {port["name"]: {"type": "DECIMAL", "value": format(value, "f")} for port in definition["inputs"]}
                nullable = [port["name"] for port in definition["inputs"] if port["nullable"]]
                if name == "NULLABLE_INPUT_SEMANTICS" and index < len(nullable):
                    row[nullable[index]] = {"type": "NULL", "value": None}
                rows.append(row)
            if definition["kind"] == "FACTOR" and name == "QUANTIZATION_BOUNDARY":
                for index, row in enumerate(rows):
                    for port in definition["inputs"]:
                        row[port["name"]] = {"type": "DECIMAL", "value": "1"}
                    row["close"] = {
                        "type": "DECIMAL",
                        "value": format(Decimal(1) + quantum * Decimal("0.5" if index % 2 == 0 else "1.5"), "f"),
                    }
            cases.append({"case_id": name, "inputs": rows})
        nodes.append({"definition": definition, "cases": cases})
    return {
        "schema_version": 1,
        "contract": "ONLYALPHA_CALCULATION_NODE_PROFILE_OBSERVATION_V1",
        "resolution": request,
        "nodes": nodes,
    }


def test_installed_node_profiles_observe_exact_factories_and_typed_nulls(prepared_runtime: dict[str, Any]) -> None:
    request = _actual_node_profile_request(prepared_runtime)
    actual = exchange(prepared_runtime, request, "evaluate")
    assert "error" not in actual, actual
    assert actual["isolation"] == "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
    observed = actual["evaluation"]
    assert set(observed) == {"schema_version", "contract", "nodes"}
    assert observed["schema_version"] == 1 and observed["contract"] == request["contract"]
    # Associate profiles with the actual Rust resolver Definition identities.
    resolved = exchange(prepared_runtime, request["resolution"])
    expected = {
        row["definition_fingerprint"]: next(n for n in request["nodes"] if n["definition"] == row["definition"])
        for row in resolved["nodes"]
    }
    assert len(expected) == 3
    values = {row["node_fingerprint"]: row for row in observed["nodes"]}
    assert len(values) == len(observed["nodes"]) == len(expected) and values.keys() == expected.keys()
    implementations = {row["definition_fingerprint"]: row["implementations"] for row in actual["nodes"]}
    total = 0
    for key, node in values.items():
        assert set(node) == {
            "node_fingerprint",
            "research_implementation_fingerprint",
            "trading_implementation_fingerprint",
            "cases",
        }
        for backend, field in (
            ("RESEARCH", "research_implementation_fingerprint"),
            ("TRADING", "trading_implementation_fingerprint"),
        ):
            selected = [m for m in implementations[key] if m["backend_kind"] == backend]
            assert len(selected) == 1 and node[field] == selected[0]["implementation_fingerprint"]
        planned = {row["case_id"]: row for row in expected[key]["cases"]}
        cases = {row["case_id"]: row for row in node["cases"]}
        assert len(cases) == len(node["cases"]) == len(planned) == 7 and cases.keys() == planned.keys()
        for case_id, case in cases.items():
            assert set(case) == {"case_id", "inputs", "research_outputs", "trading_outputs"}
            assert case["inputs"] == planned[case_id]["inputs"]
            assert case["research_outputs"] == case["trading_outputs"]
            assert len(case["research_outputs"]) == len(case["inputs"])
            total += len(case["inputs"])
            for row in case["research_outputs"]:
                assert set(row) == {port["name"] for port in expected[key]["definition"]["outputs"]}
                assert all(
                    set(value) == {"type", "value"} and value["type"] in {"DECIMAL", "NULL"} for value in row.values()
                )
        nullable = cases["NULLABLE_INPUT_SEMANTICS"]["inputs"]
        for port in expected[key]["definition"]["inputs"]:
            if port["nullable"]:
                assert any(row[port["name"]] == {"type": "NULL", "value": None} for row in nullable)
        definition = expected[key]["definition"]
        if definition["type_id"] == "onlyalpha.operator.delay":
            count = definition["parameters"]["period"]["value"]
            flat = cases["FLAT_SEQUENCE"]["research_outputs"]
            assert [row["value"] for row in flat[:count]] == [{"type": "NULL", "value": None}] * count
            assert flat[count]["value"]["type"] == "DECIMAL" and Decimal(flat[count]["value"]["value"]) == Decimal(100)
        if definition["kind"] == "FACTOR":
            assert all(
                row["value"] == {"type": "NULL", "value": None} for row in cases["ZERO_BOUNDARY"]["research_outputs"]
            )
            boundary = cases["QUANTIZATION_BOUNDARY"]["research_outputs"]
            assert boundary[0]["value"]["type"] == boundary[1]["value"]["type"] == "DECIMAL"
            assert Decimal(boundary[0]["value"]["value"]) == Decimal(0)
            assert Decimal(boundary[1]["value"]["value"]) == Decimal("0.000000000002")
    assert total <= 8192
    forbidden = {"binding", "receipt", "cursor", "strategy_state", "grant", "permission", "equivalence_evidence"}

    def check(value: object) -> None:
        if isinstance(value, dict):
            assert not forbidden & value.keys()
            for item in value.values():
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    check(observed)


def test_installed_node_profiles_reject_foreign_definitions_scalars_control_and_work_budgets(
    prepared_runtime: dict[str, Any],
) -> None:
    original = _actual_node_profile_request(prepared_runtime)
    for fault in (
        "definition",
        "scalar",
        "node-control",
        "case-control",
        "duplicate-case",
        "case-budget",
        "package-budget",
        "schema-version",
    ):
        request = json.loads(json.dumps(original))
        request["nodes"] = request["nodes"][:1]
        node = request["nodes"][0]
        node["cases"] = node["cases"][:1]
        case = node["cases"][0]
        if fault == "definition":
            node["definition"]["warmup"]["minimum_observations"] += 1
        elif fault == "scalar":
            case["inputs"][0]["value"] = {"type": "DECIMAL", "value": 0.5}
        elif fault == "node-control":
            node["binding"] = {"revision": 0}
        elif fault == "case-control":
            case["receipt"] = {}
        elif fault == "duplicate-case":
            node["cases"].append(case)
        elif fault == "case-budget":
            case["inputs"] = case["inputs"][:1] * 8193
        elif fault == "package-budget":
            case["inputs"] = case["inputs"][:1] * 4097
            node["cases"].append({"case_id": "OTHER", "inputs": case["inputs"][:4096]})
        else:
            request["schema_version"] = 2
        assert exchange(prepared_runtime, request, "evaluate") == {"error": "RESEARCH_ALGORITHM_UNAVAILABLE"}, fault


def test_installed_graph_observation_without_targets_uses_actual_feature_factories(
    prepared_runtime: dict[str, Any],
) -> None:
    request = resolution(prepared_runtime, feature_instances(prepared_runtime), private=True)
    assert all(row["type_reference"]["kind"] != "TARGET" for row in request["instances"])
    rows = [
        {"at_ns": (index + 1) * 60_000_000_000, "values": {"close": str(100 + index), "volume": "2"}}
        for index in range(41)
    ]
    actual = exchange(
        prepared_runtime,
        {"contract": "ONLYALPHA_CALCULATION_PLANES_OBSERVATION_V1", "resolution": request, "rows": rows},
        "evaluate",
    )
    assert "error" not in actual, actual
    assert actual["isolation"] == "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
    observed = actual["evaluation"]
    assert observed["targets"] is None
    assert observed["axis"] == [row["at_ns"] for row in rows]
    assert observed["input_fingerprint"] == only_canonical_fingerprint(rows)
    assert observed["feature"]["axis"] == observed["axis"]
    assert len(observed["feature"]["outputs"]) == len(actual["nodes"]) == 3
    assert len(observed["trading_capabilities"]) == 3
    factor = next(row for row in actual["nodes"] if row["definition"]["kind"] == "FACTOR")
    output = next(
        row for row in observed["feature"]["outputs"] if row["node_fingerprint"] == factor["definition_fingerprint"]
    )
    assert output["values"]["value"][:20] == [None] * 20
    assert Decimal(output["values"]["value"][-1]) == Decimal("0.166666666667")
    assert all(key not in observed for key in ("statistics", "research_run_id", "research_result_fingerprint"))
