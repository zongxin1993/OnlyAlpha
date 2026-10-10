"""Owning-store verification of a native receipt; never a native mint or PG write."""

from __future__ import annotations

from pathlib import Path

from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationCompilationV1
from onlyalpha.application.chart_calculation_input_export import OnlyChartCalculationInputExportService
from onlyalpha.application.chart_calculation_native_protocol import (
    OnlyChartCalculationNativeExecutionRequestV1,
    OnlyChartCalculationNativePublicationReceiptV1,
)
from onlyalpha.research.artifact.calculation_v2_store import OnlyParquetResearchCalculationArtifactStoreV2
from onlyalpha.research.artifact.calculation_v2_verification import OnlyResearchCalculationArtifactV2
from onlyalpha.research.calculation.execution_evidence_v2 import OnlyResearchCalculationExecutionEvidenceStoreV2
from onlyalpha.research.calculation.execution_provenance import OnlyResearchRuntimeExecutionProvenanceV1
from onlyalpha.research.calculation.result_v2_store import OnlyParquetResearchCalculationResultStoreV2
from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.dataset.publication_input import _only_require_verified_sealed_chart_publication_input
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore

from .registry import OnlyRuntimeGenerationRegistry


def only_verify_chart_native_publication(
    *,
    request: OnlyChartCalculationNativeExecutionRequestV1,
    frozen: OnlyChartCalculationCompilationV1,
    receipt: OnlyChartCalculationNativePublicationReceiptV1,
    inputs: OnlyChartCalculationInputExportService,
    generations: OnlyRuntimeGenerationRegistry,
    dataset_root: Path,
    calculation_result_root: Path,
    execution_evidence_root: Path,
    research_result_root: Path,
    artifact_root: Path,
) -> OnlyResearchCalculationArtifactV2:
    """Re-read all predecessors and the exact selected producer/Artifact pair.

    The Controller calls this outside its short terminal transaction. It still
    needs the owning Run/Attempt/lease/CAS and shared Work proof at actual COMMIT.
    A successful read is neither a persistent permission nor an issued native seal.
    This is deliberately not the Artifact-only historical reader: unavailable
    original Source or any live predecessor refuses current completion.
    """
    request.verify_compilation(frozen)
    receipt.verify_compilation(frozen)
    if receipt.request != request:
        raise ValueError("CHART_NATIVE_PUBLICATION_REQUEST_MISMATCH")
    manifest = generations.require_runtime_generation(frozen.runtime_generation_fingerprint)
    validation = generations.load_validation_evidence(frozen.runtime_generation_fingerprint)
    if not validation.verifies(manifest):
        raise ValueError("CHART_NATIVE_PUBLICATION_GENERATION_MISMATCH")
    expected_provenance = OnlyResearchRuntimeExecutionProvenanceV1(
        manifest.runtime_generation_fingerprint,
        validation.validation_evidence_fingerprint,
        manifest.core_execution.fingerprint,
        manifest.catalog_generation_fingerprint,
    )
    if receipt.runtime_provenance != expected_provenance:
        raise ValueError("CHART_NATIVE_PUBLICATION_GENERATION_MISMATCH")
    issued = inputs.export(request.operation_id)
    retained = _only_require_verified_sealed_chart_publication_input(
        issued, frozen.result_plan_fingerprint, frozen.graph_fingerprint, frozen.runtime_generation_fingerprint
    )
    datasets = OnlyParquetResearchDatasetSnapshotStore(dataset_root)
    dataset = datasets.load_verified_table(frozen.dataset_snapshot_fingerprint)
    retained.verify_snapshot(dataset.snapshot)
    calculations = OnlyParquetResearchCalculationResultStoreV2(calculation_result_root, datasets)
    calculation = calculations.load_verified(receipt.calculation_fingerprint)
    evidence_store = OnlyResearchCalculationExecutionEvidenceStoreV2(execution_evidence_root, calculations)
    evidence = evidence_store.load_verified(receipt.execution_evidence_fingerprint)
    if (
        calculation.manifest.calculation_result_fingerprint != receipt.calculation_result_fingerprint
        or calculation.manifest.calculation_graph != frozen.resolution.calculation_graph
        or evidence.research_implementation_bindings != frozen.resolution.research_implementation_bindings
        or evidence.runtime_execution_provenance != expected_provenance
        or evidence.authoring_generation_fingerprint is not None
        or evidence.calculation_fingerprint != receipt.calculation_fingerprint
        or evidence.calculation_result_fingerprint != receipt.calculation_result_fingerprint
    ):
        raise ValueError("CHART_NATIVE_PUBLICATION_PRODUCER_MISMATCH")
    results = OnlyJsonResearchResultStore(
        research_result_root, None, readiness_result_store=calculations, readiness_evidence_store=evidence_store
    )
    result = results.load_verified(frozen.result_plan_fingerprint)
    if (
        result.manifest.schema_version != 4
        or result.manifest.plan != frozen.resolution.result_plan
        or result.manifest.research_result_fingerprint != receipt.research_result_fingerprint
        or len(result.manifest.calculation_results) != 1
        or result.manifest.calculation_results[0].calculation_result_fingerprint
        != receipt.calculation_result_fingerprint
    ):
        raise ValueError("CHART_NATIVE_PUBLICATION_RESULT_MISMATCH")
    artifact = OnlyParquetResearchCalculationArtifactStoreV2(artifact_root).load_verified(
        receipt.artifact_content_fingerprint,
        research_result_fingerprint=receipt.research_result_fingerprint,
        expected_runtime_provenance=expected_provenance,
    )
    if (
        artifact.manifest.result != result.manifest
        or artifact.manifest.selected_evidence != (evidence,)
        or artifact.manifest.sealed_input != retained
        or artifact.manifest.retained_generation.generation != manifest
        or artifact.manifest.retained_generation.validation != validation
        or not artifact.dataset_table.equals(dataset.table, check_metadata=True)
    ):
        raise ValueError("CHART_NATIVE_PUBLICATION_ARTIFACT_MISMATCH")
    return artifact
