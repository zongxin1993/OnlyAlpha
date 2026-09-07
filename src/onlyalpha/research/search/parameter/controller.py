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
from .integration import (
    OnlyParameterResearchCommandService,
    commit_feedback_plan_batch,
    reconcile_parameter_research_plan,
    resolve_parameter_research_candidate,
)
from .model import OnlyParameterSearchFeedbackDecisionV1
from .store import OnlyJsonParameterSearchStore
from .verification import (
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
    ) -> None:
        self._store = parameter_store
        self._provenance = provenance
        self._evidence_reader = evidence_reader

    def advance(
        self,
        context: OnlyVerifiedParameterSearchContextV1,
    ) -> OnlyParameterControllerOutcomeV1:
        experiment = context.experiment
        current = self._store.load_frontier_fingerprint(experiment.experiment_fingerprint)
        runtime = admit_current_parameter_algorithm_runtime(context)
        if current is not None:
            durable_frontier = verify_parameter_feedback_frontier_for_execution(
                context=context,
                provenance=self._provenance,
                evidence_reader=self._evidence_reader,
                decisions=self._store,
                frontier_fingerprint=current,
            )
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
        decision = decide_parameter_search_v1(
            experiment_fingerprint=experiment.experiment_fingerprint,
            proposals=context.proposals,
            policy=context.policy,
            algorithm_implementation_fingerprint=runtime.implementation_fingerprint,
            budget=experiment.search_budget,
            evidence=evidence_values,
            prior_decisions=prior,
        )
        verified = verify_parameter_feedback_decision_occurrence(
            context=context,
            provenance=self._provenance,
            evidence_reader=self._evidence_reader,
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
    ) -> tuple[OnlySearchIterationResultV1 | None, ...]:
        """Drive each exact occurrence to terminal or retain the active barrier."""

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
