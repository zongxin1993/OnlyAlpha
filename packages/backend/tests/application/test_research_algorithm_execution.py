"""Native graph and restricted private SDK conformance; no Research permission."""

from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from onlyalpha.calculation.definition import OnlyCalculationReference
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha_backend_algorithms.sdk import private_factor_execution as execution
from onlyalpha_backend_algorithms.sdk.private_factor_source import OnlyPrivateFactorExecutableSourceRecordV1

from packages.backend.tests.application.test_research_preparation_installation import (
    exchange,
    feature_instances,
    resolution,
    target_instance,
)
from packages.backend.tests.application.test_research_preparation_installation import (
    prepared_runtime as prepared_runtime,
)
from packages.backend.tests.application.test_schema_postgres import migration_backend as migration_backend
from packages.backend.tests.application.test_schema_postgres import schema_db as schema_db


def private_source() -> OnlyPrivateFactorExecutableSourceRecordV1:
    vector = json.loads((Path(__file__).parent / "fixtures/research_factor.json").read_text())
    return OnlyPrivateFactorExecutableSourceRecordV1.from_dict(
        {key: vector["revision"][key] for key in OnlyPrivateFactorExecutableSourceRecordV1.__dataclass_fields__}
    )


def test_native_preparation_observes_both_actual_backends_and_retains_exact_vectors() -> None:
    source = private_source()
    definition = execution.OnlyPrivateFactorDefinitionResolverV1(
        execution.only_private_factor_type_definition(source)
    ).resolve({}, {name: OnlyCalculationReference(None, "value", name) for name in source.input_contract})
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import json,sys;from onlyalpha.canonical import only_canonical_json;from onlyalpha_backend_algorithms.research_preparation import certify;print(only_canonical_json(certify(json.load(sys.stdin))))",
        ],
        input=json.dumps(
            {
                "source": {key: getattr(source, key) for key in source.__dataclass_fields__}
                | {
                    key: dict(getattr(source, key))
                    for key in ("input_contract", "parameter_contract", "output_contract")
                },
                "graph": {"schema_version": 1, "nodes": [{"alias": None, "definition": dict(definition.to_dict())}]},
            }
        ),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    evidence = actual["equivalence_evidence"]
    assert actual["isolation"] == "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
    assert evidence["disposition"] == "PASS"
    assert evidence["research_output_fingerprint"] == evidence["trading_output_fingerprint"]
    assert evidence["test_vector_set_fingerprint"] == only_canonical_fingerprint(actual["certification_vectors"])
    assert actual["certification_vectors"]["parameters"] == {"literal_1": "1"}
    assert len(actual["certification_vectors"]["vectors"]) == 8
    assert actual["provider_snapshot"]["entries"][0]["revision_fingerprint"] == source.revision_fingerprint
    assert "research_result" not in actual


def test_managed_observation_reuses_the_admitted_api_math_and_checks_source_bytes() -> None:
    revision = private_source()
    validation = execution.only_validate_private_factor_revision(revision)
    manifest, source = execution.OnlyPrivateFactorSourceArtifactManifestV1.materialize(revision, validation)
    evaluate = execution.only_execute_private_factor_program
    value = evaluate(
        manifest,
        source,
        {
            "close": Decimal("120"),
            "close_lag_20": Decimal("100"),
            "volume": Decimal("200"),
            "volume_mean_20": Decimal("100"),
        },
        {"literal_1": Decimal("1")},
    )
    assert value == {"value": Decimal("0.4")}
    with pytest.raises(ValueError, match="PRIVATE_FACTOR_SOURCE_ARTIFACT_MISMATCH"):
        evaluate(manifest, source + b"\n", {}, {})


def observe(
    selected: dict[str, Any], rows: list[dict[str, Any]], request: dict[str, Any] | None = None
) -> dict[str, Any]:
    resolved = request or resolution(selected, feature_instances(selected), private=True)
    return exchange(
        selected,
        {"contract": "ONLYALPHA_CALCULATION_PLANES_OBSERVATION_V1", "resolution": resolved, "rows": rows},
        "evaluate",
    )


