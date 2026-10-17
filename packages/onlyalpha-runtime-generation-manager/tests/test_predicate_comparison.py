from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from onlyalpha_runtime_generation_manager import OnlyLocalImmutableArtifactStore, OnlyRuntimeGenerationRegistry
from onlyalpha_runtime_generation_manager import predicate_comparison as comparison

from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCalculationTypeReference,
)
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.runtime.generation import (
    OnlyArtifactCalculationImplementation,
    OnlyArtifactSourceProvenanceAuthority,
    OnlyCoreExecutionIdentity,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
    OnlyRuntimeGenerationManifest,
    OnlyRuntimeGenerationValidationEvidence,
    OnlyRuntimeProviderBinding,
)
from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives

NOW = datetime(2026, 10, 17, tzinfo=UTC)


def setup_case(root: Path, *, integer: bool = False, literal: bool = False, type_id=None, parameters=None):
    calculations = OnlyCalculationRegistry()
    only_register_trading_predicate_primitives(calculations)
    reference = OnlyCalculationTypeReference(
        OnlyCalculationKind.PREDICATE,
        "onlyalpha.predicate.internal.compare.eq.integer.literal"
        if literal
        else "onlyalpha.predicate.internal.compare.eq.integer.refs"
        if integer
        else "onlyalpha.predicate.internal.boolean.not",
        "1",
    )
    if type_id is not None:
        reference = replace(reference, type_id=type_id)
    definition = calculations.rematerialize_definition(
        reference,
        parameters if parameters is not None else {"literal": 2**53 + 1, "literal_left": False} if literal else {},
        {
            key: OnlyCalculationReference(None, key, "bar.close")
            for key in (("left",) if literal else ("left", "right") if integer or type_id is not None else ("value",))
        },
    )
    registered = calculations.resolve(reference.kind, reference.type_id, "1", OnlyCalculationBackendKind.TRADING)
    implementations = (
        OnlyArtifactCalculationImplementation(
            "PREDICATE",
            reference.type_id,
            "1",
            "TRADING",
            registered.implementation_manifest.implementation_fingerprint,
        ),
    )
    manifest = OnlyRuntimeGenerationManifest(
        OnlyCoreExecutionIdentity("onlyalpha", "0.10.3", "a" * 64),
        ("b" * 64,),
        ("a" * 64,),
        (OnlyRuntimeProviderBinding("fixture", "1", "c" * 64, "a" * 64),),
        "d" * 64,
        implementations,
    )
    registry = OnlyRuntimeGenerationRegistry(root / "generation")
    registry.prepare(manifest, actor="test", occurred_at=NOW)
    registry.admit_ready(OnlyRuntimeGenerationValidationEvidence.from_manifest(manifest), actor="test", occurred_at=NOW)
    generation = manifest.runtime_generation_fingerprint
    registry.activate_for_new_work(expected_current=None, target=generation, actor="human", occurred_at=NOW)
    registry.bind_new_work_exact("work", generation, owner="DIAGNOSTIC_FIXTURE", actor="test", occurred_at=NOW)
    binding = registry.require_work_binding_evidence("work")
    content = struct.pack(
        "<16sHHIQQQIHHHHHH", b"\x7fELF\x02\x01\x01" + b"\0" * 9, 3, 183, 1, 0, 0, 0, 0, 64, 56, 0, 64, 0, 0
    )
    artifact = OnlyDistributionArtifactManifest(
        OnlyDistributionArtifactRole.SUPPORT,
        OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        "onlyalpha",
        "1" * 40,
        "onlyalpha-kernel",
        "0.10.3",
        "onlyalpha_kernel-0.10.3-aarch64-unknown-linux-gnu.elf",
        hashlib.sha256(content).hexdigest(),
        len(content),
    )
    store = OnlyLocalImmutableArtifactStore(root / "artifacts")
    store.put_once(artifact, content)
    return comparison.OnlyPredicateComparisonService(store, registry), definition, binding, artifact


def reply(request: bytes) -> bytes:
    lines = request.decode("ascii").splitlines()
    return (
        "\n".join(
            [
                lines[0],
                *[line + "\tOK\t" + result for line, result in zip(lines[1:], ("false", "true", "null"), strict=True)],
            ]
        )
        + "\n"
    ).encode()


