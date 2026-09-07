"""Normal Research resolution and recoverable B3.1 occurrence integration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from typing import Any, Protocol, cast

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.research.command.errors import OnlyResearchSubmissionConflictError
from onlyalpha.research.command.model import OnlyResearchSubmitOutcome
from onlyalpha.research.evaluation.definition import OnlyResearchStatisticsMethod
from onlyalpha.research.evaluation.summary.definition import OnlyResearchEffectSummaryDefinition
from onlyalpha.research.evaluation.summary.metric import (
    OnlyResearchSummaryKind,
    only_research_summary_metric,
)
from onlyalpha.research.evaluation.summary.plan import OnlyResearchEffectSummaryPlan
from onlyalpha.research.experiment import (
    OnlySearchFailureCode,
    OnlySearchIterationDisposition,
    OnlySearchIterationPlanV1,
    OnlySearchIterationResultV1,
    OnlySearchResearchResultReferenceV1,
)
from onlyalpha.research.result.plan import OnlyResearchResultPlan
from onlyalpha.research.run.errors import OnlyResearchRunIntegrityError
from onlyalpha.research.run.model import OnlyResearchRun, OnlyResearchRunState
from onlyalpha.research.search.symbolic.materialization import research_specification_from_candidate_graph
from onlyalpha.research.specification.model import OnlyResearchSpecification
from onlyalpha.research.specification.resolver import (
    OnlyResearchCandidateLineage,
    OnlyResearchSpecificationResolution,
    OnlyResearchSpecificationResolver,
)

from .context import OnlyVerifiedParameterSearchContextV1
from .errors import OnlyParameterSearchError
from .model import (
    PARAMETER_PROPOSAL_KIND,
    PARAMETER_PROPOSAL_SCHEMA_VERSION,
    OnlyParameterGraphProposalV1,
    OnlyParameterSearchFeedbackDecisionV1,
    OnlyParameterSearchPolicyV1,
)


class OnlyParameterProvenanceWriter(Protocol):
    def commit_iteration_plan(self, value: OnlySearchIterationPlanV1) -> object: ...

    def commit_iteration_result(self, value: OnlySearchIterationResultV1) -> object: ...

    def terminal_result_for_plan_verified(self, plan_fingerprint: str) -> OnlySearchIterationResultV1 | None: ...


class OnlyParameterResearchCommandService(Protocol):
    def submit_research_run(
        self,
        submission_key: OnlyProductCommandId,
        specification: object,
        provenance: object | None = None,
    ) -> OnlyResearchSubmitOutcome: ...

    def finalize_parameter_evidence(
        self,
        *,
        run: OnlyResearchRun,
        resolved: OnlyResolvedParameterResearchCandidateV1,
        policy: OnlyParameterSearchPolicyV1,
    ) -> OnlySearchResearchResultReferenceV1: ...


class OnlyParameterRunReader(Protocol):
    def load(self, run_id: object) -> object: ...


class _ParameterResearchResultStore(Protocol):
    def load_verified(self, locator_fingerprint: str) -> object: ...

    def commit(self, value: object) -> object: ...


class _ParameterSummaryExecutor(Protocol):
    def execute(self, plan: OnlyResearchEffectSummaryPlan) -> object: ...


class _ParameterResultAssembler(Protocol):
    def assemble(self, plan: OnlyResearchResultPlan) -> object: ...


class _ParameterResearchSubmitter(Protocol):
    def submit_research_run(
        self,
        submission_key: OnlyProductCommandId,
        specification: object,
        provenance: object | None = None,
    ) -> OnlyResearchSubmitOutcome: ...


@dataclass(frozen=True, slots=True)
class OnlyResolvedParameterResearchCandidateV1:
    proposal: OnlyParameterGraphProposalV1
    specification: OnlyResearchSpecification
    resolution: OnlyResearchSpecificationResolution
    candidate: OnlyResearchCandidateLineage


class OnlyParameterResearchEvidenceFinalizerV1:
    """Compose exact Summary Evidence from a completed normal Research Result."""

    def __init__(
        self,
        *,
        research_results: _ParameterResearchResultStore,
        summary_executor: _ParameterSummaryExecutor,
        result_assembler: _ParameterResultAssembler,
    ) -> None:
        self._research_results = research_results
        self._summary_executor = summary_executor
        self._result_assembler = result_assembler

    def finalize(
        self,
        *,
        run: OnlyResearchRun,
        resolved: OnlyResolvedParameterResearchCandidateV1,
        policy: OnlyParameterSearchPolicyV1,
    ) -> OnlySearchResearchResultReferenceV1:
        if run.state is not OnlyResearchRunState.COMPLETED or run.research_result_fingerprint is None:
            raise OnlyParameterSearchError("AMBIGUOUS_ATTEMPT_STATE", run.run_id.value)
        if not isinstance(policy, OnlyParameterSearchPolicyV1):
            raise OnlyParameterSearchError("PARAMETER_EVIDENCE_POLICY_INVALID")
        try:
            descriptors = tuple(only_research_summary_metric(item) for item in policy.required_metric_ids)
        except ValueError as exc:
            raise OnlyParameterSearchError("PARAMETER_EVIDENCE_METRIC_SET_UNSUPPORTED") from exc
        summary_contracts = {(item.summary_kind, item.source_method) for item in descriptors}
        if len(summary_contracts) != 1:
            raise OnlyParameterSearchError("PARAMETER_EVIDENCE_METRIC_SET_UNSUPPORTED")
        summary_kind, source_method = next(iter(summary_contracts))
        if summary_kind is not OnlyResearchSummaryKind.EFFECT_SUMMARY or not isinstance(
            source_method, OnlyResearchStatisticsMethod
        ):
            raise OnlyParameterSearchError("PARAMETER_EVIDENCE_METRIC_SET_UNSUPPORTED")

        base_plan = resolved.resolution.workload.result_plan
        base_result = self._research_results.load_verified(base_plan.fingerprint)
        base_manifest = cast(Any, base_result).manifest
        if (
            base_manifest.research_result_plan_fingerprint != base_plan.fingerprint
            or base_manifest.research_result_fingerprint != run.research_result_fingerprint
        ):
            raise OnlyParameterSearchError("AMBIGUOUS_ATTEMPT_STATE", run.run_id.value)
        source_plans = tuple(
            item
            for item in resolved.resolution.workload.statistics_plans
            if item.definition.method is source_method
            and item.feature.calculation_fingerprint == resolved.candidate.calculation_fingerprint
        )
        if len(source_plans) != 1:
            raise OnlyParameterSearchError("PARAMETER_EVIDENCE_SOURCE_AMBIGUOUS", run.run_id.value)
        source_plan = source_plans[0]
        source_references = tuple(
            item
            for item in base_manifest.statistics_results
            if item.statistics_fingerprint == source_plan.statistics_fingerprint
        )
        if len(source_references) != 1:
            raise OnlyParameterSearchError("PARAMETER_EVIDENCE_SOURCE_AMBIGUOUS", run.run_id.value)
        candidate_fingerprint = resolved.candidate.candidate_fingerprint
        if candidate_fingerprint is None:
            raise OnlyParameterSearchError("CANDIDATE_BINDING_FAILED", resolved.proposal.proposal_fingerprint)
        summary_plan = OnlyResearchEffectSummaryPlan(
            base_manifest.dataset_snapshot_fingerprint,
            candidate_fingerprint,
            source_plan.feature,
            source_plan.statistics_fingerprint,
            source_references[0].statistics_result_fingerprint,
            OnlyResearchEffectSummaryDefinition(source_method),
        )
        self._summary_executor.execute(summary_plan)

        candidates = tuple(
            replace(
                item,
                statistics_fingerprints=tuple(
                    sorted({*item.statistics_fingerprints, summary_plan.statistics_fingerprint})
                ),
            )
            if item.candidate_fingerprint == candidate_fingerprint
            else item
            for item in base_plan.candidates
        )
        if sum(item.candidate_fingerprint == candidate_fingerprint for item in candidates) != 1:
            raise OnlyParameterSearchError("PARAMETER_EVIDENCE_SOURCE_AMBIGUOUS", candidate_fingerprint)
        evidence_plan = replace(
            base_plan,
            statistics_fingerprints=tuple(
                sorted({*base_plan.statistics_fingerprints, summary_plan.statistics_fingerprint})
            ),
            candidates=candidates,
        )
        assembled = self._result_assembler.assemble(evidence_plan)
        self._research_results.commit(assembled)
        exact = self._research_results.load_verified(evidence_plan.fingerprint)
        manifest = cast(Any, exact).manifest
        if manifest.research_result_plan_fingerprint != evidence_plan.fingerprint:
            raise OnlyParameterSearchError("CORRUPT_REFERENCE", evidence_plan.fingerprint)
        return OnlySearchResearchResultReferenceV1(
            evidence_plan.fingerprint,
            manifest.research_result_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class OnlyParameterResearchCommandGatewayV1:
    """Normal Product Command plus deterministic Research-Evidence composition."""

    commands: _ParameterResearchSubmitter
    evidence_finalizer: OnlyParameterResearchEvidenceFinalizerV1

    def submit_research_run(
        self,
        submission_key: OnlyProductCommandId,
        specification: object,
        provenance: object | None = None,
    ) -> OnlyResearchSubmitOutcome:
        return self.commands.submit_research_run(submission_key, specification, provenance)

    def finalize_parameter_evidence(
        self,
        *,
        run: OnlyResearchRun,
        resolved: OnlyResolvedParameterResearchCandidateV1,
        policy: OnlyParameterSearchPolicyV1,
    ) -> OnlySearchResearchResultReferenceV1:
        return self.evidence_finalizer.finalize(run=run, resolved=resolved, policy=policy)


def resolve_parameter_research_candidate(
    context: OnlyVerifiedParameterSearchContextV1,
    proposal: OnlyParameterGraphProposalV1,
    resolver: OnlyResearchSpecificationResolver,
) -> OnlyResolvedParameterResearchCandidateV1:
    """Create Candidate identity exclusively through the normal Research Resolver."""

    try:
        materialized = research_specification_from_candidate_graph(
            context.evaluation_contract,
            proposal.graph,
            proposal.candidate_node_fingerprint,
            proposal.candidate_output_name,
        )
        resolution = resolver.resolve(materialized.specification)
        candidates = tuple(
            item
            for item in resolution.candidates
            if item.calculation_id == context.evaluation_contract.candidate_calculation_id
            and item.candidate_fingerprint is not None
        )
        if len(candidates) != 1 or candidates[0].graph_fingerprint != proposal.graph_fingerprint:
            raise ValueError("normal Resolver did not produce the exact Candidate")
        return OnlyResolvedParameterResearchCandidateV1(proposal, materialized.specification, resolution, candidates[0])
    except Exception as exc:
        raise OnlyParameterSearchError("CANDIDATE_BINDING_FAILED", proposal.proposal_fingerprint) from exc


def plans_for_feedback_decision(
    decision: OnlyParameterSearchFeedbackDecisionV1,
    proposals: tuple[OnlyParameterGraphProposalV1, ...],
) -> tuple[OnlySearchIterationPlanV1, ...]:
    by_fingerprint = {item.proposal_fingerprint: item for item in proposals}
    parent = decision.selected_anchor_iteration_result_fingerprint
    plans = []
    for position, fingerprint in enumerate(decision.ordered_next_proposal_fingerprints):
        if fingerprint not in by_fingerprint:
            raise OnlyParameterSearchError("SEARCH_INVALID_PROPOSAL", fingerprint)
        plans.append(
            OnlySearchIterationPlanV1(
                decision.experiment_fingerprint,
                decision.start_iteration_index + position,
                PARAMETER_PROPOSAL_KIND,
                PARAMETER_PROPOSAL_SCHEMA_VERSION,
                fingerprint,
                decision.ordered_input_iteration_result_fingerprints,
                (),
                decision.feedback_decision_fingerprint,
                parent,
            )
        )
    return tuple(plans)


def commit_feedback_plan_batch(
    decision: OnlyParameterSearchFeedbackDecisionV1,
    proposals: tuple[OnlyParameterGraphProposalV1, ...],
    provenance: OnlyParameterProvenanceWriter,
) -> tuple[OnlySearchIterationPlanV1, ...]:
    """Idempotently finish a decision's exact Plan batch after any partial crash."""

    plans = plans_for_feedback_decision(decision, proposals)
    for plan in plans:
        provenance.commit_iteration_plan(plan)
    return plans


