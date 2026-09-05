"""Provider-neutral executable L3/L4 public-contract conformance.

The same test module is selected with environment variables when certifying private
providers against an exact OnlyAlpha checkout.  Provider IDs and asset content are
subjects, never assertions about public versus private semantics.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

from onlyalpha.application import OnlyCalculationEquivalenceCertificationApplicationService
from onlyalpha.application.product_command_receipt import OnlyProductCommandReceipt
from onlyalpha.calculation import OnlyCalculationBackendKind, OnlyCalculationKind
from onlyalpha.calculation.equivalence import OnlyCalculationEquivalenceEvidenceV2Store
from onlyalpha.canonical import only_canonical_json
from onlyalpha.domain.enums import (
    OnlySessionType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.quant_assets import (
    OnlyQuantAssetCatalogGeneration,
    OnlyQuantAssetLayer,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
    only_discover_quant_asset_providers,
    only_quant_asset_distribution_artifact_manifest,
)
from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendResolver
from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
from onlyalpha.research.calculation.execution_evidence import OnlyResearchCalculationExecutionEvidenceStore
from onlyalpha.research.calculation.result_store import OnlyParquetResearchCalculationResultStore
from onlyalpha.research.command import (
    OnlyResearchCommandService,
    OnlyResearchSubmissionKey,
)
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.dataset.definition import OnlyResearchDatasetDefinition
from onlyalpha.research.dataset.identity import only_content_fingerprint, only_snapshot_fingerprint
from onlyalpha.research.dataset.manifest import OnlyResearchDatasetSnapshot
from onlyalpha.research.dataset.schema import RESEARCH_BAR_DATASET_SCHEMA_V1
from onlyalpha.research.definition import OnlyResearchDefinition
from onlyalpha.research.definition.resolver import OnlyResearchDefinitionResolver
from onlyalpha.research.evaluation.execution import OnlyResearchStatisticsExecutor
from onlyalpha.research.evaluation.result_store import OnlyParquetResearchStatisticsResultStore
from onlyalpha.research.job.executor import OnlyResearchJobExecutor
from onlyalpha.research.provenance import (
    OnlyResearchAuthoringProvenance,
    only_research_execution_generation_fingerprint,
)
from onlyalpha.research.result.assembler import OnlyResearchResultAssembler
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore
from onlyalpha.research.run import OnlyResearchRun, OnlyResearchRunId, OnlyResearchRunState
from onlyalpha.research.run.evidence import only_research_admission_resolution_fingerprint
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from onlyalpha.research.sweep.executor import OnlyResearchSweepExecutor
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.generation import (
    OnlyCoreExecutionIdentity,
    OnlyRuntimeGenerationManifest,
    OnlyRuntimeProviderBinding,
)
from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives
from onlyalpha.strategy.admission import OnlyStrategyTradingAdmissionService
from onlyalpha.strategy.freeze import OnlyInMemoryStrategyCatalog, OnlyStrategyFreezeRequest, OnlyStrategyFreezeService
from onlyalpha.strategy.store import _only_compose_frozen_strategy_authority

pytestmark = pytest.mark.contract

NOW = datetime(2026, 9, 5, tzinfo=UTC)
L3_PROVIDER_ID = os.environ.get("ONLYALPHA_CONFORMANCE_L3_PROVIDER_ID", "example.alpha.library")
L4_PROVIDER_ID = os.environ.get("ONLYALPHA_CONFORMANCE_L4_PROVIDER_ID", "example.strategy.library")
L4_ASSET_ID = os.environ.get("ONLYALPHA_CONFORMANCE_L4_ASSET_ID", "example.strategy.simple_momentum")
SOURCE_REPOSITORY = os.environ.get("ONLYALPHA_CONFORMANCE_SOURCE_REPOSITORY", "OnlyAlpha-example-alpha")


@dataclass(slots=True)
class _Runs:
    run: OnlyResearchRun

    def load(self, run_id: OnlyResearchRunId) -> OnlyResearchRun:
        if run_id != self.run.run_id:
            raise KeyError(run_id)
        return self.run


@dataclass(frozen=True, slots=True)
class _Datasets:
    store: OnlyParquetResearchDatasetSnapshotStore
    fingerprint: str

    def resolve_verified(self, expected: OnlyResearchDatasetDefinition):  # type: ignore[no-untyped-def]
        verified = self.store.load_verified_table(self.fingerprint)
        if verified.snapshot.definition != expected:
            raise ValueError("Dataset Definition is unavailable")
        return verified


def _providers() -> dict[str, OnlyQuantAssetProvider]:
    return {item.manifest.provider_id: item for item in only_discover_quant_asset_providers().providers}


def _selected_provider(providers: dict[str, OnlyQuantAssetProvider], provider_id: str) -> OnlyQuantAssetProvider:
    try:
        return providers[provider_id]
    except KeyError as exc:
        raise AssertionError(f"installed provider is unavailable: {provider_id}") from exc


def _strategy_definition(provider: OnlyQuantAssetProvider) -> OnlyResearchDefinition:
    matches = [item for item in provider.strategy_assets if item.asset_id == L4_ASSET_ID]
    assert len(matches) == 1
    payload = json.loads(matches[0].resource_bytes("research-definition.json"))
    assert isinstance(payload, dict)
    return OnlyResearchDefinition.from_dict(payload)


def test_l3_and_l4_subjects_satisfy_the_same_public_provider_contract() -> None:
    providers = _providers()
    factor = _selected_provider(providers, L3_PROVIDER_ID)
    strategy = _selected_provider(providers, L4_PROVIDER_ID)

    assert factor.manifest.layer is OnlyQuantAssetLayer.FACTOR
    assert not factor.strategy_assets
    grouped: dict[tuple[str, str], set[OnlyCalculationBackendKind]] = {}
    for registration in factor.calculation_registrations:
        assert registration.type_definition.kind is OnlyCalculationKind.FACTOR
        assert registration.implementation_manifest is not None
        key = (registration.type_definition.type_id, registration.type_definition.semantic_version)
        grouped.setdefault(key, set()).add(registration.backend)
    assert grouped
    assert all(
        backends == {OnlyCalculationBackendKind.RESEARCH, OnlyCalculationBackendKind.TRADING}
        for backends in grouped.values()
    )

    assert strategy.manifest.layer is OnlyQuantAssetLayer.STRATEGY
    assert not strategy.calculation_registrations
    definition = _strategy_definition(strategy)
    registry = only_default_engine_services(fail_fast=True).assembler.components.calculations
    for calculation in definition.calculations:
        reference = calculation.type_reference
        assert reference.semantic_version
        registry.resolve(
            reference.kind,
            reference.type_id,
            reference.semantic_version,
            OnlyCalculationBackendKind.RESEARCH,
        )


def test_l3_and_l4_subjects_bind_one_public_artifact_and_runtime_generation_contract() -> None:
    providers = _providers()
    selected = (
        _selected_provider(providers, L3_PROVIDER_ID),
        _selected_provider(providers, L4_PROVIDER_ID),
    )
    catalog = OnlyQuantAssetCatalogGeneration(selected)
    core = OnlyCoreExecutionIdentity("onlyalpha", "0.9.9", "a" * 64)
    artifacts = tuple(
        only_quant_asset_distribution_artifact_manifest(
            source_repository=SOURCE_REPOSITORY,
            source_revision=("b" if provider.manifest.layer is OnlyQuantAssetLayer.FACTOR else "c") * 40,
            artifact_logical_name=(
                provider.manifest.distribution_name.replace("-", "_")
                + f"-{provider.manifest.distribution_version}-py3-none-any.whl"
            ),
            artifact_bytes=(provider.manifest.provider_id + provider.content_fingerprint).encode(),
            tested_core_execution_fingerprint=core.fingerprint,
            provider=provider,
        )
        for provider in selected
    )
    generation = OnlyRuntimeGenerationManifest(
        core_execution=core,
        artifact_manifest_fingerprints=("d" * 64, *(item.manifest_fingerprint for item in artifacts)),
        artifact_sha256s=(core.artifact_sha256, *(item.artifact_sha256 for item in artifacts)),
        providers=tuple(
            OnlyRuntimeProviderBinding(
                provider.manifest.provider_id,
                provider.manifest.provider_version,
                provider.content_fingerprint,
                artifact.artifact_sha256,
            )
            for provider, artifact in zip(selected, artifacts, strict=True)
        ),
        catalog_generation_fingerprint=catalog.generation_fingerprint,
        implementations=tuple(item for artifact in artifacts for item in artifact.implementations),
    )
    assert generation.catalog_generation_fingerprint == catalog.generation_fingerprint
    assert {item.provider_id for item in generation.providers} == {L3_PROVIDER_ID, L4_PROVIDER_ID}


def test_l3_subject_binds_an_exact_authoring_execution_generation(tmp_path: Path) -> None:
    from onlyalpha_authoring_execution_worker import (
        OnlyAuthoringExecutionGeneration,
        OnlyAuthoringExecutionGenerationRegistry,
        OnlyAuthoringExecutionGenerationStore,
    )

    generation = only_discover_quant_asset_providers()
    factor = _selected_provider({item.manifest.provider_id: item for item in generation.providers}, L3_PROVIDER_ID)
    candidate = OnlyQuantAssetProvider(
        OnlyQuantAssetProviderManifest(
            provider_id="candidate.contract.factor",
            provider_version="1",
            layer=OnlyQuantAssetLayer.FACTOR,
            distribution_name=factor.manifest.distribution_name,
            distribution_version=factor.manifest.distribution_version,
        ),
        calculation_registrations=factor.calculation_registrations,
    )
    catalog = OnlyQuantAssetCatalogGeneration(
        tuple(candidate if item.manifest.provider_id == L3_PROVIDER_ID else item for item in generation.providers)
    )
    identity = {
        "experiment_id": "exp-" + "a" * 32,
        "source_repository": SOURCE_REPOSITORY,
        "source_revision": "1" * 40,
        "source_tree": "2" * 40,
        "candidate_provider_id": candidate.manifest.provider_id,
        "candidate_provider_version": candidate.manifest.provider_version,
        "candidate_provider_content_fingerprint": candidate.content_fingerprint,
        "catalog_generation_fingerprint": catalog.generation_fingerprint,
    }
    provenance = OnlyResearchAuthoringProvenance(
        schema_version=1,
        **identity,
        execution_generation_fingerprint=only_research_execution_generation_fingerprint(**identity),
    )
    authoring = OnlyAuthoringExecutionGeneration(provenance, catalog)
    store = OnlyAuthoringExecutionGenerationStore(tmp_path / "generations")
    store.commit(authoring)
    store.verify(authoring)
    OnlyAuthoringExecutionGenerationRegistry((authoring,))
    definitions = authoring.engine_services().assembler.components.calculations.type_definitions()
    assert {item.type_id for item in definitions} >= {
        registration.type_definition.type_id for registration in candidate.calculation_registrations
    }


def test_installed_l3_l4_resolve_research_evidence_freeze_and_revision(tmp_path: Path) -> None:
    providers = _providers()
    strategy_provider = _selected_provider(providers, L4_PROVIDER_ID)
    services = only_default_engine_services(fail_fast=True)
    registry = services.assembler.components.calculations
    dataset_store = OnlyParquetResearchDatasetSnapshotStore(tmp_path / "datasets")
    definition = _strategy_definition(strategy_provider)
    snapshot, partitions = _snapshot(definition)
    committed = dataset_store.commit(snapshot, partitions)
    resolved = OnlyResearchDefinitionResolver(
        registry,
        _Datasets(dataset_store, committed.snapshot_fingerprint),
    ).resolve(definition)
    only_register_trading_predicate_primitives(registry)

    semantic_root = tmp_path / "semantic"
    equivalence = OnlyCalculationEquivalenceEvidenceV2Store(semantic_root)
    certification = OnlyCalculationEquivalenceCertificationApplicationService(registry, equivalence)
    decision_candidates = tuple(
        item
        for item in resolved.specification_resolution.candidates
        if item.calculation_id == "decision" and item.candidate_fingerprint is not None
    )
    assert decision_candidates
    for node in {
        node.fingerprint: node for candidate in decision_candidates for node in candidate.graph.nodes
    }.values():
        certification.certify(node)

    calculation_store = OnlyParquetResearchCalculationResultStore(
        tmp_path / "calculation-results", dataset_store, audit_time=lambda: NOW
    )
    evidence_store = OnlyResearchCalculationExecutionEvidenceStore(semantic_root)
    executor = OnlyResearchCalculationExecutor(dataset_store, OnlyResearchCalculationBackendResolver(registry))
    job = OnlyResearchJobExecutor(executor, calculation_store, evidence_store)
    sweep = OnlyResearchSweepExecutor(job)
    evidence: set[str] = set()
    for plan in resolved.workload.direct_jobs:
        evidence.add(job.execute(plan).calculation_execution_evidence_fingerprint)
    for plan in resolved.workload.sweeps:
        evidence.update(item.calculation_execution_evidence_fingerprint for item in sweep.execute(plan).cells)
    assert evidence

    statistics_store = OnlyParquetResearchStatisticsResultStore(
        tmp_path / "statistics-results", calculation_store, audit_time=lambda: NOW
    )
    statistics = OnlyResearchStatisticsExecutor(calculation_store, statistics_store)
    for plan in resolved.workload.statistics_plans:
        statistics.execute(plan)
    research_store = OnlyJsonResearchResultStore(tmp_path / "research-results", statistics_store, calculation_store)
    assembled = OnlyResearchResultAssembler(
        statistics_store,
        audit_time=lambda: NOW,
        calculation_result_store=calculation_store,
    ).assemble(resolved.workload.result_plan)
    result = research_store.commit(assembled)

    run_id = OnlyResearchRunId("00000000-0000-4000-8000-000000003000")
    queued = OnlyResearchRun.queued(
        run_id=run_id,
        specification=resolved.specification,
        canonical_specification_payload=only_canonical_json(resolved.specification.to_dict()),
        admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(
            resolved.specification_resolution
        ),
        queued_at=NOW,
    )
    generation_fingerprint = os.environ.get("ONLYALPHA_EXACT_RUNTIME_GENERATION_FINGERPRINT")
    generation_authority_root = os.environ.get("ONLYALPHA_EXACT_RUNTIME_GENERATION_AUTHORITY_ROOT")
    generation_manifest = None
    if generation_fingerprint is not None or generation_authority_root is not None:
        assert generation_fingerprint is not None and generation_authority_root is not None
        runtime_generations = OnlyRuntimeGenerationRegistry(Path(generation_authority_root))

        class _Admission:
            def prepare(self, specification, *, provenance=None):  # type: ignore[no-untyped-def]
                assert specification == queued.specification
                assert provenance is None
                return queued

        class _Commands:
            receipt: OnlyProductCommandReceipt | None = None
            persisted: OnlyResearchRun | None = None

            def find_product_command_receipt(self, key):  # type: ignore[no-untyped-def]
                del key
                return self.receipt

            def create_queued_with_receipt(self, candidate, receipt):  # type: ignore[no-untyped-def]
                self.persisted = candidate
                self.receipt = receipt
                return receipt

            def load(self, candidate_run_id):  # type: ignore[no-untyped-def]
                assert candidate_run_id == run_id and self.persisted is not None
                return self.persisted

        commands = _Commands()
        admitted = OnlyResearchCommandService(
            admission=_Admission(),  # type: ignore[arg-type]
            store=commands,  # type: ignore[arg-type]
            now_utc=lambda: NOW,
            runtime_generations=runtime_generations,
        ).submit_research_run(
            OnlyResearchSubmissionKey("00000000-0000-4000-8000-000000003001"),
            queued.specification,
        )
        assert admitted.run == queued
        binding = runtime_generations.require_work_binding(run_id.value)
        assert binding.runtime_generation_fingerprint == generation_fingerprint
        generation_manifest = runtime_generations.require_work_generation(run_id.value, generation_fingerprint)

    run = queued.transition(OnlyResearchRunState.RUNNING, at=NOW + timedelta(seconds=1)).transition(
        OnlyResearchRunState.COMPLETED,
        at=NOW + timedelta(seconds=2),
        research_result_fingerprint=result.research_result_fingerprint,
        artifact_content_fingerprint="f" * 64,
        calculation_execution_evidence_fingerprints=tuple(sorted(evidence)),
    )
    strategies, publisher = _only_compose_frozen_strategy_authority(semantic_root)
    freeze = OnlyStrategyFreezeService(
        runs=_Runs(run),
        research_results=research_store,
        calculation_results=calculation_store,
        calculation_execution_evidence=evidence_store,
        datasets=dataset_store,
        specification_resolver=OnlyResearchSpecificationResolver(registry),
        admission=OnlyStrategyTradingAdmissionService(registry, equivalence),
        strategies=strategies,
        strategy_publisher=publisher,
        catalog=OnlyInMemoryStrategyCatalog(),
        audit_time=lambda: NOW,
    )
    selected = decision_candidates[0]
    assert selected.candidate_fingerprint is not None
    request = OnlyStrategyFreezeRequest(run_id, selected.candidate_fingerprint, "contract-conformance")
    first = freeze.freeze(request)
    second = freeze.freeze(request)
    assert first.strategy_fingerprint == second.strategy_fingerprint
    revision = strategies.load_verified(first.strategy_fingerprint)
    assert revision.strategy_fingerprint.value == first.strategy_fingerprint
    if generation_manifest is not None:
        generation_implementations = {
            (item.backend, item.implementation_fingerprint) for item in generation_manifest.implementations
        }
        research_implementations = {
            ("RESEARCH", binding.research_implementation_fingerprint)
            for fingerprint in evidence
            for binding in evidence_store.load_verified(fingerprint).research_implementation_bindings
        }
        revision_implementations = {
            (backend, fingerprint)
            for binding in revision.implementation_bindings
            for backend, fingerprint in (
                ("RESEARCH", binding.research_implementation_fingerprint),
                ("TRADING", binding.trading_implementation_fingerprint),
            )
        }
        assert research_implementations <= generation_implementations
        assert revision_implementations <= generation_implementations


def _snapshot(
    research_definition: OnlyResearchDefinition,
) -> tuple[OnlyResearchDatasetSnapshot, tuple[tuple[OnlyBar, ...], ...]]:
    dataset = research_definition.dataset
    instrument = OnlyInstrumentId.parse(dataset.universe.instrument_ids[0])
    specification = dataset.bar_specification
    bar_type = OnlyBarType(instrument, specification, dataset.aggregation_source)
    bars: list[OnlyBar] = []
    start_bound = datetime.fromisoformat(dataset.start)
    end_bound = datetime.fromisoformat(dataset.end)
    closes = ("10", "11", "13", "12", "15", "14", "16", "13")
    for index, close in enumerate(closes):
        start = start_bound + timedelta(minutes=index)
        if start + timedelta(minutes=1) >= end_bound:
            break
        value = Decimal(close)
        bars.append(
            OnlyBar(
                bar_type=bar_type,
                open=OnlyPrice(value, 2),
                high=OnlyPrice(value + 1, 2),
                low=OnlyPrice(value - 1, 2),
                close=OnlyPrice(value, 2),
                volume=OnlyQuantity(Decimal(100 + index), 0),
                quote_volume=None,
                turnover=None,
                trade_count=index,
                open_interest=None,
                bar_start=start,
                bar_end=start + timedelta(minutes=1),
                ts_event=start + timedelta(minutes=1),
                ts_init=start + timedelta(minutes=1),
                is_closed=True,
                revision=0,
                adjustment_type=dataset.adjustment_type,
                trading_day=date(start.year, start.month, start.day),
                session_type=OnlySessionType.CONTINUOUS,
            )
        )
    definition = dataset.to_dataset_definition(dataset.universe.instrument_ids)
    canonical = tuple(bars)
    content = only_content_fingerprint(canonical)
    fingerprint = only_snapshot_fingerprint(definition, RESEARCH_BAR_DATASET_SCHEMA_V1, content, len(canonical))
    return (
        OnlyResearchDatasetSnapshot(
            definition,
            RESEARCH_BAR_DATASET_SCHEMA_V1,
            content,
            len(canonical),
            fingerprint,
            (),
            (),
            NOW,
        ),
        (canonical,),
    )