def test_comparison_binds_exact_inputs_owners_and_both_implementations(tmp_path, monkeypatch):
    service, definition, binding, artifact = setup_case(tmp_path)
    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", lambda *args: None)
    monkeypatch.setattr(comparison, "_run_native", lambda content, request, target: reply(request))
    before = (tmp_path / "generation/generation-events.jsonl").read_bytes()
    result = service.observe(binding, definition, ((True,), (False,), (None,)), artifact)
    payload = json.loads(result.canonical_json)
    assert payload["status"] == "MATCH"
    assert payload["context"]["binding"]["binding_owner"] == "DIAGNOSTIC_FIXTURE"
    assert payload["context"]["definition_fingerprint"] == definition.fingerprint
    assert payload["context"]["native_artifact"]["artifact_sha256"] == artifact.artifact_sha256
    assert payload["python_outputs"] == [False, True, None]
    assert payload["python_implementation"] != artifact.artifact_sha256
    assert (tmp_path / "generation/generation-events.jsonl").read_bytes() == before
    # A fresh service/registry rechecks the same immutable work, without binding a new identity.
    restarted = comparison.OnlyPredicateComparisonService(
        service.artifacts, OnlyRuntimeGenerationRegistry(tmp_path / "generation")
    )
    assert restarted.observe(binding, definition, ((True,), (False,), (None,)), artifact) == result


@pytest.mark.parametrize("integer,literal", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("mutation", ["value", "identity", "order", "rejection", "context"])
def test_well_formed_output_mutations_are_diagnostic_mismatches(tmp_path, monkeypatch, mutation, integer, literal):
    service, definition, binding, artifact = setup_case(tmp_path, integer=integer, literal=literal)
    rows = (
        ((2**53,), (2**53 + 1,), (None,))
        if literal
        else ((2**53, 2**53 + 1), (2**128, 2**128), (None, 1))
        if integer
        else ((True,), (False,), (None,))
    )
    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", lambda *args: None)

    def mutated(content, request, target):
        response = reply(request).decode("ascii")
        if mutation == "value":
            response = response.replace("\tOK\tfalse", "\tOK\ttrue", 1)
        elif mutation == "identity":
            response = (
                response.replace(".compare.eq.integer.", ".compare.ne.integer.", 1)
                if integer
                else response.replace(".boolean.not", ".terminal.entry_signal", 1)
            )
        elif mutation == "order":
            lines = response.splitlines()
            lines[1], lines[2] = lines[2], lines[1]
            response = "\n".join(lines) + "\n"
        elif mutation == "rejection":
            response = response.replace("\tOK\tfalse", "\tERROR\tUnknownVersion", 1)
        else:
            response = response.replace(response.splitlines()[0].split("\t")[1], "0" * 64, 1)
        return response.encode()

    monkeypatch.setattr(comparison, "_run_native", mutated)
    assert json.loads(service.observe(binding, definition, rows, artifact).canonical_json)["status"] == "MISMATCH"


@pytest.mark.parametrize(
    "fault",
    [
        "timeout",
        "wait_timeout",
        "crash",
        "malformed",
        "missing",
        "owner",
        "generation",
        "definition",
        "inputs",
        "hosted",
    ],
)
@pytest.mark.parametrize("integer,literal", [(False, False), (True, False), (True, True)])
def test_unavailable_proof_never_becomes_match_or_retries(tmp_path, monkeypatch, fault, integer, literal):
    service, definition, binding, artifact = setup_case(tmp_path, integer=integer, literal=literal)
    calls = []

    def native(content, request, target):
        calls.append(1)
        if fault == "timeout":
            raise TimeoutError("injected deadline")
        if fault == "wait_timeout":
            raise comparison.subprocess.TimeoutExpired("diagnostic", 3)
        if fault == "crash":
            raise OSError("injected process failure")
        return b"broken" if fault == "malformed" else reply(request)

    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", lambda *args: None)
    monkeypatch.setattr(comparison, "_run_native", native)
    rows = (
        ((2**53,), (2**53 + 1,), (None,))
        if literal
        else ((2**53, 2**53 + 1), (2**128, 2**128), (None, 1))
        if integer
        else ((True,), (False,), (None,))
    )
    if fault == "missing":
        service.artifacts.verify_exact(artifact).unlink()
    if fault == "owner":
        binding = replace(binding, binding_owner="FOREIGN_OWNER")
    if fault == "generation":
        binding = replace(binding, runtime_generation_fingerprint="e" * 64)
    if fault == "definition":
        definition = replace(definition, extensions={"foreign": True})
    if fault == "inputs":
        rows = ((True,),) if literal else ((1,),)
    if fault == "hosted":

        def rejected(*args):
            raise RuntimeError("RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH")

        monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", rejected)
    before = (tmp_path / "generation/generation-events.jsonl").read_bytes()
    payload = json.loads(service.observe(binding, definition, rows, artifact).canonical_json)
    assert payload["status"] == "UNAVAILABLE"
    if fault == "malformed":
        assert payload["native_output_sha256"] == hashlib.sha256(b"broken").hexdigest()
    assert len(calls) <= 1
    if fault == "inputs":
        assert calls == []
    assert (tmp_path / "generation/generation-events.jsonl").read_bytes() == before


def test_busy_observation_is_explicit_and_never_queues_native_work(tmp_path, monkeypatch):
    service, definition, binding, artifact = setup_case(tmp_path)
    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", lambda *args: None)
    monkeypatch.setattr(comparison, "_run_native", lambda *args: pytest.fail("busy diagnostic started work"))
    with comparison._COMPARISON_SLOT:
        payload = json.loads(service.observe(binding, definition, ((True,),), artifact).canonical_json)
    assert payload["status"] == "UNAVAILABLE"
    assert payload["reason"] == "PREDICATE_COMPARISON_BUSY"


def test_invalid_nonfinite_input_produces_bounded_unavailable_diagnostic(tmp_path):
    service, definition, binding, artifact = setup_case(tmp_path)
    result = service.observe(binding, definition, ((float("nan"),),), artifact)
    payload = json.loads(result.canonical_json)
    assert payload["status"] == "UNAVAILABLE"
    assert payload["context"]["inputs"] is None


@pytest.mark.parametrize(
    "row",
    [
        "0\tnot a type\t1\ttrue\tOK\tfalse",
        "0\tonlyalpha.predicate.internal.boolean.not\tbad version\ttrue\tOK\tfalse",
        "000\tonlyalpha.predicate.internal.boolean.not\t1\ttrue\tOK\tfalse",
    ],
)
def test_malformed_response_identity_is_unavailable_rather_than_semantic_mismatch(row):
    frame = ("ONLYALPHA_PREDICATE_DIAGNOSTIC_V4\t" + "a" * 64 + "\n" + row + "\n").encode()
    with pytest.raises(ValueError, match="RESPONSE_INVALID"):
        comparison._validate_response(frame, 1)


@pytest.mark.parametrize("literal", [False, True])
def test_proof_guard_completion_failure_withdraws_an_otherwise_matching_result(tmp_path, monkeypatch, literal):
    from contextlib import contextmanager

    service, definition, binding, artifact = setup_case(tmp_path, integer=literal, literal=literal)
    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", lambda *args: None)
    monkeypatch.setattr(comparison, "_run_native", lambda content, request, target: reply(request))
    original = OnlyRuntimeGenerationRegistry.hold_work_binding_evidence

    @contextmanager
    def failing_guard(owner, work_id):
        with original(owner, work_id) as proof:
            yield proof
        raise OSError("CONTROLLED_PROOF_COMPLETION_FAILURE")

    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "hold_work_binding_evidence", failing_guard)
    result = service.observe(
        binding, definition, (((2**53,), (2**53 + 1,), (None,)) if literal else ((True,), (False,), (None,))), artifact
    )
    assert json.loads(result.canonical_json)["status"] == "UNAVAILABLE"


