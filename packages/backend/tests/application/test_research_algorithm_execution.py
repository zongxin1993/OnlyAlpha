"""Pure algorithm conformance only; these checks grant no Research permission."""

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from onlyalpha_backend_algorithms.sdk import private_factor_execution as execution
from onlyalpha_backend_algorithms.sdk.private_factor_source import OnlyPrivateFactorExecutableSourceRecordV1

from onlyalpha.quant_assets import OnlyPrivateFactorRevision


def test_native_preparation_observes_both_actual_backends_and_retains_exact_vectors() -> None:
    vector = json.loads((Path(__file__).parent / "fixtures/research_factor.json").read_text())
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import json,sys;from onlyalpha.canonical import only_canonical_json;"
            "from onlyalpha_backend_algorithms.research_preparation import certify;"
            "print(only_canonical_json(certify(json.load(sys.stdin))))",
        ],
        input=json.dumps(
            {
                "source": {
                    key: vector["revision"][key]
                    for key in OnlyPrivateFactorExecutableSourceRecordV1.__dataclass_fields__
                },
                "graph": vector["graph"],
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
    from onlyalpha.canonical import only_canonical_fingerprint

    assert actual["isolation"] == "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
    assert evidence["disposition"] == "PASS"
    assert evidence["research_output_fingerprint"] == evidence["trading_output_fingerprint"]
    assert evidence["test_vector_set_fingerprint"] == only_canonical_fingerprint(actual["certification_vectors"])
    assert actual["certification_vectors"]["parameters"] == {"literal_1": "1"}
    assert len(actual["certification_vectors"]["vectors"]) == 8
    assert (
        actual["provider_snapshot"]["entries"][0]["revision_fingerprint"] == vector["revision"]["revision_fingerprint"]
    )
    assert "research_result" not in actual


def test_managed_observation_reuses_the_admitted_api_math_and_checks_source_bytes() -> None:
    vector = json.loads((Path(__file__).parent / "fixtures/research_factor.json").read_text())
    revision = OnlyPrivateFactorRevision.from_dict(vector["revision"])
    validation = execution.only_validate_private_factor_revision(revision)
    manifest, source = execution.OnlyPrivateFactorSourceArtifactManifestV1.materialize(revision, validation)
    evaluate = getattr(execution, "only_execute_private_factor_program", None)
    assert callable(evaluate), "managed sandbox needs the same pure API evaluator as the isolated host"
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


def test_actual_graph_batch_keeps_warmup_gaps_and_exact_parameter_values() -> None:
    import importlib

    assert importlib.util.find_spec("onlyalpha_backend_algorithms.research_evaluation") is not None, (
        "missing managed graph evaluator"
    )
    from onlyalpha_backend_algorithms.research_evaluation import evaluate_graph

    vector = json.loads((Path(__file__).parent / "fixtures/research_factor.json").read_text())
    revision = vector["revision"]
    source = {
        k: revision[k]
        for k in (
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
    }
    rows = [{"at_ns": i * 60_000_000_000, "values": {"close": str(100 + i), "volume": "200"}} for i in range(23)]
    result = evaluate_graph(source, vector["graph"], rows, vector["root_fingerprint"])
    assert result["feature"][:20] == [None] * 20
    assert Decimal(result["feature"][20]) == Decimal("0.2")
    rows[1]["values"]["close"] = None
    gapped = evaluate_graph(source, vector["graph"], rows, vector["root_fingerprint"])
    assert gapped["feature"][21] is None
    assert gapped["feature"][20] == result["feature"][20]
    with pytest.raises(ValueError):
        evaluate_graph(source, vector["graph"], rows, "0" * 64)


@pytest.mark.parametrize("bad", ["1e2", "NaN", "Infinity", "01", "+1"])
def test_managed_graph_rejects_noncanonical_external_decimal_values(bad: str) -> None:
    from onlyalpha_backend_algorithms.research_evaluation import evaluate_graph

    vector = json.loads((Path(__file__).parent / "fixtures/research_factor.json").read_text())
    revision = vector["revision"]
    source = {
        k: revision[k]
        for k in (
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
    }
    rows = [{"at_ns": i * 60_000_000_000, "values": {"close": bad, "volume": "200"}} for i in range(23)]
    with pytest.raises(ValueError, match="RESEARCH_EVALUATION_DECIMAL_INVALID"):
        evaluate_graph(source, vector["graph"], rows, vector["root_fingerprint"])


def test_calculation_resolution_reuses_actual_factor_and_operator_definitions() -> None:
    from onlyalpha_backend_algorithms.research_resolution import resolve_instances

    from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition

    vector = json.loads((Path(__file__).parent / "fixtures/research_factor.json").read_text())
    graph = OnlyCalculationGraphDefinition.from_dict(vector["graph"])
    keys = {node.fingerprint: f"node_{i}" for i, node in enumerate(graph.ordered_nodes)}
    instances = []
    for node in reversed(graph.ordered_nodes):
        definition = node.definition.to_dict()
        bindings = []
        for name, reference in definition["input_bindings"].items():
            source = (
                reference["source"]
                if reference["node_fingerprint"] is None
                else {
                    "kind": "VARIABLE",
                    "instance_key": keys[reference["node_fingerprint"]],
                    "output_name": reference["output_name"],
                }
            )
            bindings.append({"input_name": name, "source": source})
        instances.append(
            {
                "instance_key": keys[node.fingerprint],
                "type_reference": {key: definition[key] for key in ("kind", "type_id", "semantic_version")},
                "parameters": {
                    key: {"kind": "FIXED", "value": value} for key, value in definition["parameters"].items()
                },
                "published_outputs": [port["name"] for port in definition["outputs"]],
                "primary_output": "value",
                "input_bindings": bindings,
            }
        )
    source = {key: vector["revision"][key] for key in OnlyPrivateFactorExecutableSourceRecordV1.__dataclass_fields__}
    result = resolve_instances([source], instances)
    actual = {row["instance_key"]: row for row in result["nodes"]}
    assert len(actual) == len(graph.nodes)
    for node in graph.nodes:
        row = actual[keys[node.fingerprint]]
        assert row["definition"] == node.definition.to_dict()
        assert row["definition_fingerprint"] == node.fingerprint
        assert {value["backend_kind"] for value in row["implementations"]} == {"RESEARCH", "TRADING"}
    assert len(result["source_artifacts"]) == 1


def test_public_only_resolution_needs_no_fake_factor_and_rejects_unclosed_inputs() -> None:
    from onlyalpha_backend_algorithms.research_resolution import resolve_instances

    delay = {
        "instance_key": "delay",
        "type_reference": {"kind": "INDICATOR", "type_id": "onlyalpha.operator.delay", "semantic_version": "1"},
        "parameters": {"period": {"kind": "FIXED", "value": {"type": "INTEGER", "value": 20}}},
        "published_outputs": ["value"],
        "primary_output": "value",
        "input_bindings": [{"input_name": "value", "source": "bar.close"}],
    }
    target = {
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
    result = resolve_instances([], [target, delay])
    assert result["source_artifacts"] == []
    target_result = next(row for row in result["nodes"] if row["instance_key"] == "target")
    assert target_result["definition"]["parameters"]["entry_offset"] == {"type": "INTEGER", "value": 0}
    assert len(target_result["implementations"]) == 1
    changed = json.loads(json.dumps(delay))
    changed["input_bindings"][0]["source"] = {"kind": "VARIABLE", "instance_key": "missing", "output_name": "value"}
    with pytest.raises(ValueError):
        resolve_instances([], [changed])
    changed["input_bindings"][0]["source"]["instance_key"] = "delay"
    with pytest.raises(ValueError):
        resolve_instances([], [changed])