def factor_values(observed: dict[str, Any]) -> list[str | None]:
    assert "error" not in observed, observed
    factor = next(row for row in observed["nodes"] if row["definition"]["kind"] == "FACTOR")
    return next(
        row["values"]["value"]
        for row in observed["evaluation"]["feature"]["outputs"]
        if row["node_fingerprint"] == factor["definition_fingerprint"]
    )


@pytest.mark.integration
@pytest.mark.postgres
def test_actual_graph_batch_keeps_warmup_gaps_and_exact_parameter_values(prepared_runtime: dict[str, Any]) -> None:
    rows = [{"at_ns": i * 60_000_000_000, "values": {"close": str(100 + i), "volume": "200"}} for i in range(23)]
    result = observe(prepared_runtime, rows)
    values = factor_values(result)
    assert values[:20] == [None] * 20 and Decimal(values[20]) == Decimal("0.2")
    rows[1]["values"]["close"] = None
    gapped = factor_values(observe(prepared_runtime, rows))
    assert gapped[21] is None and gapped[20] == values[20]
    factor = next(row for row in result["nodes"] if row["definition"]["kind"] == "FACTOR")
    assert factor["definition"]["parameters"]["literal_1"] == {"type": "DECIMAL", "value": "1"}
    foreign = json.loads(json.dumps(resolution(prepared_runtime, feature_instances(prepared_runtime), private=True)))
    root = next(row for row in foreign["instances"] if row["type_reference"]["kind"] == "FACTOR")
    root["input_bindings"][0]["source"] = {"kind": "VARIABLE", "instance_key": "missing", "output_name": "value"}
    assert observe(prepared_runtime, rows, foreign) == {"error": "RESEARCH_ALGORITHM_UNAVAILABLE"}
    # The classic source-bound root must belong to the actual producer graph.
    classic = {
        "schema_version": 1,
        "source": {
            key: prepared_runtime["revision"][key]
            for key in OnlyPrivateFactorExecutableSourceRecordV1.__dataclass_fields__
        },
        "graph": prepared_runtime["proof"]["algorithm_observation"]["graph"],
        "core_artifact": foreign["core_artifact"],
    }
    assert exchange(
        prepared_runtime, {"resolution": classic, "rows": rows, "root_fingerprint": "0" * 64}, "evaluate"
    ) == {"error": "RESEARCH_ALGORITHM_UNAVAILABLE"}


@pytest.mark.parametrize("bad", ["1e2", "NaN", "Infinity", "01", "+1"])
@pytest.mark.integration
@pytest.mark.postgres
def test_managed_graph_rejects_noncanonical_external_decimal_values(prepared_runtime: dict[str, Any], bad: str) -> None:
    rows = [{"at_ns": i * 60_000_000_000, "values": {"close": bad, "volume": "200"}} for i in range(23)]
    assert observe(prepared_runtime, rows) == {"error": "RESEARCH_ALGORITHM_UNAVAILABLE"}


@pytest.mark.integration
@pytest.mark.postgres
def test_calculation_resolution_reuses_actual_factor_and_operator_definitions(prepared_runtime: dict[str, Any]) -> None:
    request = resolution(prepared_runtime, feature_instances(prepared_runtime), private=True)
    first = exchange(prepared_runtime, request)
    assert "error" not in first, first
    request["instances"].reverse()
    second = exchange(prepared_runtime, request)
    assert second == first
    actual = {row["instance_key"]: row for row in first["nodes"]}
    assert len(actual) == 3
    for instance in request["instances"]:
        row = actual[instance["instance_key"]]
        definition = row["definition"]
        assert {key: definition[key] for key in ("kind", "type_id", "semantic_version")} == instance["type_reference"]
        assert definition["parameters"] == {
            name: parameter["value"] for name, parameter in instance["parameters"].items()
        }
        expected_bindings = {}
        for binding in instance["input_bindings"]:
            source = binding["source"]
            expected_bindings[binding["input_name"]] = (
                {"node_fingerprint": None, "output_name": "value", "source": source}
                if isinstance(source, str)
                else {
                    "node_fingerprint": actual[source["instance_key"]]["definition_fingerprint"],
                    "output_name": source["output_name"],
                    "source": None,
                }
            )
        assert definition["input_bindings"] == expected_bindings
    for row in actual.values():
        assert {value["backend_kind"] for value in row["implementations"]} == {"RESEARCH", "TRADING"}
        definition = row["definition"]
        assert definition["semantic_version"] == ("1" if definition["kind"] == "FACTOR" else "2")
        assert len(row["definition_fingerprint"]) == 64
    assert len(first["source_artifacts"]) == 1
    private = first["source_artifacts"][0]["private_calculations"]
    assert {row["backend"] for row in private} == {"RESEARCH", "TRADING"}
    assert all(row["type"]["type_id"] == prepared_runtime["revision"]["factor_id"] for row in private)
    assert next(row for row in private if row["backend"] == "TRADING")["state_capability"] == "STATELESS"