def test_activation_switch_keeps_bound_comparison_exact_and_released_work_unavailable(tmp_path, monkeypatch):
    service, definition, binding, artifact = setup_case(tmp_path)
    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", lambda *args: None)
    monkeypatch.setattr(comparison, "_run_native", lambda content, request, target: reply(request))
    old = service.generations.require_work_generation(binding.work_id, binding.runtime_generation_fingerprint)
    next_generation = replace(
        old,
        core_execution=OnlyCoreExecutionIdentity("onlyalpha", "0.10.3", "e" * 64),
        artifact_manifest_fingerprints=("f" * 64,),
        artifact_sha256s=("e" * 64,),
        providers=(OnlyRuntimeProviderBinding("next-fixture", "1", "d" * 64, "e" * 64),),
    )
    service.generations.prepare(next_generation, actor="fixture", occurred_at=NOW)
    service.generations.admit_ready(
        OnlyRuntimeGenerationValidationEvidence.from_manifest(next_generation), actor="fixture", occurred_at=NOW
    )
    service.generations.activate_for_new_work(
        expected_current=binding.runtime_generation_fingerprint,
        target=next_generation.runtime_generation_fingerprint,
        actor="human",
        occurred_at=NOW,
    )
    observed = json.loads(service.observe(binding, definition, ((True,), (False,), (None,)), artifact).canonical_json)
    assert observed["status"] == "MATCH"
    assert (
        observed["context"]["python_generation"]["runtime_generation_fingerprint"]
        == binding.runtime_generation_fingerprint
    )
    service.generations.release_work(binding.work_id, actor="human", occurred_at=NOW)
    assert (
        json.loads(service.observe(binding, definition, ((True,), (False,), (None,)), artifact).canonical_json)[
            "status"
        ]
        == "UNAVAILABLE"
    )


