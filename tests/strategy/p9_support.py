from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from onlyalpha.application import OnlyCalculationEquivalenceCertificationApplicationService
from onlyalpha.calculation import OnlyCalculationEquivalenceEvidenceV2Store, OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_json
from onlyalpha.domain.market import OnlyBar
from onlyalpha.research import (
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyResearchCalculationBackendResolver,
    OnlyResearchCalculationExecutionEvidence,
    OnlyResearchCalculationExecutionEvidenceStore,
    OnlyResearchCalculationExecutor,
    OnlyResearchDefinitionResolver,
)
from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives
from onlyalpha.strategy import (
    OnlyFrozenStrategyRevisionStore,
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
    equivalence: OnlyCalculationEquivalenceEvidenceV2Store
    execution_evidence: tuple[OnlyResearchCalculationExecutionEvidence, ...]


class _Datasets:
    def __init__(self, store: OnlyParquetResearchDatasetSnapshotStore, fingerprint: str) -> None:
        self._store = store
        self._fingerprint = fingerprint

    def resolve_verified(self, expected):
        verified = self._store.load_verified_table(self._fingerprint)
        if verified.snapshot.definition != expected:
            raise ValueError("Dataset Definition is unavailable")
        return verified


def publish_frozen_strategy_for_execution_test(root: Path, revision: OnlyStrategyRevision) -> None:
    """Pure execution fixture support; no equivalent publisher exists under src/onlyalpha."""

    fingerprint = str(revision.strategy_fingerprint)
    target = root / "strategy" / "frozen-revisions" / "sha256" / fingerprint[:2] / fingerprint
    if target.is_dir():
        if OnlyFrozenStrategyRevisionStore(root).load_verified(fingerprint) != revision:
            raise ValueError("test frozen Strategy publication conflict")
        return
    target.mkdir(parents=True, exist_ok=False)
    payload = {
        "schema_version": 1,
        "strategy_fingerprint": fingerprint,
        "revision": revision.to_dict(),
    }
    (target / "manifest.json").write_text(only_canonical_json(payload), encoding="utf-8")


def p9_strategy_case(root: Path, *, values: tuple[OnlyBar, ...] | None = None) -> P9StrategyCase:
    dataset_store = OnlyParquetResearchDatasetSnapshotStore(root / "datasets")
    candidate, partitions = snapshot(values)
    committed = dataset_store.commit(candidate, partitions)
    registry = evaluation_registry()
    resolved = OnlyResearchDefinitionResolver(
        registry,
        _Datasets(dataset_store, committed.snapshot_fingerprint),
    ).resolve(definition(committed.definition))
    only_register_trading_predicate_primitives(registry)
    candidates = tuple(
        item
        for item in resolved.specification_resolution.candidates
        if item.calculation_id == "decision" and item.candidate_fingerprint is not None
    )
    semantic_root = root / "semantic"
    equivalence = OnlyCalculationEquivalenceEvidenceV2Store(semantic_root)
    certification = OnlyCalculationEquivalenceCertificationApplicationService(registry, equivalence)
    for node in {node.fingerprint: node for value in candidates for node in value.graph.nodes}.values():
        certification.certify(node)
    calculation_results = OnlyParquetResearchCalculationResultStore(
        root / "calculation-results",
        dataset_store,
        audit_time=lambda: datetime(2026, 8, 24, tzinfo=UTC),
    )
    evidence_store = OnlyResearchCalculationExecutionEvidenceStore(semantic_root)
    calculation = OnlyResearchCalculationExecutor(
        dataset_store,
        OnlyResearchCalculationBackendResolver(registry),
    )
    dataset_definition = committed.definition
    revisions: list[OnlyStrategyRevision] = []
    execution_evidence: list[OnlyResearchCalculationExecutionEvidence] = []
    for selected in candidates:
        execution = calculation.execute(committed.snapshot_fingerprint, selected.graph)
        result = calculation_results.commit(execution, selected.graph)
        provenance = evidence_store.commit_execution(execution, result)
        execution_evidence.append(provenance)
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
        market_input = OnlyStrategyMarketInputContract(
            dataset_definition.bar_specification,
            dataset_definition.aggregation_source,
            dataset_definition.adjustment_type,
            dataset_definition.adjustment_reference,
        )
        admitted = OnlyStrategyTradingAdmissionService(registry, equivalence).admit(
            selected.graph,
            signal_semantics,
            market_input,
            provenance,
        )
        revisions.append(
            OnlyStrategyRevision(
                OnlyStrategyUniverse(dataset_definition.instruments),
                market_input,
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
        bars() if values is None else values,
        tuple(revisions),
        equivalence,
        tuple(execution_evidence),
    )