@pytest.mark.integration
@pytest.mark.postgres
def test_public_only_resolution_needs_no_fake_factor_and_rejects_unclosed_inputs(
    prepared_runtime: dict[str, Any],
) -> None:
    delay = feature_instances(prepared_runtime)[0]
    request = resolution(prepared_runtime, [target_instance(), delay])
    result = exchange(prepared_runtime, request)
    assert "error" not in result, result
    assert result["source_artifacts"] == []
    target = next(row for row in result["nodes"] if row["instance_key"] == "target")
    assert target["definition"]["parameters"]["entry_offset"] == {"type": "INTEGER", "value": 0}
    assert len(target["implementations"]) == 1
    for parent in ("missing", "delay"):
        changed = json.loads(json.dumps(delay))
        changed["input_bindings"][0]["source"] = {"kind": "VARIABLE", "instance_key": parent, "output_name": "value"}
        assert exchange(prepared_runtime, resolution(prepared_runtime, [changed])) == {
            "error": "RESEARCH_ALGORITHM_UNAVAILABLE"
        }


def streaming_profiles(selected: dict[str, Any], *, count: int = 42) -> dict[str, Any]:
    request = resolution(selected, feature_instances(selected), private=True)
    result = exchange(selected, request)
    assert "error" not in result, result
    nodes = []
    for row in result["nodes"]:
        definition = row["definition"]
        operands = {port["name"]: {"type": "DECIMAL", "value": "0"} for port in definition["inputs"]}
        nodes.append(
            {
                "definition": definition,
                "cases": [{"case_id": "ZERO_BOUNDARY", "inputs": [operands for _ in range(count)]}],
            }
        )
    return {
        "schema_version": 1,
        "contract": "ONLYALPHA_CALCULATION_NODE_PROFILE_OBSERVATION_V1",
        "resolution": request,
        "nodes": nodes,
    }


@pytest.mark.integration
@pytest.mark.postgres
def test_full_numeric_graph_observes_actual_vector_and_streaming_backends(prepared_runtime: dict[str, Any]) -> None:
    rows = [{"at_ns": i * 60_000_000_000, "values": {"close": str(100 + i), "volume": "200"}} for i in range(720)]
    result = observe(prepared_runtime, rows)
    values = factor_values(result)
    assert values[:20] == [None] * 20
    assert Decimal(values[20]) == Decimal("0.2") and Decimal(values[40]) == Decimal("0.166666666667")
    assert len(values) == 720
    rows[1]["values"]["close"] = None
    gapped = factor_values(observe(prepared_runtime, rows))
    assert gapped[21] is None and gapped[20] == values[20]
    # Independent actual stream factories are observed through native profiles.
    # Whole-graph Trading order/receipts/restart belong to workers_trading tests.
    profiles = exchange(prepared_runtime, streaming_profiles(prepared_runtime), "evaluate")
    assert "error" not in profiles, profiles
    for node in profiles["evaluation"]["nodes"]:
        for case in node["cases"]:
            assert case["research_outputs"] == case["trading_outputs"]
    assert "equivalence_evidence" not in result and "strategy_fingerprint" not in result