def test_comparison_observation_is_not_formal_equivalence_evidence(tmp_path):
    from onlyalpha.calculation.equivalence import (
        OnlyCalculationEquivalenceError,
        OnlyCalculationEquivalenceEvidenceV2Store,
    )

    observation = comparison.OnlyPredicateComparisonObservation('{"status":"MATCH"}')
    with pytest.raises(OnlyCalculationEquivalenceError, match="EQUIVALENCE_CERTIFICATION_FAILED"):
        OnlyCalculationEquivalenceEvidenceV2Store(tmp_path).publish_certified(observation)


def test_integer_comparison_preserves_exact_context_and_restart_binding(tmp_path, monkeypatch):
    service, definition, binding, artifact = setup_case(tmp_path, integer=True)
    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", lambda *args: None)
    monkeypatch.setattr(comparison, "_run_native", lambda content, request, target: reply(request))
    rows = ((2**53, 2**53 + 1), (2**128, 2**128), (None, 1))
    before = (service.generations.root / "generation-events.jsonl").read_bytes()
    observation = service.observe(binding, definition, rows, artifact)
    result = json.loads(observation.canonical_json)
    assert result["status"] == "MATCH"
    assert result["context"]["inputs"] == [[str(2**53), str(2**53 + 1)], [str(2**128), str(2**128)], [None, "1"]]
    assert result["context"]["input_encoding"] == "INTEGER_DECIMAL_TEXT"
    assert result["context"]["schema_version"] == 4
    restarted = comparison.OnlyPredicateComparisonService(
        service.artifacts, OnlyRuntimeGenerationRegistry(service.generations.root)
    )
    assert restarted.observe(binding, definition, rows, artifact) == observation
    assert (service.generations.root / "generation-events.jsonl").read_bytes() == before
    service.generations.release_work(binding.work_id, actor="human", occurred_at=NOW)
    assert json.loads(service.observe(binding, definition, rows, artifact).canonical_json)["status"] == "UNAVAILABLE"


@pytest.mark.parametrize(
    "rows",
    [
        ((True, 1),),
        ((1.0, 1),),
        (("1", 1),),
        ((10**256, 1),),
        ((10**10000, 1),),
        tuple((10**255, 10**255) for _ in range(128)),
    ],
)
def test_integer_invalid_or_exhausted_input_never_starts_native_work(tmp_path, monkeypatch, rows):
    service, definition, binding, artifact = setup_case(tmp_path, integer=True)
    monkeypatch.setattr(comparison, "_run_native", lambda *args: pytest.fail("invalid input launched native work"))
    result = json.loads(service.observe(binding, definition, rows, artifact).canonical_json)
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] in ("PREDICATE_COMPARISON_INPUT_INVALID", "PREDICATE_COMPARISON_INPUT_LIMIT")


def test_integer_precision_mutation_is_a_mismatch_without_ledger_writes(tmp_path, monkeypatch):
    service, definition, binding, artifact = setup_case(tmp_path, integer=True)
    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", lambda *args: None)

    def rounded(content, request, target):
        return reply(request).replace(str(2**53 + 1).encode(), str(2**53).encode(), 1)

    monkeypatch.setattr(comparison, "_run_native", rounded)
    before = (service.generations.root / "generation-events.jsonl").read_bytes()
    result = service.observe(binding, definition, ((2**53, 2**53 + 1), (2**128, 2**128), (None, 1)), artifact)
    assert json.loads(result.canonical_json)["status"] == "MISMATCH"
    assert (service.generations.root / "generation-events.jsonl").read_bytes() == before


def test_integer_transport_digit_limit_preserves_both_signed_boundaries():
    for value in (10**256 - 1, -(10**256 - 1)):
        assert comparison._valid_input(value, True)
        assert comparison._valid_token(comparison._token(value))
    for value in (10**256, -(10**256)):
        assert not comparison._valid_input(value, True)
        assert not comparison._valid_token(str(value))


