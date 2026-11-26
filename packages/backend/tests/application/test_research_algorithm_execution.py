"""Restricted authoring and installed Operator/Target diagnostics; no Product Run grant."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from onlyalpha_backend_algorithms.sdk import private_factor_execution as execution
from onlyalpha_backend_algorithms.sdk.private_factor_source import OnlyPrivateFactorExecutableSourceRecordV1

from packages.backend.tests.application.test_research_preparation_installation import (
    exchange,
    operator_instances,
    resolution,
    target_instance,
)
from packages.backend.tests.application.test_research_preparation_installation import (
    prepared_runtime as prepared_runtime,
)
from packages.backend.tests.application.test_schema_postgres import migration_backend as migration_backend
from packages.backend.tests.application.test_schema_postgres import schema_db as schema_db

UNAVAILABLE = {"error": "RESEARCH_ALGORITHM_UNAVAILABLE"}
NULL = {"value": {"type": "NULL", "value": None}}
ZERO = {"value": {"type": "DECIMAL", "value": "0"}}


def private_source_record() -> dict[str, Any]:
    vector = json.loads((Path(__file__).parent / "fixtures/research_factor.json").read_text())
    return {key: vector["revision"][key] for key in OnlyPrivateFactorExecutableSourceRecordV1.__dataclass_fields__}


def test_source_validation_cannot_grant_a_native_factor_binding() -> None:
    revision = OnlyPrivateFactorExecutableSourceRecordV1.from_dict(private_source_record())
    validation = execution.only_validate_private_factor_revision(revision)
    assert validation.validation_disposition is execution.OnlyPrivateFactorValidationDisposition.FAIL
    assert validation.errors == ("PRIVATE_FACTOR_NATIVE_BUILD_REQUIRED",)
    with pytest.raises(ValueError, match="^PRIVATE_FACTOR_VALIDATION_EVIDENCE_MISMATCH$"):
        execution.OnlyPrivateFactorSourceArtifactManifestV1.materialize(revision, validation)


def test_retired_source_execution_refuses_even_matching_bytes() -> None:
    revision = OnlyPrivateFactorExecutableSourceRecordV1.from_dict(private_source_record())
    source = revision.source_text.encode()
    evidence = execution.only_validate_private_factor_revision(revision)
    # This DTO is only a byte-integrity fixture; the owning builder never
    # produces a runnable artifact from validation of source text alone.
    manifest = execution.OnlyPrivateFactorSourceArtifactManifestV1(
        revision.factor_id,
        revision.semantic_version,
        revision.revision_fingerprint,
        revision.source_sha256,
        len(source),
        revision.factor_api_version,
        revision.factor_api_contract_fingerprint,
        evidence.validation_policy_fingerprint,
        evidence.validation_evidence_fingerprint,
    )
    evaluate = execution.only_execute_private_factor_program
    with pytest.raises(ValueError, match="^PRIVATE_FACTOR_NATIVE_PROGRAM_REQUIRED$"):
        evaluate(manifest, source, {}, {})
    with pytest.raises(ValueError, match="^PRIVATE_FACTOR_SOURCE_ARTIFACT_MISMATCH$"):
        evaluate(manifest, source + b"\n", {}, {})


def observe(selected: dict[str, Any], resolved: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    return exchange(
        selected,
        {"contract": "ONLYALPHA_CALCULATION_PLANES_OBSERVATION_V1", "resolution": resolved, "rows": rows},
        "evaluate",
    )


@pytest.mark.integration
@pytest.mark.postgres
def test_source_only_resolution_cannot_attach_to_an_installed_environment(prepared_runtime: dict[str, Any]) -> None:
    request = resolution(prepared_runtime, [target_instance()])
    assert "error" not in exchange(prepared_runtime, request)
    assert exchange(prepared_runtime, {**request, "sources": [private_source_record()]}) == UNAVAILABLE


@pytest.mark.parametrize("bad", ["1e2", "NaN", "Infinity", "01", "+1"])
@pytest.mark.integration
@pytest.mark.postgres
def test_target_graph_rejects_noncanonical_external_decimal_values(prepared_runtime: dict[str, Any], bad: str) -> None:
    request = resolution(prepared_runtime, [target_instance()])
    rows = [{"at_ns": i * 60_000_000_000, "values": {"close": "100"}} for i in range(23)]
    assert "error" not in observe(prepared_runtime, request, rows)
    rows[0]["values"]["close"] = bad
    assert observe(prepared_runtime, request, rows) == UNAVAILABLE


@pytest.mark.integration
@pytest.mark.postgres
def test_operator_resolution_is_order_independent_and_requires_closed_bindings(
    prepared_runtime: dict[str, Any],
) -> None:
    delay, mean = operator_instances()
    parent = {"kind": "VARIABLE", "instance_key": "delay", "output_name": "value"}
    mean["input_bindings"][0]["source"] = parent
    request = resolution(prepared_runtime, [delay, mean])
    first = exchange(prepared_runtime, request)
    assert "error" not in first, first
    assert first["source_artifacts"] == []
    assert exchange(prepared_runtime, {**request, "instances": [mean, delay]}) == first
    actual = {row["instance_key"]: row for row in first["nodes"]}
    assert actual.keys() == {"delay", "mean"}
    for instance in (delay, mean):
        row = actual[instance["instance_key"]]
        definition = row["definition"]
        assert {key: definition[key] for key in instance["type_reference"]} == instance["type_reference"]
        assert definition["parameters"] == {name: value["value"] for name, value in instance["parameters"].items()}
        assert {value["backend_kind"] for value in row["implementations"]} == {"RESEARCH", "TRADING"}
        assert len(row["definition_fingerprint"]) == 64
    assert actual["delay"]["definition"]["input_bindings"] == {
        "value": {"node_fingerprint": None, "output_name": "value", "source": "bar.close"}
    }
    assert actual["mean"]["definition"]["input_bindings"] == {
        "value": {"node_fingerprint": actual["delay"]["definition_fingerprint"], "output_name": "value", "source": None}
    }
    for key in ("missing", "mean"):
        parent["instance_key"] = key
        assert exchange(prepared_runtime, request) == UNAVAILABLE


@pytest.mark.integration
@pytest.mark.postgres
def test_forward_return_rejects_zero_price_and_keeps_end_of_window_nulls(prepared_runtime: dict[str, Any]) -> None:
    rows = [{"at_ns": i * 60_000_000_000, "values": {"close": "100"}} for i in range(42)]
    target = resolution(prepared_runtime, [target_instance()])
    observed = observe(prepared_runtime, target, rows)
    assert "error" not in observed, observed
    values = observed["evaluation"]["targets"]["outputs"][0]["values"]["target_value"]
    assert [Decimal(value) for value in values[:-5]] == [Decimal(0)] * (len(rows) - 5)
    assert values[-5:] == [None] * 5
    rows[0]["values"]["close"] = "0"
    assert observe(prepared_runtime, target, rows) == UNAVAILABLE


@pytest.mark.integration
@pytest.mark.postgres
def test_native_delay_profile_keeps_exact_row_and_case_limits(prepared_runtime: dict[str, Any]) -> None:
    delay, _ = operator_instances()
    resolved = resolution(prepared_runtime, [delay])
    result = exchange(prepared_runtime, resolved)
    assert "error" not in result, result
    case = {"case_id": "ZERO_BOUNDARY", "inputs": [ZERO] * 8192}
    node = {"definition": result["nodes"][0]["definition"], "cases": [case]}
    request = {
        "schema_version": 1,
        "contract": "ONLYALPHA_CALCULATION_NODE_PROFILE_OBSERVATION_V1",
        "resolution": resolved,
        "nodes": [node],
    }
    accepted = exchange(prepared_runtime, request, "evaluate")
    assert "error" not in accepted, accepted
    profile = accepted["evaluation"]["nodes"][0]["cases"][0]
    outputs = profile["research_outputs"]
    assert outputs == profile["trading_outputs"]
    assert len(outputs) == 8192 and outputs[:20] == [NULL] * 20
    assert all(row["value"]["type"] == "DECIMAL" and Decimal(row["value"]["value"]) == 0 for row in outputs[20:])
    case["inputs"] = [ZERO] * 8193
    assert exchange(prepared_runtime, request, "evaluate") == UNAVAILABLE
    node["cases"] = [{"case_id": f"CASE_{i}", "inputs": [ZERO]} for i in range(32)]
    accepted = exchange(prepared_runtime, request, "evaluate")
    assert "error" not in accepted, accepted
    cases = accepted["evaluation"]["nodes"][0]["cases"]
    assert {case["case_id"] for case in cases} == {f"CASE_{i}" for i in range(32)}
    assert all(case["research_outputs"] == case["trading_outputs"] == [NULL] for case in cases)
    node["cases"].append({"case_id": "CASE_32", "inputs": [ZERO]})
    assert exchange(prepared_runtime, request, "evaluate") == UNAVAILABLE
