"""Fenced chart input preparation; no Specification, Run or numeric execution."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from onlyalpha.application.chart_calculation import (
    OnlyChartCalculationError,
    OnlyChartCalculationOperationV1,
    OnlyChartCalculationRequestV1,
)
from onlyalpha.application.market_data_product import (
    OnlyMarketDataProductService,
    OnlyMarketDataSelectionPlanV1,
    OnlyMarketDataSourceReferenceV1,
)
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.application.runtime_generation import (
    OnlyRuntimeGenerationWorkAuthority,
    OnlyRuntimeWorkAdmissionClosureEvidence,
    OnlyRuntimeWorkBindingEvidence,
)
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json, only_canonical_payload
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarSemantic
from onlyalpha.market_data.durable.models import (
    OnlyCoverageManifest,
    OnlyCoverageStatus,
    OnlyMarketDataPhysicalSegmentProof,
    OnlyMarketDataRevision,
    OnlyMarketDataScope,
)
from onlyalpha.market_data.durable.ports import OnlyMarketDataCatalog, OnlyMarketFactStore
from onlyalpha.market_data.durable.revision import OnlyHistoricalMarketDataQueryService, only_build_seal
from onlyalpha.market_data.resolution import OnlyBarConstructionIdentity, OnlyBarResolutionMode
from onlyalpha.research.dataset.definition import OnlyResearchDatasetDefinition
from onlyalpha.research.dataset.market_data_materializer import (
    OnlySealedMarketDataDatasetMaterializer,
    OnlySealedMarketDataMaterializationPlan,
)

DURATION_NS = 900_000_000_000
# Phase is defined by the producer ordering, never inferred from a missing pin.
_PRE_BIND_FAILURES = frozenset({"CHART_RUNTIME_GENERATION_NOT_ELIGIBLE"})
_POST_BIND_FAILURES = frozenset({"CHART_SEALED_COVERAGE_UNAVAILABLE"})
_BINDING_OWNER = "CHART_CALCULATION_INPUT"


def _require(condition: bool, code: str = "CHART_INPUT_EVIDENCE_CORRUPT") -> None:
    if not condition:
        raise OnlyChartCalculationError(code)


def only_chart_materialization_support(intent: OnlyChartCalculationRequestV1) -> tuple[int, int]:
    value = intent.to_dict()
    bounds = cast(dict[str, str], value["display_range"])
    selection = cast(dict[str, object], value["calculation"])
    parameters = cast(dict[str, object], selection["parameters"])
    period = parameters["period"]
    _require(type(period) is int)
    assert isinstance(period, int)
    _require(1 <= period <= 672)
    start = int(bounds["start_ns"]) - (period - 1) * DURATION_NS
    end = int(bounds["end_ns"])
    _require(0 <= start < end <= 2**63 - 1 and start % 1000 == end % 1000 == 0)
    return start, end


@dataclass(frozen=True, slots=True)
class OnlyChartCalculationInputPinV1:
    """Canonical immutable selection; operational owner is separate from Dataset identity."""

    canonical_json: str

    def __post_init__(self) -> None:
        value = self.to_dict()
        _require(
            set(value)
            == {
                "schema_version",
                "operation_id",
                "intent_fingerprint",
                "source_reference",
                "source_selection",
                "integration_binding_fingerprint",
                "display_range",
                "scope",
                "evidence",
                "runtime_generation_fingerprint",
                "runtime_work_id",
            }
        )
        _require(type(value["schema_version"]) is int and value["schema_version"] == 1)
        OnlyProductCommandId(str(value["operation_id"]))
        OnlyProductCommandId(str(value["runtime_work_id"]))
        for key in ("intent_fingerprint", "integration_binding_fingerprint", "runtime_generation_fingerprint"):
            text = value[key]
            _require(isinstance(text, str) and len(text) == 64 and all(c in "0123456789abcdef" for c in text))
        scope = self.scope
        construction = scope.bar_construction
        _require(construction is not None)
        assert construction is not None
        _require(scope.data_kind == "BAR" and construction.plan.mode is OnlyBarResolutionMode.PROVIDER_NATIVE)
        _require(construction.plan.target_semantic == OnlyBarSemantic.fixed_duration(15))
        _require(scope.first_sequence is None and scope.last_sequence is None)
        evidence = cast(dict[str, object], value["evidence"])
        _require(set(evidence) == {"revision", "manifest", "seal", "physical_proofs"})
        raw_manifest = cast(dict[str, object], evidence["manifest"])
        _require(
            raw_manifest["coverage_status"] == "COMPLETE"
            and raw_manifest["issues"] == []
            and raw_manifest["gaps"] == []
        )
        manifest = OnlyCoverageManifest.build(
            scope,
            tuple((item[0], item[1]) for item in cast(list[list[str]], raw_manifest["segment_refs"])),
            coverage_status=OnlyCoverageStatus.COMPLETE,
            proof=tuple(cast(list[str], raw_manifest["proof"])),
        )
        _require(only_canonical_payload(manifest) == raw_manifest)
        raw_revision = cast(dict[str, object], evidence["revision"])
        revision = OnlyMarketDataRevision.build(
            manifest,
            normalizers=tuple((item[0], item[1]) for item in cast(list[list[str]], raw_revision["normalizers"])),
            creation_reason=cast(str, raw_revision["creation_reason"]),
            parent_revision_id=cast(str | None, raw_revision["parent_revision_id"]),
        )
        _require(only_canonical_payload(revision) == raw_revision)
        raw_seal = cast(dict[str, object], evidence["seal"])
        seal = only_build_seal(revision, manifest, sealed_at=datetime.fromisoformat(cast(str, raw_seal["sealed_at"])))
        _require(only_canonical_payload(seal) == raw_seal)
        proofs = tuple(
            OnlyMarketDataPhysicalSegmentProof.from_dict(item)
            for item in cast(list[dict[str, object]], evidence["physical_proofs"])
        )
        _require(
            bool(proofs) and tuple((p.segment_id, p.segment_content_hash) for p in proofs) == revision.segment_refs
        )
        _require(only_canonical_payload(proofs) == evidence["physical_proofs"])
        _require(self.canonical_json == only_canonical_json(value))

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(self.canonical_json))

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict())

    @property
    def scope(self) -> OnlyMarketDataScope:
        raw = cast(dict[str, object], self.to_dict()["scope"])
        construction = OnlyBarConstructionIdentity.from_canonical_payload(
            cast(Mapping[str, object], raw["bar_construction"])
        )
        return OnlyMarketDataScope(**(raw | {"bar_construction": construction}))  # type: ignore[arg-type]

    @property
    def revision_id(self) -> str:
        evidence = cast(dict[str, dict[str, object]], self.to_dict()["evidence"])
        return cast(str, evidence["revision"]["revision_id"])

    def verify_operation(self, operation: OnlyChartCalculationOperationV1, generation: str) -> None:
        value = self.to_dict()
        intent = operation.intent.to_dict()
        start, end = only_chart_materialization_support(operation.intent)
        source = cast(dict[str, object], intent["source_reference"])
        selection = cast(dict[str, object], value["source_selection"])
        scope = self.scope
        assert scope.bar_construction is not None
        _require(
            value["operation_id"] == operation.operation_id.value
            and value["intent_fingerprint"] == operation.intent_fingerprint
            and value["source_reference"] == source
            and value["display_range"] == intent["display_range"]
            and value["runtime_work_id"] == operation.reserved_run_id.value
            and value["runtime_generation_fingerprint"] == generation
            and scope.instrument_id == intent["instrument_id"]
            and (scope.start_ns, scope.end_ns) == (start, end)
            and selection["source_id"] == scope.source_id
            and selection["integration_id"] == source["integration_id"]
            and selection["integration_revision_fingerprint"] == source["integration_revision_fingerprint"]
            and selection["type_id"] == source["expected_type_id"]
            and scope.bar_construction.plan.integration_revision_fingerprint
            == source["integration_revision_fingerprint"]
        )

    def materialization_plan(self) -> OnlySealedMarketDataMaterializationPlan:
        scope = self.scope
        # Dataset time ranges select event timestamps [start,end); closed bar support
        # (s,e] therefore requires the exact one-microsecond end extension.
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        definition = OnlyResearchDatasetDefinition(
            (OnlyInstrumentId.parse(scope.instrument_id),),
            OnlyBarSemantic.fixed_duration(15),
            OnlyTimeRange(
                epoch + timedelta(microseconds=scope.start_ns // 1000),
                epoch + timedelta(microseconds=scope.end_ns // 1000 + 1),
            ),
        )
        return OnlySealedMarketDataMaterializationPlan((self.revision_id,), definition, (scope,))


@dataclass(frozen=True, slots=True)
class OnlyChartCalculationRuntimeBindingReferenceV1:
    work_id: str
    runtime_generation_fingerprint: str
    binding_kind: str
    binding_owner: str
    binding_actor: str
    binding_event_fingerprint: str
    binding_sequence: int
    schema_version: int = 1

    def __post_init__(self) -> None:
        OnlyRuntimeWorkBindingEvidence(
            self.work_id,
            self.runtime_generation_fingerprint,
            self.binding_kind,
            self.binding_owner,
            self.binding_actor,
            self.binding_event_fingerprint,
            self.binding_sequence,
            True,
        )
        _require(
            type(self.schema_version) is int
            and self.schema_version == 1
            and self.binding_kind == "NEW_WORK"
            and self.binding_owner == _BINDING_OWNER,
            "CHART_RUNTIME_BINDING_CONFLICT",
        )

    @classmethod
    def from_evidence(cls, evidence: OnlyRuntimeWorkBindingEvidence) -> OnlyChartCalculationRuntimeBindingReferenceV1:
        return cls(
            evidence.work_id,
            evidence.runtime_generation_fingerprint,
            evidence.binding_kind,
            cast(str, evidence.binding_owner),
            evidence.binding_actor,
            evidence.binding_event_fingerprint,
            evidence.binding_sequence,
        )

    def verifies(self, evidence: OnlyRuntimeWorkBindingEvidence, *, require_active: bool) -> None:
        _require(
            self == self.from_evidence(evidence) and (not require_active or evidence.active),
            "CHART_RUNTIME_BINDING_CONFLICT",
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> OnlyChartCalculationRuntimeBindingReferenceV1:
        _require(type(raw) is dict and set(raw) == set(cls.__dataclass_fields__), "CHART_RUNTIME_BINDING_CONFLICT")
        return cls(
            cast(str, raw["work_id"]),
            cast(str, raw["runtime_generation_fingerprint"]),
            cast(str, raw["binding_kind"]),
            cast(str, raw["binding_owner"]),
            cast(str, raw["binding_actor"]),
            cast(str, raw["binding_event_fingerprint"]),
            cast(int, raw["binding_sequence"]),
            cast(int, raw["schema_version"]),
        )


@dataclass(frozen=True, slots=True)
class OnlyChartCalculationPreparationV1:
    operation_id: OnlyProductCommandId
    revision: int
    fence: int
    worker_id: OnlyProductCommandId
    lease_until: datetime
    runtime_generation_fingerprint: str
    runtime_work_id: str
    state: str = "MATERIALIZING_INPUT"
    input_pin: OnlyChartCalculationInputPinV1 | None = None
    dataset_snapshot_fingerprint: str | None = None
    dataset_materialization_id: str | None = None
    failure_code: str | None = None
    runtime_binding_reference: OnlyChartCalculationRuntimeBindingReferenceV1 | None = None
    runtime_closure_reference: OnlyRuntimeWorkAdmissionClosureEvidence | None = None
    failure_decision: str | None = None
    fact_schema_version: int = 2

    @property
    def input_selection_fingerprint(self) -> str | None:
        return None if self.input_pin is None else self.input_pin.fingerprint

    def __post_init__(self) -> None:
        _require(type(self.fact_schema_version) is int and self.fact_schema_version in {1, 2})
        _require(type(self.revision) is int and type(self.fence) is int and 1 <= self.fence <= self.revision)
        _require(self.lease_until.tzinfo is not None and self.lease_until.utcoffset() == timedelta(0))
        _require(self.state in {"MATERIALIZING_INPUT", "INPUT_READY", "FAILED"})
        _require((self.state == "FAILED") == (self.failure_code is not None))
        _require(
            (self.state == "INPUT_READY")
            == (self.dataset_snapshot_fingerprint is not None and self.dataset_materialization_id is not None)
        )
        if self.state != "INPUT_READY":
            _require(self.dataset_snapshot_fingerprint is None and self.dataset_materialization_id is None)
        if self.state == "INPUT_READY":
            _require(self.input_pin is not None)
        if self.fact_schema_version == 1:
            _require(
                self.runtime_binding_reference is None
                and self.runtime_closure_reference is None
                and self.failure_decision is None
            )
            return
        if self.runtime_binding_reference is not None:
            _require(
                self.runtime_binding_reference.work_id == self.runtime_work_id
                and self.runtime_binding_reference.runtime_generation_fingerprint == self.runtime_generation_fingerprint
            )
        if self.input_pin is not None or self.state == "INPUT_READY":
            _require(self.runtime_binding_reference is not None)
        if self.failure_decision is not None:
            _require(
                self.failure_decision in _PRE_BIND_FAILURES | _POST_BIND_FAILURES,
                "CHART_PREPARATION_FAILURE_CODE_INVALID",
            )
            if self.failure_decision in _POST_BIND_FAILURES:
                _require(self.runtime_binding_reference is not None)
        if self.state == "INPUT_READY":
            _require(self.failure_decision is None)
        if self.state == "FAILED":
            closure = self.runtime_closure_reference
            _require(closure is not None and self.failure_code == self.failure_decision)
            assert closure is not None
            _require(
                closure.work_id == self.runtime_work_id
                and closure.runtime_generation_fingerprint == self.runtime_generation_fingerprint
                and closure.binding_owner == _BINDING_OWNER
                and closure.closure_reason == self.failure_code
            )
        else:
            _require(self.runtime_closure_reference is None)


class OnlyChartCalculationPreparationStore(Protocol):
    def load_verified(self, operation: OnlyChartCalculationOperationV1) -> OnlyChartCalculationPreparationV1 | None: ...
    def claim(
        self,
        operation: OnlyChartCalculationOperationV1,
        worker_id: OnlyProductCommandId,
        generation: str,
        *,
        lease_duration: timedelta,
    ) -> OnlyChartCalculationPreparationV1: ...
    def heartbeat(
        self,
        operation: OnlyChartCalculationOperationV1,
        claim: OnlyChartCalculationPreparationV1,
        *,
        lease_duration: timedelta,
    ) -> OnlyChartCalculationPreparationV1: ...
    def commit_pin(
        self,
        operation: OnlyChartCalculationOperationV1,
        claim: OnlyChartCalculationPreparationV1,
        pin: OnlyChartCalculationInputPinV1,
    ) -> OnlyChartCalculationPreparationV1: ...
    def input_ready(
        self,
        operation: OnlyChartCalculationOperationV1,
        claim: OnlyChartCalculationPreparationV1,
        *,
        snapshot_fingerprint: str,
        materialization_id: str,
    ) -> OnlyChartCalculationPreparationV1: ...
    def fail(
        self,
        operation: OnlyChartCalculationOperationV1,
        claim: OnlyChartCalculationPreparationV1,
        code: str,
        *,
        closure_reference: OnlyRuntimeWorkAdmissionClosureEvidence,
    ) -> OnlyChartCalculationPreparationV1: ...

    def commit_runtime_binding(
        self,
        operation: OnlyChartCalculationOperationV1,
        claim: OnlyChartCalculationPreparationV1,
        reference: OnlyChartCalculationRuntimeBindingReferenceV1,
    ) -> OnlyChartCalculationPreparationV1: ...

    def begin_failure(
        self, operation: OnlyChartCalculationOperationV1, claim: OnlyChartCalculationPreparationV1, code: str
    ) -> OnlyChartCalculationPreparationV1: ...


class OnlyChartCalculationPreparationService:
    def __init__(
        self,
        *,
        store: OnlyChartCalculationPreparationStore,
        runtime_generations: OnlyRuntimeGenerationWorkAuthority,
        market_data: OnlyMarketDataProductService,
        catalog: OnlyMarketDataCatalog,
        facts: OnlyMarketFactStore,
        materializer: OnlySealedMarketDataDatasetMaterializer,
    ) -> None:
        self._store = store
        self._runtime = runtime_generations
        self._market = market_data
        self._catalog = catalog
        self._query = OnlyHistoricalMarketDataQueryService(catalog, facts)
        self._materializer = materializer

    def _require_generation(
        self, operation: OnlyChartCalculationOperationV1, generation: str, *, new_work: bool = False
    ) -> None:
        try:
            manifest = (
                self._runtime.require_new_work_generation(generation)
                if new_work
                else self._runtime.require_runtime_generation(generation)
            )
        except Exception as exc:
            code = (
                "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE"
                if isinstance(exc, ValueError) and str(exc) == "RUNTIME_GENERATION_NOT_ELIGIBLE_FOR_NEW_WORK"
                else "CHART_EXECUTION_GENERATION_UNAVAILABLE"
            )
            raise OnlyChartCalculationError(code) from exc
        context = cast(dict[str, object], operation.catalog_witness.to_dict()["context"])
        _require(
            getattr(manifest, "runtime_generation_fingerprint", None) == generation
            and getattr(manifest, "catalog_generation_fingerprint", None) == context["catalog_generation_fingerprint"],
            "CHART_EXECUTION_GENERATION_UNAVAILABLE",
        )

    def _load_binding(self, operation: OnlyChartCalculationOperationV1) -> object | None:
        try:
            binding = self._runtime.require_work_binding_evidence(operation.reserved_run_id.value)
        except ValueError as exc:
            if str(exc) == "RUNTIME_WORK_GENERATION_UNBOUND":
                return None
            raise OnlyChartCalculationError("CHART_EXECUTION_GENERATION_UNAVAILABLE") from exc
        except Exception as exc:
            raise OnlyChartCalculationError("CHART_EXECUTION_GENERATION_UNAVAILABLE") from exc
        _require(binding is not None, "CHART_RUNTIME_BINDING_CONFLICT")
        return binding

    @staticmethod
    def _verify_binding(operation: OnlyChartCalculationOperationV1, generation: str, binding: object) -> None:
        _require(isinstance(binding, OnlyRuntimeWorkBindingEvidence), "CHART_RUNTIME_BINDING_CONFLICT")
        assert isinstance(binding, OnlyRuntimeWorkBindingEvidence)
        _require(
            getattr(binding, "work_id", None) == operation.reserved_run_id.value
            and getattr(binding, "runtime_generation_fingerprint", None) == generation
            and type(getattr(binding, "active", None)) is bool,
            "CHART_RUNTIME_BINDING_CONFLICT",
        )
        _require(
            binding.binding_kind == "NEW_WORK" and binding.binding_owner == _BINDING_OWNER,
            "CHART_RUNTIME_BINDING_CONFLICT",
        )

    def _bind(self, operation: OnlyChartCalculationOperationV1, generation: str, occurred_at: datetime) -> None:
        binding = self._load_binding(operation)
        if binding is not None:
            self._verify_binding(operation, generation, binding)
            _require(getattr(binding, "active", None) is True, "CHART_RUNTIME_BINDING_INACTIVE")
            self._require_generation(operation, generation)
            return
        # Recheck the exact frozen generation at the first bind boundary. Never
        # substitute the newly active generation after an activation change.
        self._require_generation(operation, generation, new_work=True)
        work = operation.reserved_run_id.value
        try:
            binding = self._runtime.bind_new_work_exact(
                work, generation, owner=_BINDING_OWNER, actor="chart-input-preparation", occurred_at=occurred_at
            )
        except ValueError as exc:
            if str(exc) == "RUNTIME_GENERATION_NOT_ELIGIBLE_FOR_NEW_WORK":
                raise OnlyChartCalculationError("CHART_RUNTIME_GENERATION_NOT_ELIGIBLE") from exc
            if str(exc) in {"RUNTIME_WORK_GENERATION_BINDING_CONFLICT", "RUNTIME_WORK_ADMISSION_CLOSED"}:
                raise OnlyChartCalculationError("CHART_RUNTIME_BINDING_CONFLICT") from exc
            raise OnlyChartCalculationError("CHART_EXECUTION_GENERATION_UNAVAILABLE") from exc
        except Exception as exc:
            raise OnlyChartCalculationError("CHART_EXECUTION_GENERATION_UNAVAILABLE") from exc
        binding = self._load_binding(operation)
        self._verify_binding(operation, generation, binding)
        _require(getattr(binding, "active", None) is True, "CHART_RUNTIME_BINDING_INACTIVE")
        # Prove assignment and eligibility again; a released binding is never reactivated.
        self._runtime.require_work_generation(work, generation)

    def _reconcile_terminal_runtime_binding(
        self,
        operation: OnlyChartCalculationOperationV1,
        preparation: OnlyChartCalculationPreparationV1,
        *,
        occurred_at: datetime,
    ) -> None:
        del occurred_at
        _require(
            preparation.state == "FAILED" and preparation.runtime_closure_reference is not None,
            "CHART_RUNTIME_BINDING_CONFLICT",
        )
        closure = self._load_closure(operation)
        _require(closure == preparation.runtime_closure_reference, "CHART_RUNTIME_BINDING_CONFLICT")
        self._verify_closure(operation, preparation, closure)
        binding = self._load_binding(operation)
        if preparation.runtime_binding_reference is not None:
            self._verify_binding(operation, preparation.runtime_generation_fingerprint, binding)
            assert isinstance(binding, OnlyRuntimeWorkBindingEvidence)
            preparation.runtime_binding_reference.verifies(binding, require_active=False)
        elif binding is not None:
            self._verify_binding(operation, preparation.runtime_generation_fingerprint, binding)
        _require(binding is None or getattr(binding, "active", None) is False, "CHART_RUNTIME_BINDING_CONFLICT")

    def _load_closure(
        self, operation: OnlyChartCalculationOperationV1
    ) -> OnlyRuntimeWorkAdmissionClosureEvidence | None:
        try:
            evidence = self._runtime.require_work_admission_closure_evidence(operation.reserved_run_id.value)
        except ValueError as exc:
            if str(exc) == "RUNTIME_WORK_ADMISSION_NOT_CLOSED":
                return None
            raise OnlyChartCalculationError("CHART_RUNTIME_BINDING_RELEASE_UNAVAILABLE") from exc
        except Exception as exc:
            raise OnlyChartCalculationError("CHART_RUNTIME_BINDING_RELEASE_UNAVAILABLE") from exc
        _require(isinstance(evidence, OnlyRuntimeWorkAdmissionClosureEvidence), "CHART_RUNTIME_BINDING_CONFLICT")
        return evidence

    @staticmethod
    def _verify_closure(
        operation: OnlyChartCalculationOperationV1,
        preparation: OnlyChartCalculationPreparationV1,
        closure: OnlyRuntimeWorkAdmissionClosureEvidence | None,
    ) -> None:
        _require(isinstance(closure, OnlyRuntimeWorkAdmissionClosureEvidence), "CHART_RUNTIME_BINDING_CONFLICT")
        assert isinstance(closure, OnlyRuntimeWorkAdmissionClosureEvidence)
        _require(
            closure.work_id == operation.reserved_run_id.value
            and closure.runtime_generation_fingerprint == preparation.runtime_generation_fingerprint
            and closure.binding_owner == _BINDING_OWNER
            and closure.closure_reason == preparation.failure_decision,
            "CHART_RUNTIME_BINDING_CONFLICT",
        )

    def _complete_failure(
        self,
        operation: OnlyChartCalculationOperationV1,
        claim: OnlyChartCalculationPreparationV1,
        occurred_at: datetime,
    ) -> OnlyChartCalculationPreparationV1:
        code = claim.failure_decision
        _require(code in _PRE_BIND_FAILURES | _POST_BIND_FAILURES, "CHART_RUNTIME_BINDING_CONFLICT")
        assert code is not None
        binding = self._load_binding(operation)
        if binding is not None:
            self._verify_binding(operation, claim.runtime_generation_fingerprint, binding)
        if claim.runtime_binding_reference is not None:
            _require(isinstance(binding, OnlyRuntimeWorkBindingEvidence), "CHART_RUNTIME_BINDING_CONFLICT")
            assert isinstance(binding, OnlyRuntimeWorkBindingEvidence)
            claim.runtime_binding_reference.verifies(binding, require_active=False)
        if code in _POST_BIND_FAILURES:
            _require(claim.runtime_binding_reference is not None, "CHART_RUNTIME_BINDING_CONFLICT")
        closure = self._load_closure(operation)
        if closure is None:
            try:
                closure = self._runtime.close_new_work_exact(
                    operation.reserved_run_id.value,
                    claim.runtime_generation_fingerprint,
                    owner=_BINDING_OWNER,
                    closure_reason=code,
                    actor="chart-input-preparation-failed",
                    occurred_at=occurred_at,
                )
            except ValueError as exc:
                if str(exc) == "RUNTIME_WORK_GENERATION_BINDING_CONFLICT":
                    raise OnlyChartCalculationError("CHART_RUNTIME_BINDING_CONFLICT") from exc
                raise OnlyChartCalculationError("CHART_RUNTIME_BINDING_RELEASE_UNAVAILABLE") from exc
            except Exception as exc:
                raise OnlyChartCalculationError("CHART_RUNTIME_BINDING_RELEASE_UNAVAILABLE") from exc
        self._verify_closure(operation, claim, closure)
        failed = self._store.fail(operation, claim, code, closure_reference=closure)
        self._reconcile_terminal_runtime_binding(operation, failed, occurred_at=occurred_at)
        return failed

    def _fail(
        self,
        operation: OnlyChartCalculationOperationV1,
        claim: OnlyChartCalculationPreparationV1,
        code: str,
        occurred_at: datetime,
    ) -> OnlyChartCalculationPreparationV1:
        decided = self._store.begin_failure(operation, claim, code)
        return self._complete_failure(operation, decided, occurred_at)

    def _evidence(self, revision_id: str, scope: OnlyMarketDataScope) -> dict[str, object]:
        revision, seal = self._query.resolve_with_seal(revision_id)
        _require(revision.scope == scope)
        self._query.read_exact(revision_id, scope)
        manifest = self._catalog.load_coverage_manifest(revision.manifest_id)
        proofs = self._catalog.load_physical_proofs(tuple(item[0] for item in revision.segment_refs))
        return cast(
            dict[str, object],
            only_canonical_payload(
                {"revision": revision, "manifest": manifest, "seal": seal, "physical_proofs": proofs}
            ),
        )

    def prepare(
        self,
        operation: OnlyChartCalculationOperationV1,
        *,
        worker_id: OnlyProductCommandId,
        runtime_generation_fingerprint: str,
        occurred_at: datetime,
        lease_duration: timedelta = timedelta(minutes=2),
    ) -> OnlyChartCalculationPreparationV1:
        preparation = self._store.load_verified(operation)
        if preparation is None:
            _require(self._load_closure(operation) is None, "CHART_RUNTIME_BINDING_CONFLICT")
        if preparation is not None:
            _require(
                preparation.operation_id == operation.operation_id
                and preparation.runtime_work_id == operation.reserved_run_id.value
                and preparation.runtime_generation_fingerprint == runtime_generation_fingerprint,
                "CHART_RUNTIME_BINDING_CONFLICT",
            )
            if preparation.input_pin is not None:
                preparation.input_pin.verify_operation(operation, runtime_generation_fingerprint)
            if preparation.state == "FAILED":
                self._reconcile_terminal_runtime_binding(operation, preparation, occurred_at=occurred_at)
                return preparation
            _require(
                preparation.fact_schema_version != 1 or preparation.input_pin is None, "CHART_RUNTIME_BINDING_CONFLICT"
            )
            if preparation.failure_decision is not None:
                claim = self._store.claim(
                    operation, worker_id, runtime_generation_fingerprint, lease_duration=lease_duration
                )
                return self._complete_failure(operation, claim, occurred_at)
            closure = self._load_closure(operation)
            if closure is not None:
                claim = self._store.claim(
                    operation, worker_id, runtime_generation_fingerprint, lease_duration=lease_duration
                )
                _require(
                    closure.closure_reason in _PRE_BIND_FAILURES | _POST_BIND_FAILURES, "CHART_RUNTIME_BINDING_CONFLICT"
                )
                self._verify_closure(operation, replace(claim, failure_decision=closure.closure_reason), closure)
                return self._fail(operation, claim, closure.closure_reason, occurred_at)
        binding = self._load_binding(operation)
        _require(preparation is not None or binding is None, "CHART_RUNTIME_BINDING_CONFLICT")
        eligibility_lost = False
        if binding is not None:
            self._verify_binding(operation, runtime_generation_fingerprint, binding)
            if preparation is not None and preparation.runtime_binding_reference is not None:
                assert isinstance(binding, OnlyRuntimeWorkBindingEvidence)
                preparation.runtime_binding_reference.verifies(binding, require_active=False)
            _require(getattr(binding, "active", None) is True, "CHART_RUNTIME_BINDING_INACTIVE")
            self._require_generation(operation, runtime_generation_fingerprint)
        else:
            _require(
                preparation is None or (preparation.state != "INPUT_READY" and preparation.input_pin is None),
                "CHART_RUNTIME_BINDING_CONFLICT",
            )
            try:
                self._require_generation(operation, runtime_generation_fingerprint, new_work=True)
            except OnlyChartCalculationError as exc:
                if preparation is None or str(exc) != "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE":
                    raise
                eligibility_lost = True
        claim = self._store.claim(operation, worker_id, runtime_generation_fingerprint, lease_duration=lease_duration)
        if claim.state == "FAILED":
            self._reconcile_terminal_runtime_binding(operation, claim, occurred_at=occurred_at)
            return claim
        if claim.failure_decision is not None:
            return self._complete_failure(operation, claim, occurred_at)
        if eligibility_lost:
            return self._fail(operation, claim, "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE", occurred_at)
        try:
            self._bind(operation, claim.runtime_generation_fingerprint, occurred_at)
        except OnlyChartCalculationError as exc:
            if str(exc) != "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE":
                raise
            return self._fail(operation, claim, "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE", occurred_at)
        binding = self._load_binding(operation)
        self._verify_binding(operation, claim.runtime_generation_fingerprint, binding)
        assert isinstance(binding, OnlyRuntimeWorkBindingEvidence)
        reference = OnlyChartCalculationRuntimeBindingReferenceV1.from_evidence(binding)
        if claim.runtime_binding_reference is not None:
            claim.runtime_binding_reference.verifies(binding, require_active=True)
        else:
            _require(claim.input_pin is None and claim.state == "MATERIALIZING_INPUT", "CHART_RUNTIME_BINDING_CONFLICT")
        if claim.state != "INPUT_READY":
            try:
                if claim.runtime_binding_reference is None:
                    claim = self._store.commit_runtime_binding(operation, claim, reference)
                claim = self._store.heartbeat(operation, claim, lease_duration=lease_duration)
                if claim.failure_decision is not None:
                    return self._complete_failure(operation, claim, occurred_at)
            except ValueError as exc:
                if str(exc) != "CHART_PREPARATION_FENCE_LOST":
                    raise
                current = self._store.load_verified(operation)
                _require(current is not None, "CHART_RUNTIME_BINDING_CONFLICT")
                assert current is not None
                _require(
                    current.operation_id == operation.operation_id
                    and current.runtime_work_id == operation.reserved_run_id.value
                    and current.runtime_generation_fingerprint == runtime_generation_fingerprint,
                    "CHART_RUNTIME_BINDING_CONFLICT",
                )
                if current.state == "FAILED":
                    self._reconcile_terminal_runtime_binding(operation, current, occurred_at=occurred_at)
                    return current
                if current.state == "INPUT_READY":
                    binding = self._load_binding(operation)
                    self._verify_binding(operation, runtime_generation_fingerprint, binding)
                    _require(current.runtime_binding_reference is not None, "CHART_RUNTIME_BINDING_CONFLICT")
                    assert current.runtime_binding_reference is not None and isinstance(
                        binding, OnlyRuntimeWorkBindingEvidence
                    )
                    current.runtime_binding_reference.verifies(binding, require_active=True)
                    _require(getattr(binding, "active", None) is True, "CHART_RUNTIME_BINDING_INACTIVE")
                    assert current.input_pin is not None
                    current.input_pin.verify_operation(operation, runtime_generation_fingerprint)
                    return current
                raise
        if claim.input_pin is None:
            intent = operation.intent.to_dict()
            start, end = only_chart_materialization_support(operation.intent)
            source = cast(dict[str, str], intent["source_reference"])
            selected: OnlyMarketDataSelectionPlanV1 = self._market.plan_selection(
                OnlyMarketDataSourceReferenceV1(**source),
                instrument_id=cast(str, intent["instrument_id"]),
                start_ns=start,
                end_ns=end,
                bar_semantic=OnlyBarSemantic.fixed_duration(15),
            )
            try:
                revision = self._query.resolve_latest(selected.scope)
            except KeyError:
                return self._fail(operation, claim, "CHART_SEALED_COVERAGE_UNAVAILABLE", occurred_at)
            pin = OnlyChartCalculationInputPinV1(
                only_canonical_json(
                    {
                        "schema_version": 1,
                        "operation_id": operation.operation_id.value,
                        "intent_fingerprint": operation.intent_fingerprint,
                        "source_reference": source,
                        "source_selection": selected.source_selection,
                        "integration_binding_fingerprint": selected.integration_binding_fingerprint,
                        "display_range": intent["display_range"],
                        "scope": {
                            **cast(dict[str, object], only_canonical_payload(selected.scope)),
                            "bar_construction": selected.scope.bar_construction.to_dict()
                            if selected.scope.bar_construction
                            else None,
                        },
                        "evidence": self._evidence(revision.revision_id, selected.scope),
                        "runtime_generation_fingerprint": claim.runtime_generation_fingerprint,
                        "runtime_work_id": operation.reserved_run_id.value,
                    }
                )
            )
            pin.verify_operation(operation, claim.runtime_generation_fingerprint)
            claim = self._store.commit_pin(operation, claim, pin)
        committed_pin = claim.input_pin
        assert committed_pin is not None
        pin = committed_pin
        pin.verify_operation(operation, claim.runtime_generation_fingerprint)
        _require(pin.to_dict()["evidence"] == self._evidence(pin.revision_id, pin.scope))
        result = self._materializer.materialize_with_lineage(pin.materialization_plan())
        _require(result.snapshot.definition == pin.materialization_plan().definition)
        expected_revision = cast(dict[str, dict[str, object]], pin.to_dict()["evidence"])["revision"]
        bindings = result.materialization.market_data_revision_bindings
        _require(
            len(bindings) == 1
            and bindings[0].revision_id == pin.revision_id
            and bindings[0].revision_fingerprint == expected_revision["fingerprint"]
            and result.materialization.dataset_snapshot_fingerprint == result.snapshot.snapshot_fingerprint
        )
        if claim.state == "INPUT_READY":
            _require(
                claim.dataset_snapshot_fingerprint == result.snapshot.snapshot_fingerprint
                and claim.dataset_materialization_id == result.materialization.materialization_id
            )
            return claim
        self._runtime.require_work_generation(operation.reserved_run_id.value, claim.runtime_generation_fingerprint)
        return self._store.input_ready(
            operation,
            claim,
            snapshot_fingerprint=result.snapshot.snapshot_fingerprint,
            materialization_id=result.materialization.materialization_id,
        )
