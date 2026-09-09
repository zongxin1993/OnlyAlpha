"""Crash-resumable adaptive decision and Plan-batch controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.research.experiment import (
    OnlySearchFailureCode,
    OnlySearchIterationDisposition,
    OnlySearchIterationPlanV1,
    OnlySearchIterationResultV1,
)
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver

from .algorithm import decide_parameter_search_v1
from .context import OnlyVerifiedParameterSearchContextV1, admit_current_parameter_algorithm_runtime
from .errors import OnlyParameterSearchError
from .evidence import OnlyParameterResearchEvidenceReader, OnlyParameterResearchEvidenceV1
from .execution import OnlyHostedParameterGenerationExecutionV1
from .integration import (
    OnlyParameterResearchCommandService,
    commit_feedback_plan_batch,
    reconcile_parameter_research_plan,
    resolve_parameter_research_candidate,
)
from .model import OnlyParameterSearchFeedbackDecisionV1
from .store import OnlyJsonParameterSearchStore
from .verification import (
    verify_hosted_parameter_feedback_decision_occurrence,
    verify_parameter_feedback_decision_occurrence,
    verify_parameter_feedback_frontier_for_execution,
)


class OnlyParameterControllerProvenance(Protocol):
    def iteration_plans_for_experiment_verified(
        self, experiment_fingerprint: str
    ) -> tuple[OnlySearchIterationPlanV1, ...]: ...

    def terminal_result_for_plan_verified(self, plan_fingerprint: str) -> OnlySearchIterationResultV1 | None: ...

    def commit_iteration_plan(self, value: OnlySearchIterationPlanV1) -> object: ...

    def commit_iteration_result(self, value: OnlySearchIterationResultV1) -> object: ...


@dataclass(frozen=True, slots=True)
class OnlyParameterControllerOutcomeV1:
    decision: OnlyParameterSearchFeedbackDecisionV1
    plans: tuple[OnlySearchIterationPlanV1, ...]


class OnlyParameterSearchControllerV1:
    def __init__(
        self,
        *,
        parameter_store: OnlyJsonParameterSearchStore,
        provenance: OnlyParameterControllerProvenance,
        evidence_reader: OnlyParameterResearchEvidenceReader,
        generation_execution: OnlyHostedParameterGenerationExecutionV1 | None = None,
    ) -> None:
        self._store = parameter_store
        self._provenance = provenance
        self._evidence_reader = evidence_reader
        self._generation_execution = generation_execution

    def advance(
        self,
        context: OnlyVerifiedParameterSearchContextV1,
    ) -> OnlyParameterControllerOutcomeV1:
        """Explicit same-generation/current-runtime compatibility entrypoint."""

        return self._advance(context, runtime_generation_fingerprint=None)

    def advance_in_generation(
        self,
        context: OnlyVerifiedParameterSearchContextV1,
        runtime_generation_fingerprint: str,
    ) -> OnlyParameterControllerOutcomeV1:
        """Production historical path using the exact PRE-E.A-bound generation."""

        return self._advance(context, runtime_generation_fingerprint=runtime_generation_fingerprint)

    def _advance(
        self,
        context: OnlyVerifiedParameterSearchContextV1,
        *,
        runtime_generation_fingerprint: str | None,
    ) -> OnlyParameterControllerOutcomeV1:
        experiment = context.experiment
        current = self._store.load_frontier_fingerprint(experiment.experiment_fingerprint)
        current_runtime = (
            admit_current_parameter_algorithm_runtime(context) if runtime_generation_fingerprint is None else None
        )
        if current is not None:
            if runtime_generation_fingerprint is None:
                durable_frontier = verify_parameter_feedback_frontier_for_execution(
                    context=context,
                    provenance=self._provenance,
                    evidence_reader=self._evidence_reader,
                    decisions=self._store,
                    frontier_fingerprint=current,
                )
            else:
                durable_frontier = self._store.load_feedback_decision_intrinsic_verified(current)
                if (
                    durable_frontier.experiment_fingerprint != experiment.experiment_fingerprint
                    or durable_frontier.search_policy_fingerprint != context.policy.policy_fingerprint
                    or durable_frontier.algorithm_implementation_fingerprint
                    != context.historical_algorithm_manifest.implementation_fingerprint
                ):
                    raise OnlyParameterSearchError("PARAMETER_FEEDBACK_HISTORY_UNVERIFIED", current)
            commit_feedback_plan_batch(durable_frontier, context.proposals, self._provenance)
        committed_plans = self._provenance.iteration_plans_for_experiment_verified(experiment.experiment_fingerprint)
        terminal_results = []
        for plan in committed_plans:
            result = self._provenance.terminal_result_for_plan_verified(plan.iteration_plan_fingerprint)
            if result is None:
                raise OnlyParameterSearchError("SEARCH_ROUND_BARRIER_OPEN", plan.iteration_plan_fingerprint)
            terminal_results.append(result)
        plans_by_fingerprint = {item.iteration_plan_fingerprint: item for item in committed_plans}
        proposals_by_fingerprint = {item.proposal_fingerprint: item for item in context.proposals}
        evidence = []
        for result in terminal_results:
            evidence_plan = plans_by_fingerprint.get(result.iteration_plan_fingerprint)
            proposal = (
                None if evidence_plan is None else proposals_by_fingerprint.get(evidence_plan.proposal_fingerprint)
            )
            if proposal is None:
                raise OnlyParameterSearchError("IDENTITY_MISMATCH", result.iteration_result_fingerprint)
            evidence.append(
                self._evidence_reader.load_required(
                    iteration_result_fingerprint=result.iteration_result_fingerprint,
                    proposal=proposal,
                    policy=context.policy,
                )
            )
        evidence_values = tuple(evidence)
        decision_ids: list[str] = []
        for plan in sorted(committed_plans, key=lambda item: item.iteration_index):
            if not decision_ids or decision_ids[-1] != plan.decision_output_fingerprint:
                decision_ids.append(plan.decision_output_fingerprint)
        prior = tuple(self._store.load_feedback_decision_intrinsic_verified(item) for item in decision_ids)
        if runtime_generation_fingerprint is None:
            assert current_runtime is not None
            decision = decide_parameter_search_v1(
                experiment_fingerprint=experiment.experiment_fingerprint,
                proposals=context.proposals,
                policy=context.policy,
                algorithm_implementation_fingerprint=current_runtime.implementation_fingerprint,
                budget=experiment.search_budget,
                evidence=evidence_values,
                prior_decisions=prior,
            )
        else:
            if self._generation_execution is None:
                raise OnlyParameterSearchError(
                    "HISTORICAL_GENERATION_CAPABILITY_UNSUPPORTED",
                    runtime_generation_fingerprint,
                )
            decision = self._generation_execution.derive_decision(
                runtime_generation_fingerprint,
                context,
                evidence_values,
                prior,
            )
        if runtime_generation_fingerprint is None:
            verified = verify_parameter_feedback_decision_occurrence(
                context=context,
                provenance=self._provenance,
                evidence_reader=self._evidence_reader,
                decisions=self._store,
                candidate_decision=decision,
            )
        else:
            verified = verify_hosted_parameter_feedback_decision_occurrence(
                context=context,
                provenance=self._provenance,
                decisions=self._store,
                candidate_decision=decision,
            )
        predecessor = verified.predecessor_fingerprint
        if current is not None and current != decision.feedback_decision_fingerprint and current != predecessor:
            raise OnlyParameterSearchError("PARAMETER_FEEDBACK_FRONTIER_CONFLICT", current)
        self._store.commit_feedback_decision(verified)
        plans = commit_feedback_plan_batch(decision, context.proposals, self._provenance)
        return OnlyParameterControllerOutcomeV1(decision, plans)

    def reconcile_open_plans(
        self,
        context: OnlyVerifiedParameterSearchContextV1,
        *,
        resolver: OnlyResearchSpecificationResolver,
        commands: OnlyParameterResearchCommandService,
        runtime_generation_fingerprint: str | None = None,
    ) -> tuple[OnlySearchIterationResultV1 | None, ...]:
        """Drive each exact occurrence to terminal or retain the active barrier."""

        frontier = self._store.load_frontier_fingerprint(context.experiment.experiment_fingerprint)
        if frontier is None:
            plans = self._provenance.iteration_plans_for_experiment_verified(context.experiment.experiment_fingerprint)
            if plans:
                raise OnlyParameterSearchError("PARAMETER_FEEDBACK_HISTORY_UNVERIFIED", "missing frontier")
            return ()
        verify_parameter_feedback_frontier_for_execution(
            context=context,
            provenance=self._provenance,
            evidence_reader=self._evidence_reader,
            decisions=self._store,
            frontier_fingerprint=frontier,
        )
        plans = self._provenance.iteration_plans_for_experiment_verified(context.experiment.experiment_fingerprint)
        by_fingerprint = {item.proposal_fingerprint: item for item in context.proposals}
        outcomes: list[OnlySearchIterationResultV1 | None] = []
        for plan in plans:
            terminal = self._provenance.terminal_result_for_plan_verified(plan.iteration_plan_fingerprint)
            if terminal is not None:
                outcomes.append(terminal)
                continue
            proposal = by_fingerprint.get(plan.proposal_fingerprint)
            if proposal is None:
                raise OnlyParameterSearchError("SEARCH_INVALID_PROPOSAL", plan.proposal_fingerprint)
            try:
                resolved = resolve_parameter_research_candidate(context, proposal, resolver)
            except OnlyParameterSearchError as exc:
                if exc.code != "CANDIDATE_BINDING_FAILED":
                    raise
                result = OnlySearchIterationResultV1(
                    plan.iteration_plan_fingerprint,
                    None,
                    False,
                    None,
                    False,
                    None,
                    OnlySearchIterationDisposition.FAILED,
                    OnlySearchFailureCode.CANDIDATE_BINDING_FAILED,
                )
                self._provenance.commit_iteration_result(result)
                outcomes.append(result)
                continue
            if runtime_generation_fingerprint is not None:
                if self._generation_execution is None:
                    raise OnlyParameterSearchError(
                        "HISTORICAL_GENERATION_CAPABILITY_UNSUPPORTED",
                        runtime_generation_fingerprint,
                    )
                self._generation_execution.verify_resolved_research(
                    runtime_generation_fingerprint,
                    context,
                    proposal,
                    resolved,
                )
            outcomes.append(
                reconcile_parameter_research_plan(
                    plan=plan,
                    resolved=resolved,
                    provenance=self._provenance,
                    commands=commands,
                    policy=context.policy,
                )
            )
        return tuple(outcomes)

    def certify_historical_reproduction(
        self,
        context: OnlyVerifiedParameterSearchContextV1,
        historical: OnlyParameterSearchFeedbackDecisionV1,
        evidence: tuple[OnlyParameterResearchEvidenceV1, ...],
        prior_decisions: tuple[OnlyParameterSearchFeedbackDecisionV1, ...] = (),
    ) -> OnlyParameterSearchFeedbackDecisionV1:
        runtime = admit_current_parameter_algorithm_runtime(context)
        reproduced = decide_parameter_search_v1(
            experiment_fingerprint=context.experiment.experiment_fingerprint,
            proposals=context.proposals,
            policy=context.policy,
            algorithm_implementation_fingerprint=runtime.implementation_fingerprint,
            budget=context.experiment.search_budget,
            evidence=evidence,
            prior_decisions=prior_decisions,
        )
        if reproduced != historical:
            raise OnlyParameterSearchError(
                "PARAMETER_FEEDBACK_REPRODUCTION_MISMATCH",
                historical.feedback_decision_fingerprint,
            )
        return reproduced


__all__ = [name for name in globals() if name.startswith("OnlyParameter")]
