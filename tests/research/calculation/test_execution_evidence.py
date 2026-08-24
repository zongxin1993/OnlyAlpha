from dataclasses import replace
from datetime import UTC, datetime

import pytest
from onlyalpha_plugin_indicators.registration import TYPES, registrations, resolve_definition

from onlyalpha.calculation import OnlyCalculationGraphDefinition, OnlyCalculationNodeDefinition, OnlyCalculationRegistry
from onlyalpha.research import (
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyResearchCalculationBackendResolver,
    OnlyResearchCalculationError,
    OnlyResearchCalculationExecutionEvidenceStore,
    OnlyResearchCalculationExecutor,
    OnlyResearchCalculationImplementationBinding,
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
    execution = OnlyResearchCalculationExecutor(dataset, OnlyResearchCalculationBackendResolver(registry)).execute(
        committed.snapshot_fingerprint, graph
    )
    result = OnlyParquetResearchCalculationResultStore(
        tmp_path / "results", dataset, audit_time=lambda: datetime(2026, 8, 24, tzinfo=UTC)
    ).commit(execution, graph)
    store = OnlyResearchCalculationExecutionEvidenceStore(tmp_path / "semantic")
    return graph, execution, result, store


def test_execution_evidence_is_verified_immutable_and_separate_from_result_identity(tmp_path) -> None:
    graph, execution, result, store = _case(tmp_path)
    evidence = store.commit_execution(execution, result)

    assert evidence.calculation_fingerprint == result.manifest.calculation_fingerprint
    assert evidence.calculation_result_fingerprint == result.manifest.calculation_result_fingerprint
    assert evidence.result_content_fingerprint == result.manifest.result_content_fingerprint
    assert {item.node_fingerprint for item in evidence.research_implementation_bindings} == {
        item.fingerprint for item in graph.nodes
    }
    assert store.load_verified(evidence.evidence_fingerprint) == evidence
    assert store.commit_execution(execution, result) == evidence


def test_same_result_different_research_implementation_has_different_evidence(tmp_path) -> None:
    _, execution, result, store = _case(tmp_path)
    first = store.commit_execution(execution, result)
    changed = replace(
        execution,
        research_implementation_bindings=tuple(
            OnlyResearchCalculationImplementationBinding(item.node_fingerprint, "f" * 64)
            for item in execution.research_implementation_bindings
        ),
    )
    second = store.commit_execution(changed, result)

    assert first.calculation_result_fingerprint == second.calculation_result_fingerprint
    assert first.evidence_fingerprint != second.evidence_fingerprint
    with pytest.raises(OnlyResearchCalculationError) as ambiguous:
        store.require_for_result(result)
    assert ambiguous.value.code == "RESEARCH_EXECUTION_IDENTITY_MISMATCH"


def test_execution_evidence_rejects_graph_binding_set_mismatch(tmp_path) -> None:
    _, execution, result, store = _case(tmp_path)
    with pytest.raises(OnlyResearchCalculationError) as error:
        store.commit_execution(replace(execution, research_implementation_bindings=()), result)
    assert error.value.code == "RESEARCH_EXECUTION_IDENTITY_MISMATCH"


def test_execution_evidence_corruption_fails_closed(tmp_path) -> None:
    _, execution, result, store = _case(tmp_path)
    evidence = store.commit_execution(execution, result)
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
