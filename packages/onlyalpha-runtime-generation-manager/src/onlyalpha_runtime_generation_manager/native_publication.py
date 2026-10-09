"""Native installed-generation publication foundation; never Chart Run or Search-worker dispatch."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from onlyalpha.canonical import only_canonical_json
from onlyalpha.quant_assets.retained_generation import OnlyRetainedRuntimeGenerationProofV1
from onlyalpha.research.artifact.calculation_v2_materializer import OnlyResearchCalculationArtifactMaterializerV2
from onlyalpha.research.artifact.calculation_v2_store import OnlyParquetResearchCalculationArtifactStoreV2
from onlyalpha.research.artifact.calculation_v2_verification import OnlyResearchCalculationArtifactV2
from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendResolver
from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
from onlyalpha.research.calculation.execution_evidence import OnlyResearchCalculationExecutionEvidenceStore
from onlyalpha.research.calculation.execution_evidence_v2 import (
    OnlyResearchCalculationExecutionEvidenceStoreV2,
    OnlyResearchCalculationExecutionEvidenceV2,
)
from onlyalpha.research.calculation.execution_provenance import (
    OnlyResearchRuntimeExecutionProvenanceV1,
    _only_issue_research_runtime_execution_context,
    _OnlyResearchRuntimeExecutionContext,
)
from onlyalpha.research.calculation.result_store import OnlyParquetResearchCalculationResultStore
from onlyalpha.research.calculation.result_v2_store import OnlyParquetResearchCalculationResultStoreV2
from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.dataset.publication_input import (
    _only_require_verified_sealed_chart_publication_input,
    _OnlyVerifiedSealedChartPublicationInput,
)
from onlyalpha.research.job.executor import _only_execute_generation_bound_calculation_job
from onlyalpha.research.result.assembler import OnlyResearchResultAssembler
from onlyalpha.research.result.errors import OnlyResearchResultStoreError
from onlyalpha.research.result.result import OnlyResearchResult
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore
from onlyalpha.research.run.calculation_resolution import OnlyResearchCalculationRuntimeResolutionV1

from .artifact_store import OnlyLocalImmutableArtifactStore
from .hosted import only_load_hosted_quant_asset_catalog, only_verify_hosted_runtime_generation
from .registry import OnlyRuntimeGenerationRegistry
from .search_worker import _calculation_registry, _resolve_calculation_publication


@dataclass(frozen=True, slots=True)
class _OnlyNativeCalculationContext:
    context: _OnlyResearchRuntimeExecutionContext
    retained: OnlyRetainedRuntimeGenerationProofV1
    datasets: OnlyParquetResearchDatasetSnapshotStore
    calculations: OnlyParquetResearchCalculationResultStoreV2
    evidence: OnlyResearchCalculationExecutionEvidenceStoreV2
    results: OnlyJsonResearchResultStore
    executor: OnlyResearchCalculationExecutor


def only_publish_native_calculation_result(
    *,
    generations: OnlyRuntimeGenerationRegistry,
    distribution_artifact_store: OnlyLocalImmutableArtifactStore,
    frozen: OnlyResearchCalculationRuntimeResolutionV1,
    dataset_store_root: Path,
    calculation_result_root: Path,
    execution_evidence_root: Path,
    research_result_root: Path,
    audit_time: Callable[[], datetime],
    authoring_generation_fingerprint: str | None = None,
) -> tuple[OnlyResearchResult, OnlyResearchCalculationExecutionEvidenceV2]:
    publication = _prepare_native_calculation(
        generations=generations,
        distribution_artifact_store=distribution_artifact_store,
        frozen=frozen,
        dataset_store_root=dataset_store_root,
        calculation_result_root=calculation_result_root,
        execution_evidence_root=execution_evidence_root,
        research_result_root=research_result_root,
        audit_time=audit_time,
        authoring_generation_fingerprint=authoring_generation_fingerprint,
    )
    legacy = OnlyParquetResearchCalculationResultStore(
        calculation_result_root, publication.datasets, audit_time=audit_time
    )
    outcome = _only_execute_generation_bound_calculation_job(
        frozen.job_plan,
        publication.executor,
        legacy,
        OnlyResearchCalculationExecutionEvidenceStore(execution_evidence_root),
        publication.calculations,
        publication.evidence,
        publication.context,
    )
    result = OnlyResearchResultAssembler(
        None,
        audit_time=audit_time,
        readiness_result_store=publication.calculations,
        readiness_evidence_store=publication.evidence,
    ).assemble(frozen.result_plan)
    publication.results.commit(result)
    producer = publication.evidence.acknowledge_exact(outcome.calculation_execution_evidence_fingerprint)
    return publication.results.load_verified(frozen.result_plan.fingerprint), producer


def only_publish_native_calculation_artifact(
    *,
    generations: OnlyRuntimeGenerationRegistry,
    distribution_artifact_store: OnlyLocalImmutableArtifactStore,
    frozen: OnlyResearchCalculationRuntimeResolutionV1,
    dataset_store_root: Path,
    calculation_result_root: Path,
    execution_evidence_root: Path,
    research_result_root: Path,
    research_artifact_root: Path,
    verified_input: _OnlyVerifiedSealedChartPublicationInput,
    audit_time: Callable[[], datetime],
) -> OnlyResearchCalculationArtifactV2:
    """Installed-generation foundation, not Work permission, Chart dispatch or Run success."""
    if research_artifact_root.is_symlink() or not research_artifact_root.is_dir():
        raise ValueError("Artifact durability anchor must be preprovisioned")
    snapshot_fingerprint = frozen.result_plan.dataset_snapshot_fingerprint
    if snapshot_fingerprint is None:
        raise ValueError("native Artifact requires an exact Dataset Snapshot")
    _only_require_verified_sealed_chart_publication_input(
        verified_input,
        frozen.result_plan.fingerprint,
        frozen.graph_fingerprint,
        frozen.runtime_generation_fingerprint,
    ).verify_snapshot(
        OnlyParquetResearchDatasetSnapshotStore(dataset_store_root).load_verified_table(snapshot_fingerprint).snapshot
    )
    publication = _prepare_native_calculation(
        generations=generations,
        distribution_artifact_store=distribution_artifact_store,
        frozen=frozen,
        dataset_store_root=dataset_store_root,
        calculation_result_root=calculation_result_root,
        execution_evidence_root=execution_evidence_root,
        research_result_root=research_result_root,
        audit_time=audit_time,
    )
    # Artifact projection never reconstructs a missing live predecessor, including
    # when an independently readable portable publication survives upstream loss.
    publication.results.load_verified(frozen.result_plan.fingerprint)
    calculation = publication.calculations.load_verified(frozen.job_plan.calculation_fingerprint)
    producer = publication.evidence.require_exact_for_result(
        calculation, frozen.research_implementation_bindings, publication.context.provenance
    )
    return OnlyResearchCalculationArtifactMaterializerV2(
        publication.results, publication.datasets, publication.calculations, publication.evidence
    ).publish(
        frozen.result_plan.fingerprint,
        ((producer.calculation_fingerprint, producer.evidence_fingerprint),),
        runtime_context=publication.context,
        retained_generation=publication.retained,
        verified_input=verified_input,
        artifact_store=OnlyParquetResearchCalculationArtifactStoreV2(research_artifact_root, audit_time=audit_time),
    )


def _prepare_native_calculation(
    *,
    generations: OnlyRuntimeGenerationRegistry,
    distribution_artifact_store: OnlyLocalImmutableArtifactStore,
    frozen: OnlyResearchCalculationRuntimeResolutionV1,
    dataset_store_root: Path,
    calculation_result_root: Path,
    execution_evidence_root: Path,
    research_result_root: Path,
    audit_time: Callable[[], datetime],
    authoring_generation_fingerprint: str | None = None,
) -> _OnlyNativeCalculationContext:
    """Verify this exact installed process before issuing any native execution context.

    This is trusted in-process composition for publication tests/foundations, not a
    product command or Chart Work permission. No Host IPC capability calls it.
    """
    if authoring_generation_fingerprint is not None:
        raise ValueError("native publication has no verified Authoring Generation relation")
    if (
        type(generations) is not OnlyRuntimeGenerationRegistry
        or type(distribution_artifact_store) is not OnlyLocalImmutableArtifactStore
        or type(frozen) is not OnlyResearchCalculationRuntimeResolutionV1
    ):
        raise ValueError("exact owning Registry and frozen compilation contracts required")
    canonical = OnlyResearchCalculationRuntimeResolutionV1.from_dict(frozen.to_dict())
    if canonical != frozen:
        raise ValueError("native publication frozen compilation is not canonical")
    manifest = generations.load_manifest(frozen.runtime_generation_fingerprint)
    validation = generations.load_validation_evidence(frozen.runtime_generation_fingerprint)
    if manifest.runtime_generation_fingerprint != frozen.runtime_generation_fingerprint or not validation.verifies(
        manifest
    ):
        raise ValueError("RUNTIME_GENERATION_VALIDATION_EVIDENCE_MISMATCH")
    # No ambient compiler/Registry or raw-hash provenance until exact installed-byte verification.
    only_verify_hosted_runtime_generation(validation)
    catalog = only_load_hosted_quant_asset_catalog(validation)
    compiled = _resolve_calculation_publication(frozen.specification, catalog, validation)
    if compiled != frozen.to_dict():
        raise ValueError("native publication differs from exact installed compilation")
    distributions = tuple(
        sorted(
            (distribution_artifact_store.fetch_exact(identity)[0] for identity in manifest.artifact_sha256s),
            key=lambda item: item.manifest_fingerprint,
        )
    )
    retained = OnlyRetainedRuntimeGenerationProofV1(
        manifest,
        validation,
        distributions,
        (frozen.implementation_manifest,),
        only_canonical_json(catalog.descriptor()),
    )
    retained.require_graph_implementations(
        frozen.calculation_graph,
        tuple(
            (item.node_fingerprint, item.research_implementation_fingerprint)
            for item in frozen.research_implementation_bindings
        ),
    )
    registry = _calculation_registry(catalog.calculation_registry())
    datasets = OnlyParquetResearchDatasetSnapshotStore(dataset_store_root)
    executor = OnlyResearchCalculationExecutor(datasets, OnlyResearchCalculationBackendResolver(registry))
    if executor.plan(frozen.calculation_graph).implementation_bindings != frozen.research_implementation_bindings:
        raise ValueError("native publication implementation binding differs")
    context = _only_issue_research_runtime_execution_context(
        OnlyResearchRuntimeExecutionProvenanceV1(
            manifest.runtime_generation_fingerprint,
            validation.validation_evidence_fingerprint,
            manifest.core_execution.fingerprint,
            manifest.catalog_generation_fingerprint,
        ),
        frozen.graph_fingerprint,
        tuple(
            (item.node_fingerprint, item.research_implementation_fingerprint)
            for item in frozen.research_implementation_bindings
        ),
    )
    calculations = OnlyParquetResearchCalculationResultStoreV2(calculation_result_root, datasets, audit_time=audit_time)
    evidence = OnlyResearchCalculationExecutionEvidenceStoreV2(execution_evidence_root, calculations)
    results = OnlyJsonResearchResultStore(
        research_result_root, None, readiness_result_store=calculations, readiness_evidence_store=evidence
    )
    # Retained downstream Authority forbids reconstruction of missing predecessors.
    # Check the exact Plan leaf and full upstream closure before any Job/backend call.
    try:
        results.load_verified(frozen.result_plan.fingerprint)
    except OnlyResearchResultStoreError as exc:
        if exc.code != "RESEARCH_RESULT_NOT_FOUND":
            raise
    return _OnlyNativeCalculationContext(context, retained, datasets, calculations, evidence, results, executor)
