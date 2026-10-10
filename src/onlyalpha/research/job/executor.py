"""Deterministic verified reuse-or-execute Research Job orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.research.calculation.errors import (
    OnlyResearchCalculationError,
    OnlyResearchCalculationResultStoreError,
)
from onlyalpha.research.calculation.execution import (
    OnlyResearchCalculationImplementationBinding,
    _only_require_verified_research_calculation_execution_v2,
    _OnlyVerifiedResearchCalculationExecution,
    _OnlyVerifiedResearchCalculationExecutionV2,
)
from onlyalpha.research.calculation.execution_evidence import (
    OnlyResearchCalculationExecutionEvidence,
    OnlyResearchCalculationExecutionEvidenceStore,
)
from onlyalpha.research.calculation.execution_provenance import (
    _only_require_research_runtime_execution_context,
    _OnlyResearchRuntimeExecutionContext,
)
from onlyalpha.research.calculation.publication import OnlyResearchCalculationPublicationContract
from onlyalpha.research.calculation.result import OnlyResearchCalculationResult, OnlyResearchCalculationResultManifest
from onlyalpha.research.calculation.result_ports import OnlyResearchCalculationResultStore

from .errors import OnlyResearchJobError, OnlyResearchJobPhase
from .outcome import OnlyResearchJobDisposition, OnlyResearchJobOutcome, OnlyResearchJobStatus
from .plan import RESEARCH_JOB_PLAN_READINESS_SCHEMA_VERSION, RESEARCH_JOB_PLAN_SCHEMA_VERSION, OnlyResearchJobPlan

if TYPE_CHECKING:
    from onlyalpha.research.calculation.execution import (
        OnlyResearchCalculationNodeOutput,
        OnlyResearchCalculationNodeReadiness,
    )
    from onlyalpha.research.calculation.execution_evidence_v2 import (
        OnlyResearchCalculationExecutionEvidenceStoreV2,
        OnlyResearchCalculationExecutionEvidenceV2,
    )
    from onlyalpha.research.calculation.result_v2 import OnlyResearchCalculationResultV2
    from onlyalpha.research.calculation.result_v2_ports import OnlyResearchCalculationResultStoreV2


class _OnlyResearchCalculationExecutor(Protocol):
    def _execute_verified(
        self,
        snapshot_fingerprint: str,
        graph: OnlyCalculationGraphDefinition,
    ) -> _OnlyVerifiedResearchCalculationExecution: ...

    def _execute_verified_v2(
        self,
        snapshot_fingerprint: str,
        graph: OnlyCalculationGraphDefinition,
        publication: OnlyResearchCalculationPublicationContract,
        *,
        runtime_context: _OnlyResearchRuntimeExecutionContext | None = None,
    ) -> _OnlyVerifiedResearchCalculationExecutionV2: ...


def _only_execute_generation_bound_calculation_job(
    plan: OnlyResearchJobPlan,
    calculation_executor: _OnlyResearchCalculationExecutor,
    legacy_results: OnlyResearchCalculationResultStore,
    legacy_evidence: OnlyResearchCalculationExecutionEvidenceStore,
    results: OnlyResearchCalculationResultStoreV2,
    evidence: OnlyResearchCalculationExecutionEvidenceStoreV2,
    context: _OnlyResearchRuntimeExecutionContext,
    *,
    required_result_fingerprint: str | None = None,
    required_evidence_fingerprint: str | None = None,
) -> OnlyResearchJobOutcome:
    """Owning Job composition; Infrastructure supplies a verified native context, not Job Authority."""
    if plan.schema_version != RESEARCH_JOB_PLAN_READINESS_SCHEMA_VERSION:
        raise OnlyResearchJobError(OnlyResearchJobPhase.PLAN_VALIDATION, "RESEARCH_JOB_INVALID", "Plan V2 required")
    context = _only_require_research_runtime_execution_context(context, plan.calculation_graph.fingerprint)
    plan.__post_init__()
    executor = OnlyResearchJobExecutor(
        calculation_executor,
        legacy_results,
        legacy_evidence,
        readiness_result_store=results,
        readiness_execution_evidence_store=evidence,
        runtime_execution_context=context,
    )
    return executor._execute_v2(
        plan,
        required_result_fingerprint=required_result_fingerprint,
        required_evidence_fingerprint=required_evidence_fingerprint,
    )


class OnlyResearchJobExecutor:
    """Execute one exact Job without owning Dataset, Calculation, or Result state."""

    def __init__(
        self,
        calculation_executor: _OnlyResearchCalculationExecutor,
        result_store: OnlyResearchCalculationResultStore,
        execution_evidence_store: OnlyResearchCalculationExecutionEvidenceStore,
        authoring_generation_fingerprint: str | None = None,
        *,
        readiness_result_store: OnlyResearchCalculationResultStoreV2 | None = None,
        readiness_execution_evidence_store: OnlyResearchCalculationExecutionEvidenceStoreV2 | None = None,
        runtime_execution_context: _OnlyResearchRuntimeExecutionContext | None = None,
    ) -> None:
        self._calculation_executor = calculation_executor
        self._result_store = result_store
        self._execution_evidence_store = execution_evidence_store
        self._authoring_generation_fingerprint = authoring_generation_fingerprint
        self._readiness_result_store = readiness_result_store
        self._readiness_execution_evidence_store = readiness_execution_evidence_store
        self._runtime_execution_context = runtime_execution_context

    def execute(self, plan: OnlyResearchJobPlan) -> OnlyResearchJobOutcome:
        if type(plan) is not OnlyResearchJobPlan:
            raise OnlyResearchJobError(
                OnlyResearchJobPhase.PLAN_VALIDATION,
                "RESEARCH_JOB_INVALID",
                "execute requires an OnlyResearchJobPlan",
            )
        # Frozen dataclasses are a contract, not proof against external mutation.
        plan.__post_init__()
        if plan.schema_version == RESEARCH_JOB_PLAN_SCHEMA_VERSION:
            return self._execute_v1(plan)
        if plan.schema_version == RESEARCH_JOB_PLAN_READINESS_SCHEMA_VERSION:
            return self._execute_v2(plan)
        raise OnlyResearchJobError(OnlyResearchJobPhase.PLAN_VALIDATION, "RESEARCH_JOB_INVALID", "unsupported schema")

    def _execute_v1(self, plan: OnlyResearchJobPlan) -> OnlyResearchJobOutcome:
        calculation_fingerprint = plan.calculation_fingerprint
        try:
            existing = self._result_store.load_verified(calculation_fingerprint)
        except OnlyResearchCalculationResultStoreError as exc:
            if exc.code != "RESULT_NOT_FOUND":
                raise _job_error(OnlyResearchJobPhase.RESULT_REUSE, exc) from exc
        except Exception as exc:
            raise OnlyResearchJobError(
                OnlyResearchJobPhase.RESULT_REUSE,
                "RESEARCH_JOB_RESULT_REUSE_FAILED",
                str(exc),
            ) from exc
        else:
            try:
                evidence = self._execution_evidence_store.require_for_result(
                    existing,
                    self._authoring_generation_fingerprint,
                )
            except OnlyResearchCalculationError as exc:
                raise _job_error(OnlyResearchJobPhase.RESULT_REUSE, exc) from exc
            return _outcome(
                plan,
                existing,
                evidence,
                OnlyResearchJobDisposition.REUSED,
                OnlyResearchJobPhase.RESULT_REUSE,
            )

        try:
            verified_execution = self._calculation_executor._execute_verified(
                plan.dataset_snapshot_fingerprint,
                plan.calculation_graph,
            )
        except OnlyResearchCalculationError as exc:
            phase = (
                OnlyResearchJobPhase.DATASET_VERIFICATION
                if exc.code == "RESEARCH_DATASET_VERIFICATION_FAILED"
                else OnlyResearchJobPhase.CALCULATION_EXECUTION
            )
            raise _job_error(phase, exc) from exc
        except Exception as exc:
            raise OnlyResearchJobError(
                OnlyResearchJobPhase.CALCULATION_EXECUTION,
                "RESEARCH_JOB_EXECUTION_FAILED",
                str(exc),
            ) from exc

        try:
            committed = self._result_store.commit(verified_execution.execution, plan.calculation_graph)
        except OnlyResearchCalculationResultStoreError as exc:
            raise _job_error(OnlyResearchJobPhase.RESULT_COMMIT, exc) from exc
        except Exception as exc:
            raise OnlyResearchJobError(
                OnlyResearchJobPhase.RESULT_COMMIT,
                "RESEARCH_JOB_RESULT_COMMIT_FAILED",
                str(exc),
            ) from exc
        try:
            evidence = self._execution_evidence_store._publish_verified(
                verified_execution,
                committed,
                self._authoring_generation_fingerprint,
            )
        except OnlyResearchCalculationError as exc:
            raise _job_error(OnlyResearchJobPhase.RESULT_COMMIT, exc) from exc
        return _outcome(
            plan,
            committed,
            evidence,
            OnlyResearchJobDisposition.EXECUTED,
            OnlyResearchJobPhase.RESULT_COMMIT,
        )

    def _execute_v2(
        self,
        plan: OnlyResearchJobPlan,
        *,
        required_result_fingerprint: str | None = None,
        required_evidence_fingerprint: str | None = None,
    ) -> OnlyResearchJobOutcome:
        results = self._readiness_result_store
        evidence_store = self._readiness_execution_evidence_store
        publication = plan.publication
        if results is None or evidence_store is None:
            raise OnlyResearchJobError(
                OnlyResearchJobPhase.PLAN_VALIDATION,
                "RESEARCH_JOB_READINESS_AUTHORITIES_UNAVAILABLE",
                "Result V2 and Evidence V2 authorities are required",
            )
        assert publication is not None  # execute revalidated the exact Plan contract.
        observed_result_fingerprint = required_result_fingerprint
        context = self._runtime_execution_context
        if context is not None:
            try:
                context = _only_require_research_runtime_execution_context(context, plan.calculation_graph.fingerprint)
            except OnlyResearchCalculationError as exc:
                raise _job_error(OnlyResearchJobPhase.PLAN_VALIDATION, exc) from exc
        try:
            existing = results.load_verified(plan.calculation_fingerprint)
        except OnlyResearchCalculationResultStoreError as exc:
            if (
                exc.code != "RESULT_NOT_FOUND"
                or required_result_fingerprint is not None
                or required_evidence_fingerprint is not None
            ):
                raise _job_error(OnlyResearchJobPhase.RESULT_REUSE, exc) from exc
            try:
                evidence_store.require_no_retained_evidence_for_calculation(plan.calculation_fingerprint)
            except OnlyResearchCalculationError as evidence_error:
                raise _job_error(OnlyResearchJobPhase.RESULT_REUSE, evidence_error) from evidence_error
        except Exception as exc:
            raise OnlyResearchJobError(
                OnlyResearchJobPhase.RESULT_REUSE, "RESEARCH_JOB_RESULT_REUSE_FAILED", str(exc)
            ) from exc
        else:
            _require_result_v2(plan, existing, OnlyResearchJobPhase.RESULT_REUSE)
            if (
                required_result_fingerprint is not None
                and existing.manifest.calculation_result_fingerprint != required_result_fingerprint
            ):
                raise OnlyResearchJobError(
                    OnlyResearchJobPhase.RESULT_REUSE, "DETERMINISTIC_RESULT_CONFLICT", "protected Calculation changed"
                )
            observed_result_fingerprint = existing.manifest.calculation_result_fingerprint
            try:
                if context is None:
                    selected = evidence_store.require_for_result(existing, self._authoring_generation_fingerprint)
                else:
                    selected = evidence_store.load_exact_for_result(
                        existing,
                        tuple(
                            OnlyResearchCalculationImplementationBinding(*item)
                            for item in context.implementation_bindings
                        ),
                        context.provenance,
                        self._authoring_generation_fingerprint,
                    )
            except OnlyResearchJobError:
                raise
            except OnlyResearchCalculationError as exc:
                if exc.code != "RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND" or required_evidence_fingerprint is not None:
                    raise _job_error(OnlyResearchJobPhase.RESULT_REUSE, exc) from exc
            except Exception as exc:
                raise OnlyResearchJobError(
                    OnlyResearchJobPhase.RESULT_REUSE, "RESEARCH_JOB_RESULT_REUSE_FAILED", str(exc)
                ) from exc
            else:
                if (
                    required_evidence_fingerprint is not None
                    and selected.evidence_fingerprint != required_evidence_fingerprint
                ):
                    raise OnlyResearchJobError(
                        OnlyResearchJobPhase.RESULT_REUSE,
                        "RESEARCH_EXECUTION_IDENTITY_MISMATCH",
                        "protected producer differs",
                    )
                # Only initial lookup absence permits a new producer. Once selected,
                # loss during ACK cannot be reinterpreted as fresh-work permission.
                _outcome_v2(
                    plan,
                    existing,
                    selected,
                    self._authoring_generation_fingerprint,
                    OnlyResearchJobDisposition.REUSED,
                    OnlyResearchJobPhase.RESULT_REUSE,
                    context,
                )
                try:
                    evidence = evidence_store.acknowledge_exact(selected.evidence_fingerprint)
                except OnlyResearchCalculationError as exc:
                    raise _job_error(OnlyResearchJobPhase.RESULT_REUSE, exc) from exc
                except Exception as exc:
                    raise OnlyResearchJobError(
                        OnlyResearchJobPhase.RESULT_REUSE, "RESEARCH_JOB_RESULT_REUSE_FAILED", str(exc)
                    ) from exc
                return _outcome_v2(
                    plan,
                    existing,
                    evidence,
                    self._authoring_generation_fingerprint,
                    OnlyResearchJobDisposition.REUSED,
                    OnlyResearchJobPhase.RESULT_REUSE,
                    context,
                )

        # Only proved missing Result or exact Evidence permits execution. Result-only
        # recovery needs a new live producer capability, never a public Result claim.
        parity = None
        try:
            parity = self._result_store.load_verified(plan.calculation_fingerprint)
        except OnlyResearchCalculationResultStoreError as exc:
            if exc.code != "RESULT_NOT_FOUND":
                raise _job_error(OnlyResearchJobPhase.RESULT_REUSE, exc) from exc
        except Exception as exc:
            raise OnlyResearchJobError(
                OnlyResearchJobPhase.RESULT_REUSE, "RESEARCH_JOB_RESULT_REUSE_FAILED", str(exc)
            ) from exc
        else:
            if (
                type(parity) is not OnlyResearchCalculationResult
                or type(parity.manifest) is not OnlyResearchCalculationResultManifest
                or type(parity.manifest.schema_version) is not int
                or parity.manifest.schema_version != 1
                or parity.manifest.calculation_fingerprint != plan.calculation_fingerprint
                or parity.manifest.dataset_snapshot_fingerprint != plan.dataset_snapshot_fingerprint
                or parity.manifest.calculation_graph_fingerprint != plan.calculation_graph.fingerprint
            ):
                raise OnlyResearchJobError(
                    OnlyResearchJobPhase.RESULT_REUSE, "RESULT_INVALID", "V1 parity authority differs from Plan"
                )
            try:
                OnlyResearchCalculationResultManifest.from_dict(parity.manifest.to_dict())
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                raise OnlyResearchJobError(
                    OnlyResearchJobPhase.RESULT_REUSE, "RESULT_INVALID", "invalid V1 parity identity proof"
                ) from exc
        try:
            if context is None:
                sealed = self._calculation_executor._execute_verified_v2(
                    plan.dataset_snapshot_fingerprint,
                    plan.calculation_graph,
                    publication,
                )
            else:
                sealed = self._calculation_executor._execute_verified_v2(
                    plan.dataset_snapshot_fingerprint,
                    plan.calculation_graph,
                    publication,
                    runtime_context=context,
                )
            execution = _only_require_verified_research_calculation_execution_v2(sealed)
            if parity is not None:
                _require_numeric_parity(plan, parity, execution.outputs)
        except OnlyResearchCalculationError as exc:
            phase = (
                OnlyResearchJobPhase.DATASET_VERIFICATION
                if exc.code == "RESEARCH_DATASET_VERIFICATION_FAILED"
                else OnlyResearchJobPhase.CALCULATION_EXECUTION
            )
            raise _job_error(phase, exc) from exc
        except OnlyResearchJobError:
            raise
        except Exception as exc:
            raise OnlyResearchJobError(
                OnlyResearchJobPhase.CALCULATION_EXECUTION, "RESEARCH_JOB_EXECUTION_FAILED", str(exc)
            ) from exc
        try:
            if observed_result_fingerprint is None:
                committed = results.commit(sealed, plan.calculation_graph)
            else:
                # Observing a committed prefix never grants permission to rebuild
                # it if it disappears during a new producer's numerical work.
                current = results.load_verified(plan.calculation_fingerprint)
                _require_existing_execution_v2(plan, current, execution)
                committed = results.acknowledge_exact(plan.calculation_fingerprint, observed_result_fingerprint)
            _require_result_v2(plan, committed, OnlyResearchJobPhase.RESULT_COMMIT)
            evidence = evidence_store._publish_verified(sealed, committed, self._authoring_generation_fingerprint)
        except OnlyResearchCalculationError as exc:
            raise _job_error(OnlyResearchJobPhase.RESULT_COMMIT, exc) from exc
        except OnlyResearchJobError:
            raise
        except Exception as exc:
            raise OnlyResearchJobError(
                OnlyResearchJobPhase.RESULT_COMMIT, "RESEARCH_JOB_RESULT_COMMIT_FAILED", str(exc)
            ) from exc
        return _outcome_v2(
            plan,
            committed,
            evidence,
            self._authoring_generation_fingerprint,
            OnlyResearchJobDisposition.EXECUTED,
            OnlyResearchJobPhase.RESULT_COMMIT,
            context,
        )


def _require_existing_execution_v2(
    plan: OnlyResearchJobPlan,
    result: OnlyResearchCalculationResultV2,
    execution: object,
) -> None:
    from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutionV2
    from onlyalpha.research.calculation.result_store import _canonical_outputs, _tables_equal
    from onlyalpha.research.calculation.result_v2_store import _canonical_readiness

    if not isinstance(execution, OnlyResearchCalculationExecutionV2):
        raise OnlyResearchJobError(
            OnlyResearchJobPhase.RESULT_COMMIT, "RESULT_INVALID", "verified V2 execution required"
        )
    _require_result_v2(plan, result, OnlyResearchJobPhase.RESULT_COMMIT)
    axes = {item.instrument_id: tuple(item.table["ts_event_ns"].to_pylist()) for item in result.outputs}
    outputs = _canonical_outputs(execution.outputs, plan.calculation_graph, axes)
    readiness = _canonical_readiness(execution.readiness, outputs, plan.calculation_graph, axes)
    proposed: tuple[OnlyResearchCalculationNodeOutput | OnlyResearchCalculationNodeReadiness, ...] = (
        *outputs,
        *readiness,
    )
    actual: tuple[OnlyResearchCalculationNodeOutput | OnlyResearchCalculationNodeReadiness, ...] = (
        *result.outputs,
        *result.readiness,
    )
    if any(
        (left.node_fingerprint, left.instrument_id) != (right.node_fingerprint, right.instrument_id)
        or not _tables_equal(left.table, right.table)
        for left, right in zip(proposed, actual, strict=True)
    ):
        raise OnlyResearchJobError(
            OnlyResearchJobPhase.RESULT_COMMIT,
            "DETERMINISTIC_RESULT_CONFLICT",
            "live producer differs from protected Result",
        )


def _require_numeric_parity(
    plan: OnlyResearchJobPlan,
    legacy: OnlyResearchCalculationResult,
    outputs: tuple[OnlyResearchCalculationNodeOutput, ...],
) -> None:
    from onlyalpha.research.calculation.result_store import _canonical_outputs, _tables_equal

    try:
        keys = tuple((item.node_fingerprint, item.instrument_id) for item in legacy.outputs)
        if keys != tuple(sorted(set(keys))) or keys != tuple(
            (item.node_fingerprint, item.instrument_id) for item in outputs
        ):
            raise ValueError("numeric partition membership/order differs")
        axes = {item.instrument_id: tuple(item.table["ts_event_ns"].to_pylist()) for item in legacy.outputs}
        canonical = _canonical_outputs(outputs, plan.calculation_graph, axes)
        for old, raw, new in zip(legacy.outputs, outputs, canonical, strict=True):
            # Result canonicalizes declared field nullability, not values or types.
            # Preserve metadata checks rather than letting normalization discard drift.
            if (
                raw.table.schema.metadata != old.table.schema.metadata
                or any(field.metadata != old.table.schema.field(field.name).metadata for field in raw.table.schema)
                or not _tables_equal(old.table, new.table)
            ):
                raise ValueError("exact numeric schema/axis/nulls/values differ")
    except (KeyError, TypeError, ValueError) as exc:
        raise OnlyResearchJobError(
            OnlyResearchJobPhase.CALCULATION_EXECUTION, "READINESS_NUMERIC_PARITY_MISMATCH", str(exc)
        ) from exc


def _require_result_v2(
    plan: OnlyResearchJobPlan, result: OnlyResearchCalculationResultV2, phase: OnlyResearchJobPhase
) -> None:
    from onlyalpha.research.calculation.result_v2 import (
        OnlyResearchCalculationResultManifestV2,
        OnlyResearchCalculationResultV2,
    )

    publication = plan.publication
    if (
        type(result) is not OnlyResearchCalculationResultV2
        or type(result.manifest) is not OnlyResearchCalculationResultManifestV2
        or publication is None
    ):
        raise OnlyResearchJobError(phase, "RESULT_INVALID", "exact Result V2 required")
    manifest = result.manifest
    try:
        manifest.__post_init__()
        OnlyResearchCalculationResultManifestV2.from_dict(manifest.to_dict())
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise OnlyResearchJobError(phase, "RESULT_INVALID", "invalid Result V2 proof") from exc
    if (
        type(manifest.schema_version) is not int
        or manifest.schema_version != publication.calculation_result_schema_version
        or type(manifest.readiness_contract_version) is not int
        or manifest.readiness_contract_version != publication.readiness_contract_version
        or manifest.calculation_fingerprint != plan.calculation_fingerprint
        or manifest.dataset_snapshot_fingerprint != plan.dataset_snapshot_fingerprint
        or manifest.calculation_graph_fingerprint != plan.calculation_graph.fingerprint
        or manifest.calculation_graph.fingerprint != plan.calculation_graph.fingerprint
    ):
        raise OnlyResearchJobError(phase, "RESULT_INVALID", "Result V2 authority does not match Plan")


def _outcome_v2(
    plan: OnlyResearchJobPlan,
    result: OnlyResearchCalculationResultV2,
    evidence: OnlyResearchCalculationExecutionEvidenceV2,
    generation: str | None,
    disposition: OnlyResearchJobDisposition,
    phase: OnlyResearchJobPhase,
    runtime_context: _OnlyResearchRuntimeExecutionContext | None = None,
) -> OnlyResearchJobOutcome:
    from onlyalpha.research.calculation.execution_evidence_v2 import OnlyResearchCalculationExecutionEvidenceV2

    _require_result_v2(plan, result, phase)
    manifest, publication = result.manifest, plan.publication
    assert publication is not None
    if type(evidence) is not OnlyResearchCalculationExecutionEvidenceV2:
        raise OnlyResearchJobError(phase, "RESULT_INVALID", "exact Evidence V2 required")
    try:
        evidence.__post_init__()
        OnlyResearchCalculationExecutionEvidenceV2.from_dict(evidence.to_dict())
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise OnlyResearchJobError(phase, "RESULT_INVALID", "invalid Evidence V2 proof") from exc
    if (
        evidence.schema_version != publication.execution_evidence_schema_version
        or evidence.calculation_result_schema_version != publication.calculation_result_schema_version
        or evidence.readiness_contract_version != publication.readiness_contract_version
        or evidence.calculation_fingerprint != manifest.calculation_fingerprint
        or evidence.dataset_snapshot_fingerprint != manifest.dataset_snapshot_fingerprint
        or evidence.calculation_graph_fingerprint != manifest.calculation_graph_fingerprint
        or evidence.calculation_result_fingerprint != manifest.calculation_result_fingerprint
        or evidence.result_content_fingerprint != manifest.result_content_fingerprint
        or tuple(item.node_fingerprint for item in evidence.research_implementation_bindings)
        != tuple(sorted(node.fingerprint for node in plan.calculation_graph.nodes))
        or (generation is not None and evidence.authoring_generation_fingerprint != generation)
    ):
        raise OnlyResearchJobError(phase, "RESULT_INVALID", "Evidence V2 authority does not match Result/Plan")
    if runtime_context is not None:
        context = _only_require_research_runtime_execution_context(runtime_context, plan.calculation_graph.fingerprint)
        if (
            evidence.runtime_execution_provenance != context.provenance
            or tuple(
                (item.node_fingerprint, item.research_implementation_fingerprint)
                for item in evidence.research_implementation_bindings
            )
            != context.implementation_bindings
        ):
            raise OnlyResearchJobError(phase, "RESULT_INVALID", "Evidence V2 exact Runtime producer differs")
    return OnlyResearchJobOutcome(
        OnlyResearchJobStatus.SUCCEEDED,
        disposition,
        manifest.calculation_fingerprint,
        manifest.calculation_result_fingerprint,
        evidence.evidence_fingerprint,
    )


def _job_error(phase: OnlyResearchJobPhase, error: OnlyResearchCalculationError) -> OnlyResearchJobError:
    return OnlyResearchJobError(phase, error.code, error.detail)


def _outcome(
    plan: OnlyResearchJobPlan,
    result: OnlyResearchCalculationResult,
    evidence: OnlyResearchCalculationExecutionEvidence,
    disposition: OnlyResearchJobDisposition,
    phase: OnlyResearchJobPhase,
) -> OnlyResearchJobOutcome:
    manifest = result.manifest
    if (
        manifest.calculation_fingerprint != plan.calculation_fingerprint
        or manifest.dataset_snapshot_fingerprint != plan.dataset_snapshot_fingerprint
        or manifest.calculation_graph_fingerprint != plan.calculation_graph.fingerprint
        or evidence.calculation_fingerprint != manifest.calculation_fingerprint
        or evidence.calculation_result_fingerprint != manifest.calculation_result_fingerprint
    ):
        raise OnlyResearchJobError(phase, "RESULT_INVALID", "Result authority does not match Research Job Plan")
    return OnlyResearchJobOutcome(
        OnlyResearchJobStatus.SUCCEEDED,
        disposition,
        manifest.calculation_fingerprint,
        manifest.calculation_result_fingerprint,
        evidence.evidence_fingerprint,
    )
