from dataclasses import replace
from datetime import UTC, datetime

import pyarrow as pa
import pytest
from onlyalpha_plugin_indicators.registration import TYPES, registrations, resolve_definition

from onlyalpha.calculation import (
    OnlyCalculationBackendKind,
    OnlyCalculationGraphDefinition,
    OnlyCalculationNodeDefinition,
    OnlyCalculationRegistry,
)
from onlyalpha.research import (
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyResearchCalculationBackendResolver,
    OnlyResearchCalculationError,
    OnlyResearchCalculationExecutionEvidenceStore,
    OnlyResearchCalculationExecutor,
    OnlyResearchCalculationResultStoreError,
)
from tests.research.calculation.support import snapshot


def _case(tmp_path):
    dataset = OnlyParquetResearchDatasetSnapshotStore(tmp_path / "datasets")
    candidate, partitions = snapshot()
    committed = dataset.commit(candidate, partitions)
    registry = OnlyCalculationRegistry()
    for registration in registrations():
        registry.register(registration)
    graph = OnlyCalculationGraphDefinition(
        (OnlyCalculationNodeDefinition(resolve_definition(TYPES[0], {"period": 2})),)
    )
    executor = OnlyResearchCalculationExecutor(dataset, OnlyResearchCalculationBackendResolver(registry))
    verified = executor._execute_verified(committed.snapshot_fingerprint, graph)
    result_store = OnlyParquetResearchCalculationResultStore(
        tmp_path / "results", dataset, audit_time=lambda: datetime(2026, 8, 24, tzinfo=UTC)
    )
    result = result_store.commit(verified.execution, graph)
    store = OnlyResearchCalculationExecutionEvidenceStore(tmp_path / "semantic")
    return graph, verified, result, store, dataset, committed.snapshot_fingerprint, result_store


def test_execution_evidence_is_verified_immutable_and_separate_from_result_identity(tmp_path) -> None:
    graph, verified, result, store, _, _, _ = _case(tmp_path)
    evidence = store._publish_verified(verified, result)

    assert evidence.calculation_fingerprint == result.manifest.calculation_fingerprint
    assert evidence.calculation_result_fingerprint == result.manifest.calculation_result_fingerprint
    assert evidence.result_content_fingerprint == result.manifest.result_content_fingerprint
    assert {item.node_fingerprint for item in evidence.research_implementation_bindings} == {
        item.fingerprint for item in graph.nodes
    }
    assert store.load_verified(evidence.evidence_fingerprint) == evidence
    assert store._publish_verified(verified, result) == evidence


def test_same_result_different_research_implementation_has_different_evidence(tmp_path) -> None:
    graph, verified, result, store, dataset, snapshot_fingerprint, _ = _case(tmp_path)
    first = store._publish_verified(verified, result)
    changed_registry = OnlyCalculationRegistry()
    for registration in registrations():
        if (
            registration.backend is OnlyCalculationBackendKind.RESEARCH
            and registration.type_definition.type_id == graph.nodes[0].definition.type_id
        ):
            manifest = registration.implementation_manifest
            assert manifest is not None
            resources = list(manifest.resources)
            resources[0] = replace(resources[0], byte_sha256="f" * 64)
            registration = replace(
                registration,
                implementation_manifest=replace(manifest, resources=tuple(resources)),
            )
        changed_registry.register(registration)
    second_verified = OnlyResearchCalculationExecutor(
        dataset, OnlyResearchCalculationBackendResolver(changed_registry)
    )._execute_verified(snapshot_fingerprint, graph)
    second = store._publish_verified(second_verified, result)

    assert first.calculation_result_fingerprint == second.calculation_result_fingerprint
    assert first.evidence_fingerprint != second.evidence_fingerprint
    with pytest.raises(OnlyResearchCalculationError) as ambiguous:
        store.require_for_result(result)
    assert ambiguous.value.code == "RESEARCH_EXECUTION_IDENTITY_MISMATCH"


def test_execution_evidence_rejects_graph_binding_set_mismatch(tmp_path) -> None:
    _, verified, result, store, _, _, _ = _case(tmp_path)
    public_claim = replace(verified.execution, research_implementation_bindings=())
    with pytest.raises(OnlyResearchCalculationError) as error:
        store._publish_verified(public_claim, result)  # type: ignore[arg-type]
    assert error.value.code == "RESEARCH_EXECUTION_PUBLICATION_UNAUTHORIZED"


def test_execution_evidence_corruption_fails_closed(tmp_path) -> None:
    _, verified, result, store, _, _, _ = _case(tmp_path)
    evidence = store._publish_verified(verified, result)
    target = (
        tmp_path
        / "semantic"
        / "calculation-execution-evidence"
        / "sha256"
        / evidence.evidence_fingerprint[:2]
        / evidence.evidence_fingerprint
    )
    (target / "unexpected").write_text("tamper", encoding="utf-8")

    with pytest.raises(OnlyResearchCalculationError) as error:
        store.load_verified(evidence.evidence_fingerprint)
    assert error.value.code == "RESEARCH_EXECUTION_EVIDENCE_CORRUPT"


def test_actually_executed_implementation_result_drift_remains_deterministic_conflict(tmp_path) -> None:
    graph, _, _, _, dataset, snapshot_fingerprint, result_store = _case(tmp_path)
    changed_registry = OnlyCalculationRegistry()
    for registration in registrations():
        if (
            registration.backend is OnlyCalculationBackendKind.RESEARCH
            and registration.type_definition.type_id == graph.nodes[0].definition.type_id
        ):
            delegate = registration.provider

            class _DriftingBackend:
                def __init__(self, backend):
                    self._backend = backend

                def execute(self, definition, inputs):
                    outputs = dict(self._backend.execute(definition, inputs))
                    name = definition.outputs[0].name
                    values = outputs[name].to_pylist()
                    values[-1] += 1
                    outputs[name] = pa.array(values, type=outputs[name].type)
                    return outputs

            registration = replace(registration, provider=_DriftingBackend(delegate))
        changed_registry.register(registration)
    drifted = OnlyResearchCalculationExecutor(
        dataset, OnlyResearchCalculationBackendResolver(changed_registry)
    ).execute(snapshot_fingerprint, graph)
    with pytest.raises(OnlyResearchCalculationResultStoreError) as error:
        result_store.commit(drifted, graph)
    assert error.value.code == "DETERMINISTIC_RESULT_CONFLICT"
