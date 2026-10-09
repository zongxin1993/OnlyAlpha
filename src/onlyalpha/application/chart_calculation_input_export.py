"""Read-only T1/T2/D2 and original sealed-source export; no execution permission."""

from __future__ import annotations

from typing import cast

from onlyalpha.application.chart_calculation import OnlyChartCalculationError
from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationInputVerifier
from onlyalpha.application.chart_calculation_compilation_ports import (
    OnlyChartCalculationCompilationStore,
    OnlyChartCalculationPreparationReader,
)
from onlyalpha.application.chart_calculation_ports import OnlyChartCalculationAdmissionStore
from onlyalpha.application.integration_runtime import OnlyIntegrationRuntimeBindingV1, OnlyIntegrationRuntimeStateReader
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json, only_canonical_payload
from onlyalpha.data.models import OnlyBarUpdate, OnlyMarketDataInboundUpdate
from onlyalpha.market_data.durable.ports import OnlyMarketDataCatalog, OnlyMarketFactStore
from onlyalpha.market_data.durable.revision import OnlyHistoricalMarketDataQueryService
from onlyalpha.plugin.integration import OnlyIntegrationCategory
from onlyalpha.research.dataset.codec import only_bars_to_table
from onlyalpha.research.dataset.identity import only_canonical_bars
from onlyalpha.research.dataset.lineage import OnlyDatasetMaterializationStore
from onlyalpha.research.dataset.publication_input import (
    _only_issue_verified_sealed_chart_publication_input,
    _OnlyVerifiedSealedChartPublicationInput,
)
from onlyalpha.research.dataset.sealed_input_evidence import (
    OnlyRetainedSealedChartInputEvidenceV1,
    _segment_payload,
)


