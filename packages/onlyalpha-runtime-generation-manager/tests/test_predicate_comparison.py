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


def setup_case(root: Path):
    calculations = OnlyCalculationRegistry()
    only_register_trading_predicate_primitives(calculations)
    reference = OnlyCalculationTypeReference(
        OnlyCalculationKind.PREDICATE, "onlyalpha.predicate.internal.boolean.not", "1"
    )
    definition = calculations.rematerialize_definition(
        reference, {}, {"value": OnlyCalculationReference(None, "value", "bar.close")}
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


@pytest.mark.parametrize("mutation", ["value", "identity", "order", "rejection", "context"])
def test_well_formed_output_mutations_are_diagnostic_mismatches(tmp_path, monkeypatch, mutation):
    service, definition, binding, artifact = setup_case(tmp_path)
    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", lambda *args: None)

    def mutated(content, request, target):
        response = reply(request).decode("ascii")
        if mutation == "value":
            response = response.replace("\tOK\tfalse", "\tOK\ttrue", 1)
        elif mutation == "identity":
            response = response.replace(".boolean.not", ".terminal.entry_signal", 1)
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
    assert (
        json.loads(service.observe(binding, definition, ((True,), (False,), (None,)), artifact).canonical_json)[
            "status"
        ]
        == "MISMATCH"
    )


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
def test_unavailable_proof_never_becomes_match_or_retries(tmp_path, monkeypatch, fault):
    service, definition, binding, artifact = setup_case(tmp_path)
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
    rows = ((True,), (False,), (None,))
    if fault == "missing":
        service.artifacts.verify_exact(artifact).unlink()
    if fault == "owner":
        binding = replace(binding, binding_owner="FOREIGN_OWNER")
    if fault == "generation":
        binding = replace(binding, runtime_generation_fingerprint="e" * 64)
    if fault == "definition":
        definition = replace(definition, extensions={"foreign": True})
    if fault == "inputs":
        rows = ((1,),)
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
    frame = ("ONLYALPHA_PREDICATE_DIAGNOSTIC_V1\t" + "a" * 64 + "\n" + row + "\n").encode()
    with pytest.raises(ValueError, match="RESPONSE_INVALID"):
        comparison._validate_response(frame, 1)


def test_proof_guard_completion_failure_withdraws_an_otherwise_matching_result(tmp_path, monkeypatch):
    from contextlib import contextmanager

    service, definition, binding, artifact = setup_case(tmp_path)
    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "verify_hosted_generation", lambda *args: None)
    monkeypatch.setattr(comparison, "_run_native", lambda content, request, target: reply(request))
    original = OnlyRuntimeGenerationRegistry.hold_work_binding_evidence

    @contextmanager
    def failing_guard(owner, work_id):
        with original(owner, work_id) as proof:
            yield proof
        raise OSError("CONTROLLED_PROOF_COMPLETION_FAILURE")

    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "hold_work_binding_evidence", failing_guard)
    result = service.observe(binding, definition, ((True,), (False,), (None,)), artifact)
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
