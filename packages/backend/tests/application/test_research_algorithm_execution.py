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
