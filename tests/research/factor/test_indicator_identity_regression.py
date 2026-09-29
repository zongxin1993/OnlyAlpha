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


def test_indicator_graph_calculation_and_result_identities_remain_exact(tmp_path) -> None:
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
    assert execution.calculation_fingerprint == "446a9b5c8b664da3e175f31f28e9514094a52055d47fd2ec40edc1ead10bb54d"
    assert (
        result.manifest.result_content_fingerprint == "6caf8ea98bfa08bd68a4047eab165dfac11e3b63b2dccbcfe43add850afd8ba0"
    )
    assert result.manifest.calculation_result_fingerprint == (
        "c69bd8a2e7439eb0aa7c86140b914433d0ca7f49a3bf44924d8891ec4460d381"
    )