def test_literal_comparison_binds_exact_configuration_and_rechecks_restart(tmp_path, monkeypatch):
    service, definition, binding, artifact = setup_case(tmp_path, integer=True, literal=True)
    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", lambda *args: None)
    requests = []

    def native(content, request, target):
        requests.append(request)
        return reply(request)

    monkeypatch.setattr(comparison, "_run_native", native)
    rows = ((2**53,), (2**53 + 1,), (None,))
    before = (service.generations.root / "generation-events.jsonl").read_bytes()
    result = service.observe(binding, definition, rows, artifact)
    payload = json.loads(result.canonical_json)
    assert payload["status"] == "MATCH"
    assert payload["context"]["definition_fingerprint"] == definition.fingerprint
    assert payload["context"]["literal_configuration"] == {"literal": str(2**53 + 1), "literal_left": False}
    assert payload["context"]["inputs"] == [[str(2**53)], [str(2**53 + 1)], [None]]
    assert requests[0].splitlines()[1].split(b"\t")[3:] == [str(2**53 + 1).encode(), b"false", str(2**53).encode()]
    restarted = comparison.OnlyPredicateComparisonService(
        service.artifacts, OnlyRuntimeGenerationRegistry(service.generations.root)
    )
    assert restarted.observe(binding, definition, rows, artifact) == result
    assert (service.generations.root / "generation-events.jsonl").read_bytes() == before
    service.generations.release_work(binding.work_id, actor="human", occurred_at=NOW)
    assert json.loads(service.observe(binding, definition, rows, artifact).canonical_json)["status"] == "UNAVAILABLE"


@pytest.mark.parametrize("field", ["literal", "literal_left"])
def test_literal_configuration_echo_mutation_is_mismatch_even_if_outputs_match(tmp_path, monkeypatch, field):
    service, definition, binding, artifact = setup_case(tmp_path, integer=True, literal=True)
    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", lambda *args: None)

    def mutated(content, request, target):
        lines = reply(request).decode().splitlines()
        fields = lines[1].split("\t")
        fields[3 if field == "literal" else 4] = str(2**53) if field == "literal" else "true"
        lines[1] = "\t".join(fields)
        return ("\n".join(lines) + "\n").encode()

    monkeypatch.setattr(comparison, "_run_native", mutated)
    before = (service.generations.root / "generation-events.jsonl").read_bytes()
    assert (
        json.loads(service.observe(binding, definition, ((2**53,), (2**53 + 1,), (None,)), artifact).canonical_json)[
            "status"
        ]
        == "MISMATCH"
    )
    assert (service.generations.root / "generation-events.jsonl").read_bytes() == before


@pytest.mark.parametrize(
    "parameters",
    [
        {"literal": 10**10000, "literal_left": False},
        {"literal": 10**256, "literal_left": False},
        {"literal": True, "literal_left": False},
        {"literal": "1", "literal_left": False},
        {"literal": 1.0, "literal_left": False},
        {"literal": None, "literal_left": False},
        {"literal": 1, "literal_left": "true"},
        {"literal": 1},
    ],
)
def test_invalid_literal_configuration_is_bounded_unavailable_before_proof(tmp_path, monkeypatch, parameters):
    service, definition, binding, artifact = setup_case(tmp_path, integer=True, literal=True)
    definition = replace(definition, parameters=parameters)
    monkeypatch.setattr(
        OnlyRuntimeGenerationRegistry,
        "verify_hosted_generation",
        lambda *args: pytest.fail("invalid literal reached proof"),
    )
    monkeypatch.setattr(comparison, "_run_native", lambda *args: pytest.fail("invalid literal launched native work"))
    result = json.loads(service.observe(binding, definition, ((1,),), artifact).canonical_json)
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "PREDICATE_COMPARISON_CONFIGURATION_INVALID"
    assert result["context"]["definition"] is None
    assert result["context"]["definition_fingerprint"] is None


def test_repeated_literal_is_included_in_the_total_frame_budget(tmp_path, monkeypatch):
    service, definition, binding, artifact = setup_case(tmp_path, integer=True, literal=True)
    definition = replace(definition, parameters={"literal": 10**255, "literal_left": False})
    monkeypatch.setattr(
        OnlyRuntimeGenerationRegistry,
        "verify_hosted_generation",
        lambda *args: pytest.fail("oversized frame reached proof"),
    )
    monkeypatch.setattr(comparison, "_run_native", lambda *args: pytest.fail("oversized frame launched native work"))
    result = json.loads(
        service.observe(binding, definition, tuple((10**255,) for _ in range(128)), artifact).canonical_json
    )
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "PREDICATE_COMPARISON_INPUT_LIMIT"


