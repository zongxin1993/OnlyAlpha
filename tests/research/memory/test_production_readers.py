"""Exact reference verification uses retained owning facts, never copied facets."""

from __future__ import annotations

from pathlib import Path

import pytest
from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

from onlyalpha.backtest.evidence import OnlyBacktestEvidenceStore
from onlyalpha.research.memory.production import SUPPORTED_REFERENCE_KINDS, OnlyExperimentMemoryReferenceReadersV1
from onlyalpha.research.memory.projector import OnlyMemoryReferenceKind
from onlyalpha.research.memory.source_manifest import OnlyMemoryProjectionError
from onlyalpha.research.search.parameter.store import OnlyJsonParameterSearchStore
from onlyalpha.research.search.symbolic.store import OnlyJsonSymbolicSearchStore
from onlyalpha.strategy.qualification_store import OnlyQualificationPolicyStore
from tests.strategy.test_strategy_freeze import _freeze_case


class _UnavailableCatalog:
    def load_verified_catalog_descriptor(self, fingerprint: str) -> dict[str, object]:
        raise RuntimeError(f"catalog unavailable: {fingerprint}")


class _UnavailableAuthoringGenerationAuthority:
    def load_descriptor_verified(self, fingerprint: str) -> dict[str, object]:
        raise RuntimeError(f"authoring generation unavailable: {fingerprint}")


def test_production_reference_kind_contract_is_exhaustive() -> None:
    assert set(OnlyMemoryReferenceKind) == SUPPORTED_REFERENCE_KINDS
    assert len(SUPPORTED_REFERENCE_KINDS) == 14


def test_real_dataset_calculation_graph_and_missing_reference_fail_closed(tmp_path: Path) -> None:
    service, _, candidate, _, _ = _freeze_case(tmp_path)
    results = service._research_results
    cut = results.capture_closed_cut()
    observations = results.iter_closed_cut_observations_verified(cut.cut_fingerprint)
    assert len(observations) == 1
    owners = OnlyExperimentMemoryReferenceReadersV1(
        service._datasets,
        _UnavailableCatalog(),
        OnlyJsonSymbolicSearchStore(tmp_path / "semantic"),
        OnlyJsonParameterSearchStore(tmp_path / "semantic"),
        service._calculation_results,
        OnlyRuntimeGenerationRegistry(tmp_path / "runtime-generations"),
        _UnavailableAuthoringGenerationAuthority(),
        OnlyQualificationPolicyStore(tmp_path / "semantic"),
        OnlyBacktestEvidenceStore(tmp_path),
    )
    reader = owners.for_observations(observations)
    graph = candidate.graph_fingerprint
    dataset = observations[0].canonical_payload["dataset_snapshot_fingerprint"]
    assert reader("CALCULATION_GRAPH", graph)["graph_fingerprint"] == graph
    assert reader("DATASET_SNAPSHOT", dataset)["snapshot_fingerprint"] == dataset
    with pytest.raises(OnlyMemoryProjectionError, match="REFERENCE_AUTHORITY_UNAVAILABLE"):
        reader("CALCULATION_GRAPH", "0" * 64)
    with pytest.raises(OnlyMemoryProjectionError, match="REFERENCE_AUTHORITY_UNAVAILABLE"):
        reader("DATASET_SNAPSHOT", "0" * 64)
    with pytest.raises(OnlyMemoryProjectionError, match="REFERENCE_AUTHORITY_UNAVAILABLE"):
        reader("CATALOG_GENERATION", "0" * 64)

    with pytest.raises(OnlyMemoryProjectionError, match="REFERENCE_AUTHORITY_UNAVAILABLE"):
        reader("NOT_A_REFERENCE_KIND", "0" * 64)


def test_retired_runtime_reference_is_retained_identity_not_execution_permission(tmp_path: Path) -> None:
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from tests.runtime_support.generation_support import only_ready_test_generation

    now = datetime(2026, 10, 8, tzinfo=UTC)
    runtime = OnlyRuntimeGenerationRegistry(tmp_path / "runtime")
    generation = only_ready_test_generation(runtime, "a", now)
    other = only_ready_test_generation(runtime, "b", now)
    runtime.activate_for_new_work(expected_current=None, target=generation, actor="human", occurred_at=now)
    runtime.bind_new_work_exact("chart", generation, owner="CHART_CALCULATION_INPUT", actor="chart", occurred_at=now)
    catalogs = SimpleNamespace(load_verified_catalog_descriptor=lambda identity: {"generation_fingerprint": identity})
    owners = OnlyExperimentMemoryReferenceReadersV1(None, catalogs, None, None, None, runtime, None, None, None)
    reader = owners.for_observations(())
    original = reader("RUNTIME_WORK_BINDING", "chart")
    runtime.release_work("chart", actor="human", occurred_at=now)
    runtime.activate_for_new_work(expected_current=generation, target=other, actor="human", occurred_at=now)
    runtime.retire(generation, actor="human", occurred_at=now)
    assert reader("RUNTIME_WORK_BINDING", "chart") == original
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_UNAVAILABLE"):
        runtime.require_runtime_generation(generation)
