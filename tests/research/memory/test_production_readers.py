"""Exact reference verification uses retained owning facts, never copied facets."""

from __future__ import annotations

from pathlib import Path

import pytest
from onlyalpha_authoring_execution_worker import OnlyAuthoringExecutionGenerationStore
from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

from onlyalpha.backtest.evidence import OnlyBacktestEvidenceStore
from onlyalpha.research.memory.production import OnlyExperimentMemoryReferenceReadersV1
from onlyalpha.research.memory.source_manifest import OnlyMemoryProjectionError
from onlyalpha.research.search.parameter.store import OnlyJsonParameterSearchStore
from onlyalpha.research.search.symbolic.store import OnlyJsonSymbolicSearchStore
from onlyalpha.strategy.qualification_store import OnlyQualificationPolicyStore
from tests.strategy.test_strategy_freeze import _freeze_case


class _UnavailableCatalog:
    def load_verified_catalog_descriptor(self, fingerprint: str) -> dict[str, object]:
        raise RuntimeError(f"catalog unavailable: {fingerprint}")


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
        OnlyAuthoringExecutionGenerationStore(tmp_path / "authoring-generations"),
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