def parameter_submission_key(plan: OnlySearchIterationPlanV1) -> OnlyProductCommandId:
    """Stable UUID4 derived only from the immutable Plan occurrence identity."""

    raw = bytes.fromhex(plan.iteration_plan_fingerprint[:32])
    return OnlyProductCommandId(str(uuid.UUID(bytes=raw, version=4)))


def reconcile_parameter_research_plan(
    *,
    plan: OnlySearchIterationPlanV1,
    resolved: OnlyResolvedParameterResearchCandidateV1,
    provenance: OnlyParameterProvenanceWriter,
    commands: OnlyParameterResearchCommandService,
    policy: OnlyParameterSearchPolicyV1,
) -> OnlySearchIterationResultV1 | None:
    """Reconcile exact Product Command/Run facts; active states remain behind the barrier."""

    existing = provenance.terminal_result_for_plan_verified(plan.iteration_plan_fingerprint)
    if existing is not None:
        return existing
    try:
        outcome = commands.submit_research_run(parameter_submission_key(plan), resolved.specification)
    except (OnlyResearchSubmissionConflictError, OnlyResearchRunIntegrityError) as exc:
        raise OnlyParameterSearchError("AMBIGUOUS_ATTEMPT_STATE", plan.iteration_plan_fingerprint) from exc
    except Exception:
        raise
    run = outcome.run
    candidate_fingerprint = resolved.candidate.candidate_fingerprint
    if candidate_fingerprint is None:
        raise OnlyParameterSearchError("CANDIDATE_BINDING_FAILED", plan.proposal_fingerprint)
    if run.state in {OnlyResearchRunState.QUEUED, OnlyResearchRunState.RUNNING, OnlyResearchRunState.CANCEL_REQUESTED}:
        return None
    if run.state is OnlyResearchRunState.COMPLETED:
        reference = commands.finalize_parameter_evidence(run=run, resolved=resolved, policy=policy)
        result = OnlySearchIterationResultV1(
            plan.iteration_plan_fingerprint,
            candidate_fingerprint,
            True,
            reference,
            False,
            None,
            OnlySearchIterationDisposition.RESEARCH_EVIDENCE_RECORDED,
            None,
        )
    elif run.state in {OnlyResearchRunState.FAILED, OnlyResearchRunState.CANCELLED}:
        result = OnlySearchIterationResultV1(
            plan.iteration_plan_fingerprint,
            candidate_fingerprint,
            True,
            None,
            False,
            None,
            OnlySearchIterationDisposition.FAILED,
            OnlySearchFailureCode.RESEARCH_EXECUTION_FAILED,
        )
    else:  # pragma: no cover - enum exhaustiveness guard
        raise OnlyParameterSearchError("AMBIGUOUS_ATTEMPT_STATE", plan.iteration_plan_fingerprint)
    provenance.commit_iteration_result(result)
    return result


__all__ = [
    name for name in globals() if name.startswith(("Only", "commit_", "parameter_", "plans_", "reconcile_", "resolve_"))
]
