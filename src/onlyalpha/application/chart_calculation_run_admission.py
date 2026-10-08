"""Typed, frozen Chart compilation -> Research queue; never Calculation execution."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, cast

from onlyalpha.application.chart_calculation import OnlyChartCalculationError, OnlyChartCalculationOperationV1
from onlyalpha.application.chart_calculation_compilation import (
    OnlyChartCalculationCompilationV1,
    OnlyChartCalculationInputVerifier,
    _verified_ready_pin,
)
from onlyalpha.application.chart_calculation_compilation_ports import (
    OnlyChartCalculationCompilationStore,
    OnlyChartCalculationPreparationReader,
)
from onlyalpha.application.runtime_generation import OnlyRuntimeGenerationWorkAuthority
from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.dataset.lineage import OnlyDatasetMaterializationStore
from onlyalpha.research.dataset.ports import OnlyResearchDatasetSnapshotStore
from onlyalpha.research.run.model import OnlyResearchOriginKind, OnlyResearchRun, OnlyResearchRunState


def only_chart_calculation_queued_run(
    compilation: OnlyChartCalculationCompilationV1, *, queued_at: datetime
) -> OnlyResearchRun:
    """The frozen compilation itself is the Chart admission resolution evidence."""
    from onlyalpha.research.run.model import OnlyResearchRunId

    compilation.__post_init__()
    return OnlyResearchRun(
        OnlyResearchRunId(compilation.runtime_work_id),
        0,
        OnlyResearchRunState.QUEUED,
        compilation.specification,
        compilation.specification_fingerprint,
        only_canonical_json(compilation.specification.to_dict()),
        compilation.compilation_fingerprint,
        queued_at,
        origin_kind=OnlyResearchOriginKind.CHART_CALCULATION,
    )


def only_require_chart_calculation_new_admission(
    runtime: OnlyRuntimeGenerationWorkAuthority,
    operation: OnlyChartCalculationOperationV1,
    compilation: OnlyChartCalculationCompilationV1,
) -> None:
    """No binding acquisition, rebinding, release or numerical host resolution."""
    binding = runtime.require_work_binding_evidence(operation.reserved_run_id.value)
    compilation.runtime_binding_reference.verifies(binding, require_active=True)
    try:
        # T2 already admitted this exact root work. Activation switching does not
        # revoke bound-work availability (READY/ACTIVE/DRAINING); RETIRED is rejected.
        manifest = runtime.require_runtime_generation(compilation.runtime_generation_fingerprint)
    except ValueError as exc:
        raise OnlyChartCalculationError("CHART_RUNTIME_GENERATION_NOT_ELIGIBLE") from exc
    context = cast(dict[str, object], operation.catalog_witness.to_dict()["context"])
    if (
        getattr(manifest, "runtime_generation_fingerprint", None) != compilation.runtime_generation_fingerprint
        or getattr(manifest, "catalog_generation_fingerprint", None) != context["catalog_generation_fingerprint"]
    ):
        raise OnlyChartCalculationError("CHART_EXECUTION_GENERATION_UNAVAILABLE")


def only_verify_chart_calculation_run(run: OnlyResearchRun, frozen: OnlyChartCalculationCompilationV1) -> None:
    if type(run) is not OnlyResearchRun:
        raise OnlyChartCalculationError("CHART_RUN_ADMISSION_RELATION_CORRUPT")
    run.__post_init__()
    expected = only_chart_calculation_queued_run(frozen, queued_at=run.queued_at)
    if run.state is OnlyResearchRunState.CANCELLED:
        assert run.finished_at is not None
        expected = expected.transition(run.state, at=run.finished_at)
    if run != expected:
        raise OnlyChartCalculationError("CHART_RUN_ADMISSION_RELATION_CORRUPT")


class OnlyChartCalculationRunAdmissionStore(Protocol):
    def load_verified(self, operation: OnlyChartCalculationOperationV1) -> OnlyResearchRun | None: ...

    def commit_or_replay(
        self,
        operation: OnlyChartCalculationOperationV1,
        compilation: OnlyChartCalculationCompilationV1,
        *,
        queued_at: datetime,
    ) -> OnlyResearchRun: ...


class OnlyChartCalculationRunAdmissionService:
    def __init__(
        self,
        *,
        preparations: OnlyChartCalculationPreparationReader,
        compilations: OnlyChartCalculationCompilationStore,
        datasets: OnlyResearchDatasetSnapshotStore,
        materializations: OnlyDatasetMaterializationStore,
        runtime_generations: OnlyRuntimeGenerationWorkAuthority,
        runs: OnlyChartCalculationRunAdmissionStore,
    ) -> None:
        self._preparations = preparations
        self._compilations = compilations
        self._runtime = runtime_generations
        self._runs = runs
        self._inputs = OnlyChartCalculationInputVerifier(
            datasets=datasets, materializations=materializations, runtime_generations=runtime_generations
        )

    def admit(self, operation: OnlyChartCalculationOperationV1, *, queued_at: datetime) -> OnlyResearchRun:
        preparation = self._preparations.load_verified(operation)
        _verified_ready_pin(operation, preparation)
        assert preparation is not None
        frozen = self._compilations.load_verified(operation)
        if type(frozen) is not OnlyChartCalculationCompilationV1:
            raise OnlyChartCalculationError("CHART_COMPILATION_NOT_READY")
        self._inputs.verify_frozen(operation, preparation, frozen)
        existing = self._runs.load_verified(operation)
        if existing is not None:
            only_verify_chart_calculation_run(existing, frozen)
            return existing
        only_require_chart_calculation_new_admission(self._runtime, operation, frozen)
        committed = self._runs.commit_or_replay(operation, frozen, queued_at=queued_at)
        only_verify_chart_calculation_run(committed, frozen)
        return committed
