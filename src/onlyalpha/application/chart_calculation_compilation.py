"""Immutable chart input -> exact hosted compilation; never numeric execution or a Run."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import cast

from onlyalpha.application.chart_calculation import OnlyChartCalculationError, OnlyChartCalculationOperationV1
from onlyalpha.application.chart_calculation_compilation_ports import (
    OnlyChartCalculationCompilationStore,
    OnlyChartCalculationPreparationReader,
    OnlyChartCalculationPublicationResolver,
)
from onlyalpha.application.chart_calculation_preparation import (
    OnlyChartCalculationInputPinV1,
    OnlyChartCalculationPreparationV1,
    OnlyChartCalculationRuntimeBindingReferenceV1,
)
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.application.runtime_generation import OnlyRuntimeGenerationWorkAuthority, OnlyRuntimeWorkBindingEvidence
from onlyalpha.application.search_generation_execution import (
    OnlyHistoricalGenerationCapabilityUnsupported,
    OnlyHistoricalGenerationExecutionError,
    OnlyHistoricalGenerationExecutionMismatch,
)
from onlyalpha.calculation.definition import OnlyCalculationKind, OnlyCalculationScalar, OnlyCalculationTypeReference
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.calculation.publication import OnlyResearchCalculationPublicationSelectionV1
from onlyalpha.research.dataset.lineage import (
    OnlyDatasetMaterialization,
    OnlyDatasetMaterializationStore,
    OnlyMarketDataRevisionBinding,
)
from onlyalpha.research.dataset.manifest import OnlyResearchDatasetSnapshot
from onlyalpha.research.dataset.market_data_materializer import only_sealed_market_data_input_fingerprints
from onlyalpha.research.dataset.parquet_store import OnlyResearchDatasetStoreError
from onlyalpha.research.dataset.ports import OnlyResearchDatasetSnapshotStore, OnlyVerifiedResearchDataset
from onlyalpha.research.job.errors import OnlyResearchJobError
from onlyalpha.research.run.calculation_resolution import OnlyResearchCalculationRuntimeResolutionV1
from onlyalpha.research.runtime_errors import OnlyResearchRuntimeError
from onlyalpha.research.specification.errors import OnlyResearchSpecificationError
from onlyalpha.research.specification.model import (
    OnlyResearchCalculationSpec,
    OnlyResearchSeriesSelector,
    OnlyResearchSpecification,
)
from onlyalpha.research.sweep.errors import OnlyResearchSweepError
from onlyalpha.research.sweep.template import OnlyResearchGraphTemplate, OnlyResearchGraphTemplateNode

_SHA = re.compile(r"[0-9a-f]{64}")
_CORRUPT = "CHART_COMPILATION_RELATION_CORRUPT"
_CONFLICT = "CHART_SPECIFICATION_COMPILATION_CONFLICT"
_INPUT_CORRUPT = "CHART_INPUT_EVIDENCE_CORRUPT"
_RUNTIME_UNAVAILABLE_ERRORS = frozenset(
    {
        "RUNTIME_GENERATION_NOT_FOUND",
        "RUNTIME_GENERATION_UNAVAILABLE",
        "RUNTIME_GENERATION_EVENT_INVALID",
        "RUNTIME_GENERATION_EVENT_CHAIN_CORRUPT",
        "RUNTIME_GENERATION_EVENT_ORDER_INVALID",
        "RUNTIME_GENERATION_MANIFEST_MISMATCH",
        "RUNTIME_GENERATION_VALIDATION_EVIDENCE_MISMATCH",
    }
)
_SHAPE_ERRORS = (
    TypeError,
    ValueError,
    KeyError,
    OnlyResearchJobError,
    OnlyResearchRuntimeError,
    OnlyResearchSweepError,
)


def _require(condition: bool, code: str = _CORRUPT) -> None:
    if not condition:
        raise OnlyChartCalculationError(code)


def _sha(value: object) -> bool:
    return type(value) is str and _SHA.fullmatch(value) is not None


def _materialization_id(value: object) -> bool:
    prefix = "dataset-materialization:"
    return type(value) is str and value.startswith(prefix) and _sha(value.removeprefix(prefix))


def _verified_ready_pin(
    operation: OnlyChartCalculationOperationV1, preparation: OnlyChartCalculationPreparationV1 | None
) -> OnlyChartCalculationInputPinV1:
    _require(type(operation) is OnlyChartCalculationOperationV1, _INPUT_CORRUPT)
    operation.__post_init__()
    operation.intent.__post_init__()
    operation.catalog_witness.__post_init__()
    _require(preparation is not None, "CHART_INPUT_NOT_READY")
    _require(type(preparation) is OnlyChartCalculationPreparationV1, _INPUT_CORRUPT)
    assert preparation is not None
    _require(preparation.state == "INPUT_READY", "CHART_INPUT_NOT_READY")
    preparation.__post_init__()
    pin = preparation.input_pin
    reference = preparation.runtime_binding_reference
    _require(
        preparation.operation_id == operation.operation_id
        and preparation.runtime_work_id == operation.reserved_run_id.value
        and preparation.fact_schema_version == 2
        and type(pin) is OnlyChartCalculationInputPinV1
        and type(reference) is OnlyChartCalculationRuntimeBindingReferenceV1
        and _sha(preparation.dataset_snapshot_fingerprint)
        and _materialization_id(preparation.dataset_materialization_id),
        _INPUT_CORRUPT,
    )
    assert pin is not None and reference is not None
    pin.__post_init__()
    reference.__post_init__()
    _require(
        reference.work_id == operation.reserved_run_id.value
        and reference.runtime_generation_fingerprint == preparation.runtime_generation_fingerprint,
        "CHART_RUNTIME_BINDING_CONFLICT",
    )
    pin.verify_operation(operation, preparation.runtime_generation_fingerprint)
    return pin


def only_chart_calculation_specification_v3(
    operation: OnlyChartCalculationOperationV1, preparation: OnlyChartCalculationPreparationV1
) -> OnlyResearchSpecification:
    """Copy admitted normalized intent; the hosted registered compiler selects inputs."""
    _verified_ready_pin(operation, preparation)
    selection = cast(dict[str, object], operation.intent.to_dict()["calculation"])
    reference = OnlyCalculationTypeReference(
        OnlyCalculationKind(cast(str, selection["kind"])),
        cast(str, selection["type_id"]),
        cast(str, selection["semantic_version"]),
    )
    template = OnlyResearchGraphTemplate(
        (
            OnlyResearchGraphTemplateNode(
                "indicator",
                reference,
                dict(cast(Mapping[str, OnlyCalculationScalar], selection["parameters"])),
            ),
        )
    )
    return OnlyResearchSpecification(
        cast(str, preparation.dataset_snapshot_fingerprint),
        (OnlyResearchCalculationSpec("chart_calculation", template),),
        (),
        schema_version=3,
        purpose="CALCULATION_PUBLICATION",
        published_series=(
            OnlyResearchSeriesSelector("chart_calculation", "indicator", cast(str, selection["output_name"])),
        ),
        publication=OnlyResearchCalculationPublicationSelectionV1(),
    )


@dataclass(frozen=True, slots=True)
class OnlyChartCalculationCompilationV1:
    operation_id: OnlyProductCommandId
    intent_fingerprint: str
    catalog_witness_fingerprint: str
    input_preparation_revision: int
    input_preparation_fence: int
    input_selection_fingerprint: str
    dataset_snapshot_fingerprint: str
    dataset_materialization_id: str
    runtime_generation_fingerprint: str
    runtime_work_id: str
    runtime_binding_reference: OnlyChartCalculationRuntimeBindingReferenceV1
    catalog_implementation_fingerprint: str
    specification: OnlyResearchSpecification
    resolution: OnlyResearchCalculationRuntimeResolutionV1
    schema_version: int = 1

    def __post_init__(self) -> None:
        _require(type(self.operation_id) is OnlyProductCommandId)
        _require(type(self.schema_version) is int and self.schema_version == 1)
        _require(
            type(self.input_preparation_revision) is int
            and type(self.input_preparation_fence) is int
            and 1 <= self.input_preparation_fence <= self.input_preparation_revision
        )
        _require(
            all(
                _sha(value)
                for value in (
                    self.intent_fingerprint,
                    self.catalog_witness_fingerprint,
                    self.input_selection_fingerprint,
                    self.dataset_snapshot_fingerprint,
                    self.runtime_generation_fingerprint,
                    self.catalog_implementation_fingerprint,
                )
            )
        )
        _require(_materialization_id(self.dataset_materialization_id))
        try:
            _require(type(self.runtime_work_id) is str and self.runtime_work_id != self.operation_id.value)
            OnlyProductCommandId(self.runtime_work_id)
            _require(type(self.runtime_binding_reference) is OnlyChartCalculationRuntimeBindingReferenceV1)
            reference = OnlyChartCalculationRuntimeBindingReferenceV1.from_dict(
                self.runtime_binding_reference.to_dict()
            )
            _require(
                reference.work_id == self.runtime_work_id
                and reference.runtime_generation_fingerprint == self.runtime_generation_fingerprint
            )
            _require(type(self.specification) is OnlyResearchSpecification)
            spec = OnlyResearchSpecification.from_dict(self.specification.to_dict())
            _require(type(self.resolution) is OnlyResearchCalculationRuntimeResolutionV1)
            resolution = OnlyResearchCalculationRuntimeResolutionV1.from_dict(self.resolution.to_dict())
            _require(spec == self.specification and resolution == self.resolution)
            _require(
                spec.schema_version == 3
                and spec.dataset_snapshot_fingerprint == self.dataset_snapshot_fingerprint
                and resolution.specification == spec
                and resolution.runtime_generation_fingerprint == self.runtime_generation_fingerprint
                and resolution.implementation_manifest.implementation_fingerprint
                == self.catalog_implementation_fingerprint
            )
            (calculation,) = spec.calculations
            (node,) = calculation.graph_template.nodes
            _require(
                calculation.calculation_id == "chart_calculation"
                and node.template_node_id == "indicator"
                and node.input_bindings == ()
            )
        except _SHAPE_ERRORS as exc:
            raise OnlyChartCalculationError(_CORRUPT) from exc

    @property
    def specification_fingerprint(self) -> str:
        return self.specification.specification_fingerprint

    @property
    def result_plan_fingerprint(self) -> str:
        return self.resolution.result_plan.fingerprint

    @property
    def graph_fingerprint(self) -> str:
        return self.resolution.graph_fingerprint

    @property
    def calculation_fingerprint(self) -> str:
        return self.resolution.calculation_fingerprint

    @property
    def implementation_fingerprint(self) -> str:
        return self.resolution.implementation_manifest.implementation_fingerprint

    @property
    def compilation_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {"domain": "onlyalpha.chart-calculation-compilation.v1", "relation": self.to_dict()}
        )

    def to_dict(self) -> dict[str, object]:
        result = {item.name: getattr(self, item.name) for item in fields(self)}
        return result | {
            "operation_id": self.operation_id.value,
            "runtime_binding_reference": self.runtime_binding_reference.to_dict(),
            "specification": self.specification.to_dict(),
            "resolution": self.resolution.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> OnlyChartCalculationCompilationV1:
        try:
            _require(isinstance(raw, Mapping) and set(raw) == {item.name for item in fields(cls)})
            _require(type(raw["operation_id"]) is str)
            return cls(
                OnlyProductCommandId(cast(str, raw["operation_id"])),
                cast(str, raw["intent_fingerprint"]),
                cast(str, raw["catalog_witness_fingerprint"]),
                cast(int, raw["input_preparation_revision"]),
                cast(int, raw["input_preparation_fence"]),
                cast(str, raw["input_selection_fingerprint"]),
                cast(str, raw["dataset_snapshot_fingerprint"]),
                cast(str, raw["dataset_materialization_id"]),
                cast(str, raw["runtime_generation_fingerprint"]),
                cast(str, raw["runtime_work_id"]),
                OnlyChartCalculationRuntimeBindingReferenceV1.from_dict(
                    cast(dict[str, object], raw["runtime_binding_reference"])
                ),
                cast(str, raw["catalog_implementation_fingerprint"]),
                OnlyResearchSpecification.from_dict(cast(Mapping[str, object], raw["specification"])),
                OnlyResearchCalculationRuntimeResolutionV1.from_dict(cast(Mapping[str, object], raw["resolution"])),
                cast(int, raw["schema_version"]),
            )
        except _SHAPE_ERRORS as exc:
            raise OnlyChartCalculationError(_CORRUPT) from exc

    def verify_operation_preparation(
        self, operation: OnlyChartCalculationOperationV1, preparation: OnlyChartCalculationPreparationV1
    ) -> None:
        """Prove exact occurrence ownership, not just self-consistent nested identities."""
        self.__post_init__()
        _verified_ready_pin(operation, preparation)
        _require(
            self.operation_id == operation.operation_id
            and self.intent_fingerprint == operation.intent_fingerprint
            and self.catalog_witness_fingerprint == operation.catalog_witness.fingerprint
            and self.input_preparation_revision == preparation.revision
            and self.input_preparation_fence == preparation.fence
            and self.input_selection_fingerprint == preparation.input_selection_fingerprint
            and self.dataset_snapshot_fingerprint == preparation.dataset_snapshot_fingerprint
            and self.dataset_materialization_id == preparation.dataset_materialization_id
            and self.runtime_generation_fingerprint == preparation.runtime_generation_fingerprint
            and self.runtime_work_id == operation.reserved_run_id.value
            and self.runtime_binding_reference == preparation.runtime_binding_reference
            and self.specification == only_chart_calculation_specification_v3(operation, preparation),
            _CONFLICT,
        )
        capability = operation.catalog_witness.capability
        manifest = self.resolution.implementation_manifest
        _require(
            self.catalog_implementation_fingerprint == capability.implementation_fingerprint
            and manifest.calculation_type_reference.kind == capability.kind
            and manifest.calculation_type_reference.type_id == capability.type_id
            and manifest.calculation_type_reference.semantic_version == capability.semantic_version
            and manifest.backend_kind == capability.backend,
            _CORRUPT,
        )


class OnlyChartCalculationInputVerifier:
    """Shared immutable input/runtime proof for compilation and typed Run handoff."""

    def __init__(
        self,
        *,
        datasets: OnlyResearchDatasetSnapshotStore,
        materializations: OnlyDatasetMaterializationStore,
        runtime_generations: OnlyRuntimeGenerationWorkAuthority,
    ) -> None:
        self._datasets = datasets
        self._materializations = materializations
        self._runtime = runtime_generations

    def binding(
        self, preparation: OnlyChartCalculationPreparationV1, *, require_active: bool
    ) -> OnlyRuntimeWorkBindingEvidence:
        try:
            binding = self._runtime.require_work_binding_evidence(preparation.runtime_work_id)
        except ValueError as exc:
            if str(exc) in {"RUNTIME_WORK_GENERATION_UNBOUND", "RUNTIME_WORK_BINDING_EVIDENCE_INVALID"}:
                raise OnlyChartCalculationError("CHART_RUNTIME_BINDING_CONFLICT") from exc
            if str(exc) in _RUNTIME_UNAVAILABLE_ERRORS:
                raise OnlyChartCalculationError("CHART_EXECUTION_GENERATION_UNAVAILABLE") from exc
            raise
        except RuntimeError as exc:
            if str(exc) != "RUNTIME_GENERATION_WORK_AUTHORITY_UNAVAILABLE":
                raise
            raise OnlyChartCalculationError("CHART_EXECUTION_GENERATION_UNAVAILABLE") from exc
        _require(type(binding) is OnlyRuntimeWorkBindingEvidence, "CHART_RUNTIME_BINDING_CONFLICT")
        assert preparation.runtime_binding_reference is not None
        preparation.runtime_binding_reference.verifies(binding, require_active=False)
        _require(not require_active or binding.active, "CHART_RUNTIME_BINDING_INACTIVE")
        return binding

    def dataset(self, preparation: OnlyChartCalculationPreparationV1, pin: OnlyChartCalculationInputPinV1) -> None:
        """Verify physical Snapshot and full pinned lineage without rematerializing anything."""
        assert (
            preparation.dataset_snapshot_fingerprint is not None and preparation.dataset_materialization_id is not None
        )
        try:
            verified = self._datasets.load_verified_table(preparation.dataset_snapshot_fingerprint)
            _require(type(verified) is OnlyVerifiedResearchDataset, _INPUT_CORRUPT)
            _require(type(verified.snapshot) is OnlyResearchDatasetSnapshot, _INPUT_CORRUPT)
            snapshot = OnlyResearchDatasetSnapshot.from_dict(verified.snapshot.to_dict())
            materialization = self._materializations.load_materialization(preparation.dataset_materialization_id)
            _require(type(materialization) is OnlyDatasetMaterialization, _INPUT_CORRUPT)
            materialization.__post_init__()
            scope = pin.scope
            assert scope.bar_construction is not None
            evidence = cast(dict[str, dict[str, object]], pin.to_dict()["evidence"])
            revision = evidence["revision"]
            expected_bindings = (
                OnlyMarketDataRevisionBinding(
                    scope.source_id,
                    scope.instrument_id,
                    scope.data_kind,
                    pin.revision_id,
                    cast(str, revision["fingerprint"]),
                ),
            )
            construction, request = only_sealed_market_data_input_fingerprints(
                pin.materialization_plan(),
                (
                    (
                        scope.instrument_id,
                        scope.bar_construction.fingerprint,
                        cast(str, revision["fingerprint"]),
                        cast(str, evidence["seal"]["seal_id"]),
                    ),
                ),
            )
            _require(
                snapshot.snapshot_fingerprint == preparation.dataset_snapshot_fingerprint
                and snapshot.definition == pin.materialization_plan().definition
                and snapshot.construction_fingerprint == construction
                and snapshot.row_count == verified.table.num_rows
                and materialization.materialization_id == preparation.dataset_materialization_id
                and materialization.dataset_snapshot_fingerprint == snapshot.snapshot_fingerprint
                and materialization.market_data_revision_bindings == expected_bindings
                and materialization.materializer_id == "onlyalpha.sealed-market-data"
                and materialization.materializer_version == "1"
                and materialization.request_fingerprint == request,
                _INPUT_CORRUPT,
            )
            _require(len(snapshot.provenance) == 1, _INPUT_CORRUPT)
            (provenance,) = snapshot.provenance
            bounds = ((str(scope.start_ns), str(scope.end_ns)),)
            _require(
                provenance.source_id == scope.source_id
                and provenance.instrument_id == scope.instrument_id
                and provenance.data_version == scope.data_version
                and provenance.plugin_id == "durable-market-data"
                and provenance.plugin_version == "1"
                and provenance.cache_content_fingerprint is None
                and provenance.resolved_ranges == bounds
                and provenance.observed_ranges == bounds
                and provenance.source_metadata
                == {
                    "bar_construction_fingerprint": scope.bar_construction.fingerprint,
                    "construction_recipe": scope.bar_construction.plan.resolved_recipe.to_dict(),
                },
                _INPUT_CORRUPT,
            )
        except (*_SHAPE_ERRORS, OSError, OnlyResearchDatasetStoreError) as exc:
            raise OnlyChartCalculationError(_INPUT_CORRUPT) from exc

    def generation(
        self,
        operation: OnlyChartCalculationOperationV1,
        preparation: OnlyChartCalculationPreparationV1,
        *,
        historical: bool = False,
    ) -> None:
        try:
            reader = (
                self._runtime.require_historical_generation if historical else self._runtime.require_runtime_generation
            )
            manifest = reader(preparation.runtime_generation_fingerprint)
        except ValueError as exc:
            if str(exc) not in _RUNTIME_UNAVAILABLE_ERRORS:
                raise
            raise OnlyChartCalculationError("CHART_EXECUTION_GENERATION_UNAVAILABLE") from exc
        except RuntimeError as exc:
            if str(exc) != "RUNTIME_GENERATION_WORK_AUTHORITY_UNAVAILABLE":
                raise
            raise OnlyChartCalculationError("CHART_EXECUTION_GENERATION_UNAVAILABLE") from exc
        context = cast(dict[str, object], operation.catalog_witness.to_dict()["context"])
        _require(
            getattr(manifest, "runtime_generation_fingerprint", None) == preparation.runtime_generation_fingerprint
            and getattr(manifest, "catalog_generation_fingerprint", None) == context["catalog_generation_fingerprint"],
            "CHART_EXECUTION_GENERATION_UNAVAILABLE",
        )

    def verify_frozen(
        self,
        operation: OnlyChartCalculationOperationV1,
        preparation: OnlyChartCalculationPreparationV1,
        compilation: OnlyChartCalculationCompilationV1,
    ) -> None:
        pin = _verified_ready_pin(operation, preparation)
        compilation.verify_operation_preparation(operation, preparation)
        self.binding(preparation, require_active=False)
        self.dataset(preparation, pin)
        self.generation(operation, preparation, historical=True)


class OnlyChartCalculationCompilationService:
    def __init__(
        self,
        *,
        preparations: OnlyChartCalculationPreparationReader,
        datasets: OnlyResearchDatasetSnapshotStore,
        materializations: OnlyDatasetMaterializationStore,
        runtime_generations: OnlyRuntimeGenerationWorkAuthority,
        resolver: OnlyChartCalculationPublicationResolver,
        compilations: OnlyChartCalculationCompilationStore,
    ) -> None:
        self._preparations = preparations
        self._resolver = resolver
        self._compilations = compilations
        self._inputs = OnlyChartCalculationInputVerifier(
            datasets=datasets, materializations=materializations, runtime_generations=runtime_generations
        )

    def compile(self, operation: OnlyChartCalculationOperationV1) -> OnlyChartCalculationCompilationV1:
        _require(type(operation) is OnlyChartCalculationOperationV1, _INPUT_CORRUPT)
        preparation = self._preparations.load_verified(operation)
        pin = _verified_ready_pin(operation, preparation)
        assert preparation is not None
        binding = self._inputs.binding(preparation, require_active=False)
        self._inputs.dataset(preparation, pin)
        existing = self._compilations.load_verified(operation)
        if existing is not None:
            _require(type(existing) is OnlyChartCalculationCompilationV1)
            existing.verify_operation_preparation(operation, preparation)
            return existing
        _require(binding.active, "CHART_RUNTIME_BINDING_INACTIVE")
        self._inputs.generation(operation, preparation)
        specification = only_chart_calculation_specification_v3(operation, preparation)
        try:
            resolution = self._resolver.resolve_calculation_publication(
                preparation.runtime_generation_fingerprint, specification
            )
        except OnlyHistoricalGenerationExecutionMismatch as exc:
            raise OnlyChartCalculationError(_CORRUPT) from exc
        except OnlyHistoricalGenerationCapabilityUnsupported as exc:
            raise OnlyChartCalculationError("CHART_READINESS_CAPABILITY_UNAVAILABLE") from exc
        except OnlyHistoricalGenerationExecutionError as exc:
            raise OnlyChartCalculationError("CHART_EXECUTION_GENERATION_UNAVAILABLE") from exc
        except OnlyResearchSpecificationError as exc:
            if exc.code != "RESEARCH_SPEC_READINESS_BACKEND_UNAVAILABLE":
                raise
            raise OnlyChartCalculationError("CHART_READINESS_CAPABILITY_UNAVAILABLE") from exc
        compilation = OnlyChartCalculationCompilationV1(
            operation.operation_id,
            operation.intent_fingerprint,
            operation.catalog_witness.fingerprint,
            preparation.revision,
            preparation.fence,
            pin.fingerprint,
            cast(str, preparation.dataset_snapshot_fingerprint),
            cast(str, preparation.dataset_materialization_id),
            preparation.runtime_generation_fingerprint,
            preparation.runtime_work_id,
            cast(OnlyChartCalculationRuntimeBindingReferenceV1, preparation.runtime_binding_reference),
            operation.catalog_witness.capability.implementation_fingerprint,
            specification,
            resolution,
        )
        compilation.verify_operation_preparation(operation, preparation)
        current = self._preparations.load_verified(operation)
        _verified_ready_pin(operation, current)
        assert current is not None
        compilation.verify_operation_preparation(operation, current)
        self._inputs.binding(current, require_active=True)
        committed = self._compilations.commit_or_replay(operation, current, compilation)
        _require(type(committed) is OnlyChartCalculationCompilationV1)
        committed.verify_operation_preparation(operation, current)
        _require(committed == compilation, _CONFLICT)
        return committed