@pytest.mark.parametrize("literal_left", [False, True])
@pytest.mark.parametrize("value", [10**256 - 1, -(10**256 - 1)])
def test_literal_transport_admits_both_signed_256_digit_boundaries(tmp_path, monkeypatch, literal_left, value):
    service, definition, binding, artifact = setup_case(tmp_path, integer=True, literal=True)
    definition = replace(definition, parameters={"literal": value, "literal_left": literal_left})
    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", lambda *args: None)

    def native(content, request, target):
        assert request.splitlines()[1].split(b"\t")[3] == str(value).encode()
        line = request.splitlines()[1]
        return request.splitlines()[0] + b"\n" + line + b"\tOK\ttrue\n"

    monkeypatch.setattr(comparison, "_run_native", native)
    result = json.loads(service.observe(binding, definition, ((value,),), artifact).canonical_json)
    assert result["status"] == "MATCH"
    assert result["context"]["literal_configuration"] == {"literal": str(value), "literal_left": literal_left}


@pytest.mark.parametrize("configuration", ["null\tfalse", "1\tnull", "true\tfalse", "1\t0"])
def test_malformed_literal_reply_configuration_is_unavailable(configuration):
    frame = (
        "ONLYALPHA_PREDICATE_DIAGNOSTIC_V4\t"
        + "a" * 64
        + "\n0\tonlyalpha.predicate.internal.compare.eq.integer.literal\t1\t"
        + configuration
        + "\t1\tOK\ttrue\n"
    ).encode()
    with pytest.raises(ValueError, match="RESPONSE_INVALID"):
        comparison._validate_response(frame, 1)


@pytest.mark.parametrize("old", ["V1", "V2", "V3"])
def test_old_diagnostic_replies_are_unavailable_without_substitution(tmp_path, monkeypatch, old):
    service, definition, binding, artifact = setup_case(tmp_path, integer=True, literal=True)
    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", lambda *args: None)
    calls = []

    def native(content, request, target):
        calls.append(request)
        return reply(request).replace(b"DIAGNOSTIC_V4", ("DIAGNOSTIC_" + old).encode())

    monkeypatch.setattr(comparison, "_run_native", native)
    before = (service.generations.root / "generation-events.jsonl").read_bytes()
    result = json.loads(
        service.observe(binding, definition, ((2**53,), (2**53 + 1,), (None,)), artifact).canonical_json
    )
    assert result["status"] == "UNAVAILABLE"
    assert len(calls) == 1
    assert result["context"]["native_artifact"] == artifact.to_dict()
    assert (service.generations.root / "generation-events.jsonl").read_bytes() == before


@pytest.mark.parametrize("family", ["boolean", "string"])
@pytest.mark.parametrize("operator", ["eq", "ne"])
@pytest.mark.parametrize("literal", [False, True])
@pytest.mark.parametrize("position", [False, True])
def test_scalar_equality_compares_exact_configuration_and_restart(
    tmp_path, monkeypatch, family, operator, literal, position
):
    value, other = (False, True) if family == "boolean" else ("a\t\0e\u0301😀", "a\t\0é😀")
    service, definition, binding, artifact = setup_case(
        tmp_path,
        integer=True,
        literal=literal,
        type_id=f"onlyalpha.predicate.internal.compare.{operator}.{family}.{'literal' if literal else 'refs'}",
        parameters={"literal": value, "literal_left": position} if literal else {},
    )
    first, second = (other, value) if operator == "eq" else (value, other)
    rows = ((first,), (second,), (None,)) if literal else ((first, value), (second, value), (None, value))
    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", lambda *args: None)
    monkeypatch.setattr(comparison, "_run_native", lambda content, request, target: reply(request))
    before = (service.generations.root / "generation-events.jsonl").read_bytes()
    observed = service.observe(binding, definition, rows, artifact)
    payload = json.loads(observed.canonical_json)
    assert payload["status"] == "MATCH", payload
    assert payload["python_outputs"] == [False, True, None]
    assert payload["context"]["definition_fingerprint"] == definition.fingerprint
    assert payload["context"]["schema_version"] == 4
    if family == "string":
        assert payload["context"]["input_encoding"] == "UTF8_HEX"
        assert payload["context"]["inputs"][0][0] == "utf8:" + first.encode().hex()
    if literal:
        assert payload["context"]["literal_configuration"] == {
            "literal": "utf8:" + value.encode().hex() if family == "string" else "false",
            "literal_left": position,
        }
    restarted = comparison.OnlyPredicateComparisonService(
        service.artifacts, OnlyRuntimeGenerationRegistry(service.generations.root)
    )
    assert restarted.observe(binding, definition, rows, artifact) == observed
    assert (service.generations.root / "generation-events.jsonl").read_bytes() == before


