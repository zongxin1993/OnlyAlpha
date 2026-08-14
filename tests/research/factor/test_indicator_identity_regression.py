from datetime import UTC, datetime

from onlyalpha_plugin_indicators.registration import TYPES, registrations, resolve_definition

from onlyalpha.calculation import OnlyCalculationGraphDefinition, OnlyCalculationNodeDefinition, OnlyCalculationRegistry
from onlyalpha.research import (
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyResearchCalculationBackendResolver,
    OnlyResearchCalculationExecutor,
)
from tests.research.calculation.support import snapshot


def test_p75_preserves_preexisting_indicator_graph_calculation_and_result_identities(tmp_path) -> None:
    registry = OnlyCalculationRegistry()
    for registration in registrations():
        registry.register(registration)
    graph = OnlyCalculationGraphDefinition(
        (OnlyCalculationNodeDefinition(resolve_definition(TYPES[0], {"period": 2})),)
    )
    dataset_store = OnlyParquetResearchDatasetSnapshotStore(tmp_path / "datasets")
    candidate, partitions = snapshot()
    dataset_store.commit(candidate, partitions)
    execution = OnlyResearchCalculationExecutor(
        dataset_store, OnlyResearchCalculationBackendResolver(registry)
    ).execute(candidate.snapshot_fingerprint, graph)
    result = OnlyParquetResearchCalculationResultStore(
        tmp_path / "results", dataset_store, audit_time=lambda: datetime(2026, 8, 14, tzinfo=UTC)
    ).commit(execution, graph)
    assert graph.fingerprint == "7f631b1ec661ccacd14774cbe5c7cfd59cbef848642c72b5e0581ac0c1b6626f"
    assert execution.calculation_fingerprint == "f337e136ee125a4080752407c39df42cd691bd70b0992ea99f79523e97e758a6"
    assert (
        result.manifest.result_content_fingerprint == "6caf8ea98bfa08bd68a4047eab165dfac11e3b63b2dccbcfe43add850afd8ba0"
    )
    assert result.manifest.calculation_result_fingerprint == (
        "7177fa2d1ba38f891a5a9884a264f06357c1e277ddeff9e23d4a3517bc81b8fb"
    )