class OnlyChartCalculationInputExportService:
    """Composition uses existing verified owning readers; no new Source Authority."""

    def __init__(
        self,
        *,
        operations: OnlyChartCalculationAdmissionStore,
        preparations: OnlyChartCalculationPreparationReader,
        compilations: OnlyChartCalculationCompilationStore,
        inputs: OnlyChartCalculationInputVerifier,
        integrations: OnlyIntegrationRuntimeStateReader,
        catalog: OnlyMarketDataCatalog,
        facts: OnlyMarketFactStore,
        materializations: OnlyDatasetMaterializationStore,
    ) -> None:
        self._operations, self._preparations, self._compilations = operations, preparations, compilations
        self._inputs, self._integrations, self._catalog, self._materializations = (
            inputs,
            integrations,
            catalog,
            materializations,
        )
        self._query = OnlyHistoricalMarketDataQueryService(catalog, facts)

    def export(self, operation_id: OnlyProductCommandId) -> _OnlyVerifiedSealedChartPublicationInput:
        retained, plan, graph, generation = self._read(operation_id)

        def reverify() -> OnlyRetainedSealedChartInputEvidenceV1:
            current, current_plan, current_graph, current_generation = self._read(operation_id)
            if (current_plan, current_graph, current_generation) != (plan, graph, generation):
                raise OnlyChartCalculationError("CHART_COMPILATION_RELATION_CORRUPT")
            return current

        return _only_issue_verified_sealed_chart_publication_input(retained, plan, graph, generation, reverify)

    def _read(self, operation_id: OnlyProductCommandId) -> tuple[OnlyRetainedSealedChartInputEvidenceV1, str, str, str]:
        if type(operation_id) is not OnlyProductCommandId:
            raise OnlyChartCalculationError("CHART_OPERATION_RELATION_CORRUPT")
        operation = self._operations.load_verified(operation_id)
        if operation is None:
            raise OnlyChartCalculationError("CHART_OPERATION_NOT_FOUND")
        if operation.operation_id != operation_id:
            raise OnlyChartCalculationError("CHART_OPERATION_RELATION_CORRUPT")
        preparation = self._preparations.load_verified(operation)
        if preparation is None or preparation.state != "INPUT_READY":
            raise OnlyChartCalculationError("CHART_INPUT_NOT_READY")
        compilation = self._compilations.load_verified(operation)
        if compilation is None:
            raise OnlyChartCalculationError("CHART_COMPILATION_NOT_FOUND")
        dataset = self._inputs.verify_frozen(operation, preparation, compilation)
        pin = preparation.input_pin
        assert pin is not None
        raw = pin.to_dict()
        reference = cast(dict[str, object], raw["source_reference"])
        scope = pin.scope
        assert scope.bar_construction is not None
        integration_revision = self._integrations.load_revision(
            cast(str, reference["integration_revision_fingerprint"])
        )
        descriptor = integration_revision.type_descriptor_document
        binding = OnlyIntegrationRuntimeBindingV1.from_revision(
            integration_revision, OnlyIntegrationCategory.DATA_SOURCE
        )
        if (
            integration_revision.integration_id.value != reference["integration_id"]
            or integration_revision.revision_fingerprint != reference["integration_revision_fingerprint"]
            or integration_revision.type_id != reference["expected_type_id"]
            or descriptor["category"] != OnlyIntegrationCategory.DATA_SOURCE.value
            or only_canonical_fingerprint(descriptor) != integration_revision.type_descriptor_fingerprint
            or binding.binding_fingerprint != raw["integration_binding_fingerprint"]
        ):
            raise OnlyChartCalculationError("CHART_INPUT_EVIDENCE_CORRUPT")
        revision, seal = self._query.resolve_with_seal(pin.revision_id)
        manifest = self._catalog.load_coverage_manifest(revision.manifest_id)
        segments = self._catalog.load_durable_segments(tuple(item[0] for item in revision.segment_refs))
        proofs = self._catalog.load_physical_proofs(tuple(item[0] for item in revision.segment_refs))
        evidence = {"revision": revision, "manifest": manifest, "seal": seal, "physical_proofs": proofs}
        if only_canonical_payload(evidence) != raw["evidence"]:
            raise OnlyChartCalculationError("CHART_INPUT_EVIDENCE_CORRUPT")
        # Exact historical read re-verifies original physical partitions and coverage.
        # Project native bars mechanically and compare, without materializing/writing.
        source_bars = []
        for fact in self._query.read_exact(pin.revision_id, scope):
            update = OnlyMarketDataInboundUpdate.from_dict(fact.canonical_payload)
            if not isinstance(update.payload, OnlyBarUpdate):
                raise OnlyChartCalculationError("CHART_INPUT_EVIDENCE_CORRUPT")
            source_bars.append(update.payload.bar)
        if not dataset.table.equals(only_bars_to_table(only_canonical_bars(tuple(source_bars))), check_metadata=True):
            raise OnlyChartCalculationError("CHART_INPUT_EVIDENCE_CORRUPT")
        materialization = self._materializations.load_materialization(compilation.dataset_materialization_id)
        retained = OnlyRetainedSealedChartInputEvidenceV1(
            only_canonical_json(
                {
                    "schema_version": 1,
                    "source_reference": reference,
                    "source_selection": raw["source_selection"],
                    "integration_binding": binding.to_dict(),
                    "integration_binding_fingerprint": raw["integration_binding_fingerprint"],
                    "scope": raw["scope"],
                    "evidence": only_canonical_payload(evidence),
                    "segments": [_segment_payload(item) for item in segments],
                    "materialization": cast(
                        dict[str, object], only_canonical_payload(materialization.semantic_payload())
                    )
                    | {"materialization_id": materialization.materialization_id},
                    "dataset_snapshot_fingerprint": dataset.snapshot.snapshot_fingerprint,
                }
            )
        )
        retained.verify_snapshot(dataset.snapshot)
        return (
            retained,
            compilation.result_plan_fingerprint,
            compilation.graph_fingerprint,
            compilation.runtime_generation_fingerprint,
        )