@pytest.mark.parametrize("literal", [False, True])
@pytest.mark.parametrize("value", [True, 1, b"text", "\ud800", "x" * 4097, "😀" * 1025])
def test_scalar_string_invalid_values_are_rejected_before_proof(tmp_path, monkeypatch, literal, value):
    service, definition, binding, artifact = setup_case(
        tmp_path,
        integer=True,
        literal=literal,
        type_id=f"onlyalpha.predicate.internal.compare.eq.string.{'literal' if literal else 'refs'}",
        parameters={"literal": "x", "literal_left": False} if literal else {},
    )
    if literal:
        definition = replace(definition, parameters={"literal": value, "literal_left": False})
    monkeypatch.setattr(
        OnlyRuntimeGenerationRegistry,
        "verify_hosted_generation",
        lambda *args: pytest.fail("invalid string reached proof"),
    )
    result = json.loads(
        service.observe(binding, definition, (("x",),) if literal else ((value, "x"),), artifact).canonical_json
    )
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == (
        "PREDICATE_COMPARISON_CONFIGURATION_INVALID" if literal else "PREDICATE_COMPARISON_INPUT_INVALID"
    )
    assert result["context"]["definition"] is None


@pytest.mark.parametrize(
    "token", ["utf8:0", "utf8:FF", "utf8:ff", "utf8:eda080", "utf8:c080", "utf8:00 00", "utf8:" + "00" * 4097]
)
def test_malformed_utf8_reply_is_unavailable(token):
    frame = (
        "ONLYALPHA_PREDICATE_DIAGNOSTIC_V4\t"
        + "a" * 64
        + "\n0\tonlyalpha.predicate.internal.compare.eq.string.refs\t1\t"
        + token
        + "\tutf8:78\tOK\ttrue\n"
    ).encode()
    with pytest.raises(ValueError, match="RESPONSE_INVALID"):
        comparison._validate_response(frame, 1)


@pytest.mark.parametrize("family", ["boolean", "string"])
@pytest.mark.parametrize("literal", [False, True])
@pytest.mark.parametrize(
    "fault", ["owner", "generation", "missing", "hosted", "released", "timeout", "crash", "malformed", "guard"]
)
def test_scalar_equality_proof_failure_is_unavailable_without_writes(tmp_path, monkeypatch, family, literal, fault):
    from contextlib import contextmanager

    value = False if family == "boolean" else "e\u0301\0😀"
    service, definition, binding, artifact = setup_case(
        tmp_path,
        integer=True,
        literal=literal,
        type_id=f"onlyalpha.predicate.internal.compare.eq.{family}.{'literal' if literal else 'refs'}",
        parameters={"literal": value, "literal_left": False} if literal else {},
    )
    rows = ((value,),) if literal else ((value, value),)
    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", lambda *args: None)
    calls = []

    def native(content, request, target):
        calls.append(1)
        if fault == "timeout":
            raise TimeoutError("CONTROLLED_DEADLINE")
        if fault == "crash":
            raise OSError("CONTROLLED_CRASH")
        return b"broken" if fault == "malformed" else request.rstrip(b"\n") + b"\tOK\ttrue\n"

    monkeypatch.setattr(comparison, "_run_native", native)
    if fault == "owner":
        binding = replace(binding, binding_owner="FOREIGN")
    elif fault == "generation":
        binding = replace(binding, runtime_generation_fingerprint="e" * 64)
    elif fault == "missing":
        service.artifacts.verify_exact(artifact).unlink()
    elif fault == "hosted":

        def reject(*args):
            raise RuntimeError("CONTROLLED_HOSTED_FAILURE")

        monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", reject)
    elif fault == "released":
        service.generations.release_work(binding.work_id, actor="human", occurred_at=NOW)
    elif fault == "guard":
        original = OnlyRuntimeGenerationRegistry.hold_work_binding_evidence

        @contextmanager
        def fail_after(owner, work_id):
            with original(owner, work_id) as evidence:
                yield evidence
            raise OSError("CONTROLLED_GUARD_COMPLETION_FAILURE")

        monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "hold_work_binding_evidence", fail_after)
    before = (service.generations.root / "generation-events.jsonl").read_bytes()
    payload = json.loads(service.observe(binding, definition, rows, artifact).canonical_json)
    assert payload["status"] == "UNAVAILABLE"
    assert len(calls) == (1 if fault in ("timeout", "crash", "malformed", "guard") else 0)
    assert (service.generations.root / "generation-events.jsonl").read_bytes() == before


