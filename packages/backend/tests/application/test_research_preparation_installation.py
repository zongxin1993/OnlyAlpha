"""Actual installed math worker and framed protocol; not Human/Product acceptance."""

import hashlib
import json
import struct
import subprocess
import zipfile
from pathlib import Path
from typing import Any

from onlyalpha_backend_algorithms.sdk.private_factor_source import OnlyPrivateFactorExecutableSourceRecordV1
from onlyalpha_gateway_protocol.v1 import calculation_pb2 as wire

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from scripts.build_algorithm_sdk import install


def test_selected_installed_preparation_rejects_rehashed_foreign_operator_resources(tmp_path: Path) -> None:
    wheels, installation = tmp_path / "wheels", tmp_path / "algorithms"
    artifact = install(wheels, installation)
    vector = json.loads((Path(__file__).parent / "fixtures/research_factor.json").read_text())

    def wheel(path: Path) -> dict[str, object]:
        return {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
            "distribution_version": path.name.split("-")[1],
        }

    operator = next(wheels.glob("onlyalpha_plugin_operators-*.whl"))
    request = {
        "schema_version": 1,
        "source": {
            key: vector["revision"][key] for key in OnlyPrivateFactorExecutableSourceRecordV1.__dataclass_fields__
        },
        "graph": vector["graph"],
        "core_artifact": wheel(next(wheels.glob("onlyalpha-*.whl"))),
        "operator_artifact": wheel(operator),
    }

    response = exchange(installation, artifact, request)
    assert response.WhichOneof("outcome") == "result", response
    actual = json.loads(response.result.record_json)
    assert actual["contract"] == "ONLYALPHA_FACTOR_EXECUTABLE_PREPARATION_V1"
    assert actual["equivalence_evidence"]["test_vector_set_fingerprint"] == only_canonical_fingerprint(
        actual["certification_vectors"]
    )
    assert actual["operator_artifact_sha256"] == request["operator_artifact"]["sha256"]
    assert (
        actual["operator_provider_manifest"]["source"]["distribution_version"]
        == request["operator_artifact"]["distribution_version"]
    )
    foreign = tmp_path / operator.name
    with zipfile.ZipFile(operator) as source, zipfile.ZipFile(foreign, "w") as output:
        for name in source.namelist():
            raw = source.read(name)
            output.writestr(name, raw + b"\n# foreign\n" if name.endswith("/registration.py") else raw)
    assert wheel(foreign)["sha256"] != wheel(operator)["sha256"]
    denied = exchange(installation, artifact, {**request, "operator_artifact": wheel(foreign)})
    assert denied.WhichOneof("outcome") == "error"
    assert denied.error.code == "REQUEST_REJECTED"


def exchange(
    installation: Path, artifact: str, payload: dict[str, object], operation: str = "research_prepare"
) -> wire.CalculationResponse:
    handshake = wire.CalculationRequest(
        protocol_version=1, generation="a" * 64, sequence=1, handshake=wire.CalculationEmpty()
    )
    prepare = wire.CalculationRequest(
        protocol_version=1,
        generation="a" * 64,
        sequence=2,
        **{
            operation: {
                "research_prepare": wire.ResearchPrepare,
                "research_resolve": wire.ResearchResolve,
                "research_evaluate": wire.ResearchEvaluate,
            }[operation](request_json=only_canonical_json(payload).encode())
        },
    )
    frames = b"".join(
        struct.pack("!I", len(raw)) + raw
        for message in (handshake, prepare)
        for raw in (message.SerializeToString(deterministic=True),)
    )
    child = subprocess.run(
        [
            str(installation / "bin/python"),
            "-B",
            "-I",
            "-m",
            "onlyalpha_backend_algorithms.research_worker",
            "--generation",
            "a" * 64,
            "--artifact",
            artifact,
            "--installation",
            str(installation),
        ],
        input=frames,
        capture_output=True,
        check=False,
        timeout=30,
        env={},
    )
    assert child.returncode == 0, child.stderr.decode()
    responses, remaining = [], child.stdout
    while remaining:
        size = struct.unpack("!I", remaining[:4])[0]
        assert 0 < size <= 8 * 1024 * 1024
        responses.append(wire.CalculationResponse.FromString(remaining[4 : 4 + size]))
        remaining = remaining[4 + size :]
    assert len(responses) == 2
    assert [r.sequence for r in responses] == [1, 2]
    assert all(r.artifact_fingerprint == artifact and r.generation == "a" * 64 for r in responses)
    return responses[1]