@pytest.mark.integration
@pytest.mark.postgres
def test_zero_volume_graph_preserves_actual_math_and_forward_return_rejects_zero_price(
    prepared_runtime: dict[str, Any],
) -> None:
    rows = [{"at_ns": i * 60_000_000_000, "values": {"close": "100", "volume": "0"}} for i in range(42)]
    result = observe(prepared_runtime, rows)
    assert factor_values(result) == [None] * len(rows)
    mean = next(row for row in result["nodes"] if row["definition"]["type_id"] == "onlyalpha.operator.rolling_mean")
    values = next(
        row["values"]["value"]
        for row in result["evaluation"]["feature"]["outputs"]
        if row["node_fingerprint"] == mean["definition_fingerprint"]
    )
    assert Decimal(values[-1]) == 0
    target = resolution(prepared_runtime, [target_instance()])
    observed = observe(prepared_runtime, rows, target)
    assert "error" not in observed, observed
    values = observed["evaluation"]["targets"]["outputs"][0]["values"]["target_value"]
    assert [Decimal(value) for value in values[:-5]] == [Decimal(0)] * (len(rows) - 5)
    assert values[-5:] == [None] * 5
    rows[0]["values"]["close"] = "0"
    assert observe(prepared_runtime, rows, target) == {"error": "RESEARCH_ALGORITHM_UNAVAILABLE"}


@pytest.mark.integration
@pytest.mark.postgres
def test_direct_zero_profiles_keep_actual_private_factor_division_null(prepared_runtime: dict[str, Any]) -> None:
    request = streaming_profiles(prepared_runtime)
    result = exchange(prepared_runtime, request, "evaluate")
    assert "error" not in result, result
    observed = result["evaluation"]["nodes"]
    assert len(observed) == len(request["nodes"]) == 3
    for node in observed:
        case = node["cases"][0]
        assert case["case_id"] == "ZERO_BOUNDARY" and case["research_outputs"] == case["trading_outputs"]
        assert all(value == {"type": "DECIMAL", "value": "0"} for row in case["inputs"] for value in row.values())
    factor = next(row for row in result["nodes"] if row["definition"]["kind"] == "FACTOR")
    outputs = next(
        row["cases"][0]["research_outputs"]
        for row in observed
        if row["node_fingerprint"] == factor["definition_fingerprint"]
    )
    assert outputs == [{"value": {"type": "NULL", "value": None}}] * len(outputs)
    # Exact per-case and package limits reach the native profile owner unchanged.
    bounded = json.loads(json.dumps(request))
    bounded["nodes"] = [
        next(node for node in bounded["nodes"] if node["definition"]["type_id"] == "onlyalpha.operator.delay")
    ]
    case = bounded["nodes"][0]["cases"][0]
    zero = case["inputs"][:1]
    case["inputs"] = zero * 8192
    accepted = exchange(prepared_runtime, bounded, "evaluate")
    assert "error" not in accepted, accepted
    assert len(accepted["evaluation"]["nodes"][0]["cases"][0]["research_outputs"]) == 8192
    outputs = accepted["evaluation"]["nodes"][0]["cases"][0]["research_outputs"]
    assert outputs[:20] == [{"value": {"type": "NULL", "value": None}}] * 20
    assert all(row["value"]["type"] == "DECIMAL" and Decimal(row["value"]["value"]) == 0 for row in outputs[20:])
    case["inputs"] = zero * 8193
    assert exchange(prepared_runtime, bounded, "evaluate") == {"error": "RESEARCH_ALGORITHM_UNAVAILABLE"}
    bounded["nodes"][0]["cases"] = [{"case_id": f"CASE_{i}", "inputs": zero} for i in range(32)]
    accepted = exchange(prepared_runtime, bounded, "evaluate")
    assert "error" not in accepted and len(accepted["evaluation"]["nodes"][0]["cases"]) == 32
    assert all(
        case["research_outputs"] == [{"value": {"type": "NULL", "value": None}}]
        for case in accepted["evaluation"]["nodes"][0]["cases"]
    )
    bounded["nodes"][0]["cases"].append({"case_id": "CASE_32", "inputs": zero})
    assert exchange(prepared_runtime, bounded, "evaluate") == {"error": "RESEARCH_ALGORITHM_UNAVAILABLE"}