@pytest.mark.parametrize("family", ["boolean", "string"])
@pytest.mark.parametrize("mutation", ["literal", "position", "input", "type", "context"])
def test_scalar_equality_exact_echo_mutations_are_mismatches_even_with_equal_outputs(
    tmp_path, monkeypatch, family, mutation
):
    value = False if family == "boolean" else "é"
    token = "false" if family == "boolean" else "utf8:c3a9"
    changed = "true" if family == "boolean" else "utf8:65cc81"
    service, definition, binding, artifact = setup_case(
        tmp_path,
        literal=True,
        type_id=f"onlyalpha.predicate.internal.compare.eq.{family}.literal",
        parameters={"literal": value, "literal_left": False},
    )
    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", lambda *args: None)

    def native(content, request, target):
        lines = request.decode().splitlines()
        fields = lines[1].split("\t")
        assert fields[3] == token
        if mutation == "literal":
            fields[3] = changed
        elif mutation == "position":
            fields[4] = "true"
        elif mutation == "input":
            fields[5] = changed
        elif mutation == "type":
            fields[1] = fields[1].replace(".eq.", ".ne.")
        else:
            lines[0] = lines[0].replace(lines[0].split("\t")[1], "0" * 64)
        # All operands are missing: changing literal/position cannot change the output.
        return (lines[0] + "\n" + "\t".join(fields) + "\tOK\tnull\n").encode()

    monkeypatch.setattr(comparison, "_run_native", native)
    result = json.loads(service.observe(binding, definition, ((None,),), artifact).canonical_json)
    assert result["status"] == "MISMATCH"


@pytest.mark.parametrize("value", ["", "null", "\0\t\n😀", "x" * 4096, "😀" * 1024])
@pytest.mark.parametrize("literal", [False, True])
def test_string_transport_preserves_empty_controls_and_maximum_utf8_bytes(tmp_path, monkeypatch, value, literal):
    service, definition, binding, artifact = setup_case(
        tmp_path,
        integer=True,
        literal=literal,
        type_id=f"onlyalpha.predicate.internal.compare.eq.string.{'literal' if literal else 'refs'}",
        parameters={"literal": value, "literal_left": True} if literal else {},
    )
    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", lambda *args: None)

    def native(content, request, target):
        assert b"utf8:" + value.encode().hex().encode() in request
        return request.rstrip(b"\n") + b"\tOK\ttrue\n"

    monkeypatch.setattr(comparison, "_run_native", native)
    rows = ((value,),) if literal else ((value, value),)
    result = json.loads(service.observe(binding, definition, rows, artifact).canonical_json)
    assert result["status"] == "MATCH"


def test_repeated_string_configuration_exhausts_frame_budget_before_proof(tmp_path, monkeypatch):
    service, definition, binding, artifact = setup_case(
        tmp_path,
        literal=True,
        type_id="onlyalpha.predicate.internal.compare.eq.string.literal",
        parameters={"literal": "x" * 4096, "literal_left": False},
    )
    monkeypatch.setattr(
        OnlyRuntimeGenerationRegistry,
        "verify_hosted_generation",
        lambda *args: pytest.fail("oversized frame reached proof"),
    )
    result = json.loads(service.observe(binding, definition, tuple(("",) for _ in range(128)), artifact).canonical_json)
    assert result["status"] == "UNAVAILABLE"
    assert result["reason"] == "PREDICATE_COMPARISON_INPUT_LIMIT"


@pytest.mark.parametrize(
    "family,layout,tokens",
    [
        ("integer", "literal", "utf8:78\tfalse\t0"),
        ("integer", "refs", "utf8:78\t0"),
        ("boolean", "refs", "0\tfalse"),
        ("boolean", "literal", "false\tfalse\tutf8:78"),
        ("string", "refs", "true\tutf8:78"),
    ],
)
def test_cross_family_reply_tokens_are_malformed_not_mismatches(family, layout, tokens):
    frame = (
        "ONLYALPHA_PREDICATE_DIAGNOSTIC_V4\t"
        + "a" * 64
        + f"\n0\tonlyalpha.predicate.internal.compare.eq.{family}.{layout}\t1\t{tokens}\tOK\ttrue\n"
    ).encode()
    with pytest.raises(ValueError, match="RESPONSE_INVALID"):
        comparison._validate_response(frame, 1)
