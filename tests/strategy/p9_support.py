from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from onlyalpha.calculation import OnlyCalculationBackendKind, OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.market import OnlyBar
from onlyalpha.research import (
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyResearchDefinitionResolver,
)
from onlyalpha.strategy import (
    OnlyCalculationEquivalenceAdmission,
    OnlyCalculationEquivalenceAdmissionRegistry,
    OnlyStrategyMarketInputContract,
    OnlyStrategyRevision,
    OnlyStrategySignalBinding,
    OnlyStrategySignalSemantics,
    OnlyStrategyTradingAdmissionService,
    OnlyStrategyUniverse,
)
from tests.research.calculation.support import bars, snapshot
from tests.research.definition.support import definition
from tests.research.evaluation.support import evaluation_registry


@dataclass(frozen=True, slots=True)
class P9StrategyCase:
    revision: OnlyStrategyRevision
    registry: OnlyCalculationRegistry
    dataset_store: OnlyParquetResearchDatasetSnapshotStore
    dataset_fingerprint: str
    bars: tuple[OnlyBar, ...]
    revision_variants: tuple[OnlyStrategyRevision, ...]
    equivalence: OnlyCalculationEquivalenceAdmissionRegistry


class _Datasets:
    def __init__(self, store: OnlyParquetResearchDatasetSnapshotStore, fingerprint: str) -> None:
        self._store = store
        self._fingerprint = fingerprint

    def resolve_verified(self, expected):
        verified = self._store.load_verified_table(self._fingerprint)
        if verified.snapshot.definition != expected:
            raise ValueError("Dataset Definition is unavailable")
        return verified


def p9_strategy_case(root: Path) -> P9StrategyCase:
    dataset_store = OnlyParquetResearchDatasetSnapshotStore(root / "datasets")
    candidate, partitions = snapshot()
    committed = dataset_store.commit(candidate, partitions)
    registry = evaluation_registry()
    resolved = OnlyResearchDefinitionResolver(
        registry,
        _Datasets(dataset_store, committed.snapshot_fingerprint),
    ).resolve(definition(committed.definition))
    candidates = tuple(
        item
        for item in resolved.specification_resolution.candidates
        if item.calculation_id == "decision" and item.candidate_fingerprint is not None
    )
    equivalence = OnlyCalculationEquivalenceAdmissionRegistry()
    registered: set[tuple[str, str, str]] = set()
    for node in (node for candidate_value in candidates for node in candidate_value.graph.nodes):
        definition_value = node.definition
        research = registry.resolve(
            definition_value.kind,
            definition_value.type_id,
            definition_value.semantic_version,
            OnlyCalculationBackendKind.RESEARCH,
        )
        trading = registry.resolve(
            definition_value.kind,
            definition_value.type_id,
            definition_value.semantic_version,
            OnlyCalculationBackendKind.TRADING,
        )
        assert research.implementation_manifest is not None
        assert trading.implementation_manifest is not None
        key = (
            definition_value.type_id,
            research.implementation_manifest.implementation_fingerprint,
            trading.implementation_manifest.implementation_fingerprint,
        )
        if key in registered:
            continue
        registered.add(key)
        equivalence.register(
            OnlyCalculationEquivalenceAdmission(
                research.implementation_manifest.calculation_type_reference,
                research.implementation_manifest.implementation_fingerprint,
                trading.implementation_manifest.implementation_fingerprint,
                only_canonical_fingerprint(
                    {
                        "contract": "P9_CROSS_BACKEND_EQUIVALENCE_V1",
                        "type_id": definition_value.type_id,
                        "semantic_version": definition_value.semantic_version,
                    }
                ),
            )
        )
    dataset_definition = committed.definition
    revisions = []
    for selected in candidates:
        signals = tuple(
            item
            for item in resolved.specification_resolution.signals
            if item.candidate_fingerprint == selected.candidate_fingerprint
        )
        by_role = {item.role: item for item in signals}
        signal_semantics = OnlyStrategySignalSemantics(
            OnlyStrategySignalBinding(by_role["ELIGIBILITY"].node_fingerprint, by_role["ELIGIBILITY"].output_name),
            OnlyStrategySignalBinding(by_role["ENTRY_SIGNAL"].node_fingerprint, by_role["ENTRY_SIGNAL"].output_name),
            OnlyStrategySignalBinding(by_role["EXIT_SIGNAL"].node_fingerprint, by_role["EXIT_SIGNAL"].output_name),
        )
        admitted = OnlyStrategyTradingAdmissionService(registry, equivalence).admit(selected.graph, signal_semantics)
        revisions.append(
            OnlyStrategyRevision(
                OnlyStrategyUniverse(dataset_definition.instruments),
                OnlyStrategyMarketInputContract(
                    dataset_definition.bar_specification,
                    dataset_definition.aggregation_source,
                    dataset_definition.adjustment_type,
                    dataset_definition.adjustment_reference,
                ),
                selected.graph,
                admitted.implementation_bindings,
                signal_semantics,
            )
        )
    return P9StrategyCase(
        revisions[0],
        registry,
        dataset_store,
        committed.snapshot_fingerprint,
        bars(),
        tuple(revisions),
        equivalence,
    )