def test_installed_calculation_resolution_uses_exact_target_and_operator_resources(tmp_path: Path) -> None:
    wheels, installation = tmp_path / "wheels", tmp_path / "algorithms"
    artifact = install(wheels, installation)

    def selected(pattern: str) -> dict[str, object]:
        path = next(wheels.glob(pattern))
        return {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
            "distribution_version": path.name.split("-")[1],
        }

    request = {
        "schema_version": 1,
        "contract": "ONLYALPHA_CALCULATION_INSTANCES_RESOLVE_V1",
        "sources": [],
        "instances": [
            {
                "instance_key": "target",
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
        "core_artifact": selected("onlyalpha-*.whl"),
        "operator_artifact": selected("onlyalpha_plugin_operators-*.whl"),
        "target_artifact": selected("onlyalpha_backend_algorithms-*.whl"),
    }
    response = exchange(installation, artifact, request, "research_resolve")
    assert response.WhichOneof("outcome") == "result", response
    actual = json.loads(response.result.record_json)
    assert actual["contract"] == request["contract"]
    assert actual["source_artifacts"] == []
    assert actual["nodes"][0]["definition"]["type_id"] == "onlyalpha.target.forward_return"
    assert actual["target_artifact_sha256"] == request["target_artifact"]["sha256"]
    assert actual["isolation"] == "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
    assert "equivalence_evidence" not in actual and "runtime_generation_fingerprint" not in actual
    evaluated = exchange(
        installation,
        artifact,
        {
            "resolution": request,
            "rows": [{"at_ns": i * 60_000_000_000, "values": {"close": str(10 + i)}} for i in range(8)],
        },
        "research_evaluate",
    )
    assert evaluated.WhichOneof("outcome") == "result", evaluated
    observation = json.loads(evaluated.result.record_json)
    assert observation["evaluation"]["outputs"][0]["values"]["target_value"] == [
        "0.500000000000",
        "0.454545454545",
        "0.416666666667",
        None,
        None,
        None,
        None,
        None,
    ]
    assert observation["evaluation"]["trading_outputs"] == []
    assert observation["isolation"] == "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
    for name in ("core_artifact", "operator_artifact", "target_artifact"):
        changed = json.loads(json.dumps(request))
        changed[name]["sha256"] = "f" * 64
        denied = exchange(installation, artifact, changed, "research_resolve")
        assert denied.WhichOneof("outcome") == "error"
        assert denied.error.code == "REQUEST_REJECTED"


def test_installed_strategy_preparation_retains_actual_target_capabilities_and_refuses_foreign_bytes(
    tmp_path: Path,
) -> None:
    wheels, installation = tmp_path / "wheels", tmp_path / "algorithms"
    artifact = install(wheels, installation)
    vector = json.loads((Path(__file__).parent / "fixtures/research_factor.json").read_text())

    def wheel(path: Path) -> dict[str, object]:
        return {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
            "distribution_version": path.name.split("-")[1],
        }

    original = {
        "schema_version": 1,
        "source": {
            key: vector["revision"][key] for key in OnlyPrivateFactorExecutableSourceRecordV1.__dataclass_fields__
        },
        "graph": vector["graph"],
        "core_artifact": wheel(next(wheels.glob("onlyalpha-*.whl"))),
        "operator_artifact": wheel(next(wheels.glob("onlyalpha_plugin_operators-*.whl"))),
    }
    legacy = exchange(installation, artifact, original)
    assert legacy.WhichOneof("outcome") == "result", legacy
    legacy_record = json.loads(legacy.result.record_json)
    assert legacy_record["contract"] == "ONLYALPHA_FACTOR_EXECUTABLE_PREPARATION_V1"
    assert "target_calculations" not in legacy_record and "target_artifact_sha256" not in legacy_record

    target = next(wheels.glob("onlyalpha_backend_algorithms-*.whl"))
    request = {
        **original,
        "contract": "ONLYALPHA_STRATEGY_EXECUTABLE_PREPARATION_V1",
        "target_artifact": wheel(target),
    }
    response = exchange(installation, artifact, request)
    assert response.WhichOneof("outcome") == "result", response
    actual = json.loads(response.result.record_json)
    assert actual["contract"] == request["contract"]
    assert actual["target_artifact_sha256"] == request["target_artifact"]["sha256"]
    assert len(actual["target_resources_fingerprint"]) == 64
    capabilities = actual["target_calculations"]
    assert capabilities
    assert all(c["type"]["kind"] == "TARGET" and c["backend"] == "RESEARCH" for c in capabilities)
    assert all(c["state_capability"] is None and c["checkpoint_schema_version"] is None for c in capabilities)
    assert "target_provider_manifest" not in actual
    assert "runtime_generation_fingerprint" not in actual
    assert actual["isolation"] == "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
    # The new inventory is an actual installed registration, independently
    # rematerialized through the already shipping exact Calculation resolver.
    resolved = exchange(
        installation,
        artifact,
        {
            "schema_version": 1,
            "contract": "ONLYALPHA_CALCULATION_INSTANCES_RESOLVE_V1",
            "sources": [],
            "instances": [
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
            "core_artifact": original["core_artifact"],
            "operator_artifact": original["operator_artifact"],
            "target_artifact": wheel(target),
        },
        "research_resolve",
    )
    assert resolved.WhichOneof("outcome") == "result", resolved
    manifest = json.loads(resolved.result.record_json)["nodes"][0]["implementations"][0]
    assert any(c["implementation_fingerprint"] == manifest["implementation_fingerprint"] for c in capabilities)
    # All former Factor preparation values remain exact under the new explicit
    # envelope. The Runtime owner adds the separately typed Target capability.
    for key, value in legacy_record.items():
        if key != "contract":
            assert actual[key] == value, key
    foreign = tmp_path / target.name
    with zipfile.ZipFile(target) as source, zipfile.ZipFile(foreign, "w") as output:
        for name in source.namelist():
            raw = source.read(name)
            output.writestr(name, raw + b"\n# foreign resource\n" if name.endswith("/registration.py") else raw)
    assert wheel(foreign)["sha256"] != wheel(target)["sha256"]
    denied = exchange(installation, artifact, {**request, "target_artifact": wheel(foreign)})
    assert denied.WhichOneof("outcome") == "error"
    assert denied.error.code == "REQUEST_REJECTED"
    for change in ({"distribution_version": "missing"}, {"sha256": "f" * 64}):
        denied = exchange(installation, artifact, {**request, "target_artifact": {**wheel(target), **change}})
        assert denied.WhichOneof("outcome") == "error"
        assert denied.error.code == "REQUEST_REJECTED"


def _actual_node_profile_request(wheels: Path) -> dict[str, Any]:
    """Controlled mathematical inputs retain actual Definition/implementation identity."""
    from decimal import Decimal

    from onlyalpha.calculation.definition import OnlyCalculationDefinition

    root = Path(__file__).parents[4]
    vector = json.loads((root / "packages/backend/tests/application/fixtures/research_factor.json").read_text())
    calculations = json.loads(
        (root / "packages/backend/tests/application/fixtures/strategy_calculations.json").read_text()
    )

    def selected(pattern: str) -> dict[str, object]:
        wheel = next(wheels.glob(pattern))
        return {
            "path": str(wheel),
            "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "size": wheel.stat().st_size,
            "distribution_version": wheel.name.split("-")[1],
        }

    resolution = {
        "schema_version": 1,
        "contract": "ONLYALPHA_CALCULATION_INSTANCES_RESOLVE_V1",
        "sources": [
            {key: vector["revision"][key] for key in OnlyPrivateFactorExecutableSourceRecordV1.__dataclass_fields__}
        ],
        "instances": calculations["instances"],
        "core_artifact": selected("onlyalpha-*.whl"),
        "operator_artifact": selected("onlyalpha_plugin_operators-*.whl"),
        "target_artifact": selected("onlyalpha_backend_algorithms-*.whl"),
    }
    nodes = []
    for record in calculations["nodes"]:
        definition = record["definition"]
        parsed = OnlyCalculationDefinition.from_dict(definition)
        period = definition["parameters"].get("period", {}).get("value", 0)
        count = max(parsed.warmup.minimum_observations, int(period) + 1) + 22
        quantum = Decimal(str(definition["numeric"]["output_quantum"]))
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
                    "QUANTIZATION_BOUNDARY": quantum * Decimal("0.5") if index % 2 == 0 else quantum * Decimal("1.5"),
                }[name]
                row = {port.name: {"type": "DECIMAL", "value": format(value, "f")} for port in parsed.inputs}
                if name == "NULLABLE_INPUT_SEMANTICS":
                    nullable = [port.name for port in parsed.inputs if port.nullable]
                    if nullable and index < len(nullable):
                        row[nullable[index]] = {"type": "NULL", "value": None}
                rows.append(row)
            # This approved Factor's explicit public contract has close and a
            # historical-close operand. Straddle output rounding with a ratio
            # denominator of one, rather than merely attaching a case label.
            if definition["kind"] == "FACTOR" and name == "QUANTIZATION_BOUNDARY":
                for index, row in enumerate(rows):
                    for port in parsed.inputs:
                        row[port.name] = {"type": "DECIMAL", "value": "1"}
                    row["close"] = {
                        "type": "DECIMAL",
                        "value": format(
                            Decimal(1) + quantum * (Decimal("0.5") if index % 2 == 0 else Decimal("1.5")), "f"
                        ),
                    }
            cases.append({"case_id": name, "inputs": rows})
        nodes.append({"definition": definition, "cases": cases})
    return {
        "schema_version": 1,
        "contract": "ONLYALPHA_CALCULATION_NODE_PROFILE_OBSERVATION_V1",
        "resolution": resolution,
        "nodes": nodes,
    }


def test_installed_node_profiles_observe_exact_factories_and_typed_nulls(tmp_path: Path) -> None:
    from onlyalpha.calculation.definition import OnlyCalculationDefinition

    wheels, installation = tmp_path / "wheels", tmp_path / "algorithms"
    artifact = install(wheels, installation)
    request = _actual_node_profile_request(wheels)
    response = exchange(installation, artifact, request, "research_evaluate")
    assert response.WhichOneof("outcome") == "result", response
    actual = json.loads(response.result.record_json)
    assert actual["isolation"] == "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
    observed = actual["evaluation"]
    assert set(observed) == {"schema_version", "contract", "nodes"}
    assert observed["schema_version"] == 1 and observed["contract"] == request["contract"]
    expected = {OnlyCalculationDefinition.from_dict(row["definition"]).fingerprint: row for row in request["nodes"]}
    values = {row["node_fingerprint"]: row for row in observed["nodes"]}
    assert len(values) == len(observed["nodes"]) == len(expected) == 3
    assert values.keys() == expected.keys()
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
        assert len(cases) == len(node["cases"]) == len(planned) == 7
        assert cases.keys() == planned.keys()
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
        name = expected[key]["definition"]["type_id"]
        if name == "onlyalpha.operator.delay":
            count = expected[key]["definition"]["parameters"]["period"]["value"]
            flat = cases["FLAT_SEQUENCE"]["research_outputs"]
            assert [row["value"] for row in flat[:count]] == [{"type": "NULL", "value": None}] * count
            assert flat[count]["value"] == {"type": "DECIMAL", "value": "100"}
        if expected[key]["definition"]["kind"] == "FACTOR":
            assert all(
                row["value"] == {"type": "NULL", "value": None} for row in cases["ZERO_BOUNDARY"]["research_outputs"]
            )
            boundary = cases["QUANTIZATION_BOUNDARY"]["research_outputs"]
            assert boundary[0]["value"] == {"type": "DECIMAL", "value": "0"}
            assert boundary[1]["value"] == {"type": "DECIMAL", "value": "0.000000000002"}
    assert total <= 8192
    # This is a raw algorithm observation, not a portable Kernel checkpoint,
    # execution receipt, Strategy state, authorization or admission certificate.
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


def test_installed_node_profiles_reject_foreign_definitions_scalars_control_and_work_budgets(tmp_path: Path) -> None:
    wheels, installation = tmp_path / "wheels", tmp_path / "algorithms"
    artifact = install(wheels, installation)
    original = _actual_node_profile_request(wheels)
    for fault in (
        "definition",
        "scalar",
        "node-control",
        "case-control",
        "duplicate-case",
        "case-budget",
        "package-budget",
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
        else:
            case["inputs"] = case["inputs"][:1] * 4097
            node["cases"].append({"case_id": "OTHER", "inputs": case["inputs"][:4096]})
        response = exchange(installation, artifact, request, "research_evaluate")
        assert response.WhichOneof("outcome") == "error", (fault, response)
        assert response.error.code == "REQUEST_REJECTED"


def test_installed_graph_observation_without_targets_uses_actual_feature_factories(tmp_path: Path) -> None:
    """Targetless validation is actual arithmetic, not a fabricated Research study."""
    from decimal import Decimal

    wheels, installation = tmp_path / "wheels", tmp_path / "algorithms"
    artifact = install(wheels, installation)
    resolution = _actual_node_profile_request(wheels)["resolution"]
    assert all(row["type_reference"]["kind"] != "TARGET" for row in resolution["instances"])
    rows = [
        {"at_ns": (index + 1) * 60_000_000_000, "values": {"close": str(100 + index), "volume": "2"}}
        for index in range(41)
    ]
    request = {"contract": "ONLYALPHA_CALCULATION_PLANES_OBSERVATION_V1", "resolution": resolution, "rows": rows}
    response = exchange(installation, artifact, request, "research_evaluate")
    assert response.WhichOneof("outcome") == "result", response
    actual = json.loads(response.result.record_json)
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
