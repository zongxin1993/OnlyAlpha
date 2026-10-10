"""Native-context-bound publication from exact live authorities, never raw derived rows."""

from __future__ import annotations

from onlyalpha.quant_assets.retained_generation import OnlyRetainedRuntimeGenerationProofV1
from onlyalpha.research.calculation.execution import (
    OnlyResearchCalculationNodeOutput,
    OnlyResearchCalculationNodeReadiness,
)
from onlyalpha.research.calculation.execution_evidence_v2 import OnlyResearchCalculationExecutionEvidenceStoreV2
from onlyalpha.research.calculation.execution_provenance import (
    _only_require_research_runtime_execution_context,
    _OnlyResearchRuntimeExecutionContext,
)
from onlyalpha.research.calculation.result_v2_store import OnlyParquetResearchCalculationResultStoreV2
from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.dataset.publication_input import (
    _only_require_verified_sealed_chart_publication_input,
    _OnlyVerifiedSealedChartPublicationInput,
)
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore

from .calculation_v2_model import _only_calculation_artifact_reference_manifest
from .calculation_v2_sections import _section_tables
from .calculation_v2_store import OnlyParquetResearchCalculationArtifactStoreV2
from .calculation_v2_verification import OnlyResearchCalculationArtifactV2
from .errors import OnlyResearchArtifactError


class OnlyResearchCalculationArtifactMaterializerV2:
    def __init__(
        self,
        results: OnlyJsonResearchResultStore,
        datasets: OnlyParquetResearchDatasetSnapshotStore,
        calculations: OnlyParquetResearchCalculationResultStoreV2,
        evidence: OnlyResearchCalculationExecutionEvidenceStoreV2,
    ) -> None:
        if any(
            type(value) is not expected
            for value, expected in (
                (results, OnlyJsonResearchResultStore),
                (datasets, OnlyParquetResearchDatasetSnapshotStore),
                (calculations, OnlyParquetResearchCalculationResultStoreV2),
                (evidence, OnlyResearchCalculationExecutionEvidenceStoreV2),
            )
        ):
            raise ValueError("native Artifact publication requires explicit owning stores")
        self._results, self._datasets, self._calculations, self._evidence = results, datasets, calculations, evidence

    def publish(
        self,
        result_plan_fingerprint: str,
        evidence_selection: tuple[tuple[str, str], ...],
        *,
        runtime_context: _OnlyResearchRuntimeExecutionContext,
        retained_generation: OnlyRetainedRuntimeGenerationProofV1,
        verified_input: _OnlyVerifiedSealedChartPublicationInput,
        artifact_store: OnlyParquetResearchCalculationArtifactStoreV2,
    ) -> OnlyResearchCalculationArtifactV2:
        try:
            if type(artifact_store) is not OnlyParquetResearchCalculationArtifactStoreV2:
                raise ValueError("exact Artifact V2 publication boundary required")
            result = self._results.load_verified(result_plan_fingerprint)
            if result.manifest.schema_version != 4:
                raise ValueError("Artifact V2 requires explicitly selected Result V4")
            expected = tuple(item.calculation_fingerprint for item in result.manifest.calculation_results)
            if (
                type(evidence_selection) is not tuple
                or any(
                    type(item) is not tuple or len(item) != 2 or any(type(value) is not str for value in item)
                    for item in evidence_selection
                )
                or tuple(item[0] for item in evidence_selection) != expected
            ):
                raise ValueError("explicit Evidence selection must be a complete canonical bijection")
            dataset = self._datasets.load_verified_table(result.manifest.dataset_snapshot_fingerprint)
            calculations = tuple(self._calculations.load_verified(identity) for identity in expected)
            selected = tuple(self._evidence.load_verified(identity) for _, identity in evidence_selection)
            for calculation in calculations:
                context = _only_require_research_runtime_execution_context(
                    runtime_context, calculation.manifest.calculation_graph_fingerprint
                )
                retained_generation.require_graph_implementations(
                    calculation.manifest.calculation_graph, context.implementation_bindings
                )
            sealed_input = _only_require_verified_sealed_chart_publication_input(
                verified_input,
                result_plan_fingerprint,
                runtime_context.graph_fingerprint,
                runtime_context.provenance.runtime_generation_fingerprint,
            )
            sealed_input.verify_snapshot(dataset.snapshot)
            tables = {}
            offset = 0
            for partition in dataset.snapshot.partitions:
                tables[f"dataset/{partition.relative_path}"] = dataset.table.slice(offset, partition.row_count)
                offset += partition.row_count
            for calculation in calculations:
                outputs: tuple[OnlyResearchCalculationNodeOutput | OnlyResearchCalculationNodeReadiness, ...] = (
                    *calculation.outputs,
                    *calculation.readiness,
                )
                for calculation_partition, output in zip(
                    (*calculation.manifest.value_partitions, *calculation.manifest.readiness_partitions),
                    outputs,
                    strict=True,
                ):
                    tables[
                        f"calculations/{calculation.manifest.calculation_fingerprint}/{calculation_partition.relative_path}"
                    ] = output.table
            manifest = _only_calculation_artifact_reference_manifest(
                result=result.manifest,
                dataset=dataset.snapshot,
                calculations=tuple(item.manifest for item in calculations),
                selected_evidence=selected,
                retained_generation=retained_generation,
                sealed_input=sealed_input,
            )
            if manifest.expected_runtime_provenance != runtime_context.provenance or any(
                tuple(
                    (item.node_fingerprint, item.research_implementation_fingerprint)
                    for item in value.research_implementation_bindings
                )
                != runtime_context.implementation_bindings
                for value in selected
            ):
                raise ValueError("selected Evidence differs from verified native composition expectation")

            def acknowledge() -> None:
                current_input = _only_require_verified_sealed_chart_publication_input(
                    verified_input,
                    result_plan_fingerprint,
                    runtime_context.graph_fingerprint,
                    runtime_context.provenance.runtime_generation_fingerprint,
                )
                if current_input != manifest.sealed_input:
                    raise ValueError("sealed input changed after materialization")
                _only_require_research_runtime_execution_context(runtime_context, runtime_context.graph_fingerprint)
                current_dataset = self._datasets.acknowledge_exact(dataset.snapshot.snapshot_fingerprint)
                if current_dataset.snapshot != dataset.snapshot or not current_dataset.table.equals(
                    dataset.table, check_metadata=True
                ):
                    raise ValueError("Dataset changed after materialization")
                reloaded = self._results.acknowledge_exact(
                    result_plan_fingerprint, result.manifest.research_result_fingerprint
                )
                if reloaded.manifest != result.manifest:
                    raise ValueError("Research Result changed after materialization")
                for original in selected:
                    if self._evidence.acknowledge_exact(original.evidence_fingerprint) != original:
                        raise ValueError("selected Evidence changed after materialization")

            tables.update(
                _section_tables(
                    manifest, dataset.table, {item.manifest.calculation_fingerprint: item for item in calculations}
                )
            )
            return artifact_store._publish_materialized(manifest, tables, acknowledge_predecessors=acknowledge)
        except OnlyResearchArtifactError:
            raise
        except Exception as exc:
            raise OnlyResearchArtifactError("ARTIFACT_INVALID", str(exc)) from exc
