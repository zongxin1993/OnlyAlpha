"""One-occurrence symbolic Search controller for the Product boundary."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Protocol

from onlyalpha.application.product_command_authority import OnlyProductCommandReceiptAuthority
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandId,
    OnlyProductCommandOutcomeKind,
)
from onlyalpha.application.search_product import (
    OnlySearchBoundedOperationV1,
    OnlySearchPlanExpectedStateV1,
    OnlySearchProductCapabilityUnsupported,
    OnlySearchProductEffectConflict,
    OnlySearchProductEffectStateV1,
    OnlySearchProductExpectedStateMismatch,
    OnlySearchResearchRunReader,
    OnlySymbolicExpectedStateV1,
    only_load_search_research_run_exact,
)
from onlyalpha.research.command.model import OnlyResearchSubmitOutcome
from onlyalpha.research.experiment import (
    OnlySearchFailureCode,
    OnlySearchIterationDisposition,
    OnlySearchIterationPlanV1,
    OnlySearchIterationResultV1,
    OnlySearchResearchResultReferenceV1,
)
from onlyalpha.research.run.model import OnlyResearchRunState
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver

from .context import OnlyVerifiedSymbolicSearchContextV1, admit_current_symbolic_algorithm_runtime
from .enumeration import enumerate_symbolic_factor_proposals
from .execution import build_symbolic_enumeration_result
from .historical import (
    commit_symbolic_enumeration_result_verified,
    load_optional_symbolic_enumeration_result_historical_verified,
    load_symbolic_enumeration_result_historical_verified,
    verify_symbolic_historical_iteration_occurrence,
)
from .integration import OnlySymbolicResolvedResearchCandidateV1, resolve_symbolic_research_candidate
from .model import SYMBOLIC_PROPOSAL_KIND, SYMBOLIC_PROPOSAL_SCHEMA_VERSION
from .store import OnlyJsonSymbolicSearchStore


class OnlySymbolicControllerProvenance(Protocol):
    def iteration_plans_for_experiment_verified(
        self, experiment_fingerprint: str
    ) -> tuple[OnlySearchIterationPlanV1, ...]: ...

    def terminal_result_for_plan_verified(self, plan_fingerprint: str) -> OnlySearchIterationResultV1 | None: ...

    def commit_iteration_plan(self, value: OnlySearchIterationPlanV1) -> object: ...

    def commit_iteration_result(self, value: OnlySearchIterationResultV1) -> object: ...


class OnlySymbolicResearchCommandService(Protocol):
    def submit_symbolic_research(
        self,
        *,
        plan: OnlySearchIterationPlanV1,
        resolved: OnlySymbolicResolvedResearchCandidateV1,
    ) -> OnlyResearchSubmitOutcome: ...

    def research_result_reference(
        self,
        *,
        outcome: OnlyResearchSubmitOutcome,
        resolved: OnlySymbolicResolvedResearchCandidateV1,
    ) -> OnlySearchResearchResultReferenceV1: ...


@dataclass(frozen=True, slots=True)
class OnlySymbolicControllerOutcomeV1:
    plan: OnlySearchIterationPlanV1
    result: OnlySearchIterationResultV1 | None = None


class OnlySymbolicSearchControllerV1:
    """Create or reconcile exactly one deterministic symbolic occurrence."""

    def __init__(
        self,
        *,
        symbolic_store: OnlyJsonSymbolicSearchStore,
        provenance: OnlySymbolicControllerProvenance,
        resolver: OnlyResearchSpecificationResolver,
        product_receipts: OnlyProductCommandReceiptAuthority | None = None,
        research_runs: OnlySearchResearchRunReader | None = None,
    ) -> None:
        self._store = symbolic_store
        self._provenance = provenance
        self._resolver = resolver
        self._product_receipts = product_receipts
        self._research_runs = research_runs

    def expected_state(
        self,
        context: OnlyVerifiedSymbolicSearchContextV1,
        *,
        target_plan_fingerprint: str | None = None,
    ) -> OnlySymbolicExpectedStateV1:
        experiment = context.experiment
        enumeration_fingerprint: str | None
        verified_enumeration = load_optional_symbolic_enumeration_result_historical_verified(
            experiment, context, self._store
        )
        enumeration_fingerprint = (
            None if verified_enumeration is None else verified_enumeration.result.enumeration_result_fingerprint
        )
        plans = tuple(
            sorted(
                self._provenance.iteration_plans_for_experiment_verified(experiment.experiment_fingerprint),
                key=lambda item: item.iteration_index,
            )
        )
        if tuple(item.iteration_index for item in plans) != tuple(range(len(plans))):
            raise OnlySearchProductEffectConflict(experiment.experiment_fingerprint)
        states = []
        research_attempts = 0
        qualification_attempts = 0
        open_count = 0
        for plan in plans:
            verify_symbolic_historical_iteration_occurrence(experiment, plan, context, self._store)
            result = self._provenance.terminal_result_for_plan_verified(plan.iteration_plan_fingerprint)
            if result is None:
                open_count += 1
            else:
                research_attempts += int(result.research_attempted)
                qualification_attempts += int(result.qualification_attempted)
            command_id = symbolic_submission_key(plan)
            receipt = (
                None if self._product_receipts is None else self._product_receipts.load_verified_receipt(command_id)
            )
            if receipt is not None and receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.RESEARCH_RUN:
                raise OnlySearchProductEffectConflict(plan.iteration_plan_fingerprint)
            if receipt is not None:
                if self._research_runs is None or self._product_receipts is None:
                    raise OnlySearchProductEffectConflict(plan.iteration_plan_fingerprint)
                proposal = verify_symbolic_historical_iteration_occurrence(experiment, plan, context, self._store)
                resolved = resolve_symbolic_research_candidate(proposal, self._resolver)
                only_load_search_research_run_exact(
                    command_id=command_id,
                    receipts=self._product_receipts,
                    runs=self._research_runs,
                    expected_specification=resolved.specification,
                )
            states.append(
                OnlySearchPlanExpectedStateV1(
                    plan.iteration_plan_fingerprint,
                    None if result is None else result.iteration_result_fingerprint,
                    None if receipt is None else command_id.value,
                    None if receipt is None else receipt.outcome_ref.outcome_id,
                )
            )
        if open_count > 1 or (open_count and states[-1].result_fingerprint is not None):
            raise OnlySearchProductEffectConflict(experiment.experiment_fingerprint)
        return OnlySymbolicExpectedStateV1(
            experiment.experiment_fingerprint,
            enumeration_fingerprint,
            tuple(states),
            len(states),
            research_attempts,
            qualification_attempts,
            target_plan_fingerprint,
        )

    def assess_effect(
        self,
        context: OnlyVerifiedSymbolicSearchContextV1,
        operation: OnlySearchBoundedOperationV1,
        expected: OnlySymbolicExpectedStateV1,
    ) -> OnlySearchProductEffectStateV1:
        try:
            actual = self.expected_state(
                context,
                target_plan_fingerprint=expected.target_plan_fingerprint,
            )
            if operation is OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE:
                if expected.target_plan_fingerprint is not None or (
                    expected.ordered_plan_states and expected.ordered_plan_states[-1].result_fingerprint is None
                ):
                    raise OnlySearchProductExpectedStateMismatch("open Symbolic Plan requires reconciliation")
                intended = self._intended_plan(context, expected)
                occupant = next(
                    (
                        item
                        for item in self._provenance.iteration_plans_for_experiment_verified(
                            context.experiment.experiment_fingerprint
                        )
                        if item.iteration_index == expected.next_iteration_ordinal
                    ),
                    None,
                )
                if occupant is not None:
                    if occupant != intended:
                        return OnlySearchProductEffectStateV1.CONFLICT_OR_STALE
                    verify_symbolic_historical_iteration_occurrence(context.experiment, occupant, context, self._store)
                    return OnlySearchProductEffectStateV1.COMPLETE_EXACT_EFFECT
                if actual == expected:
                    return OnlySearchProductEffectStateV1.EXACT_PRE_STATE
                if (
                    expected.enumeration_result_fingerprint is None
                    and actual.enumeration_result_fingerprint is not None
                    and actual.next_iteration_ordinal == 0
                ):
                    return OnlySearchProductEffectStateV1.PARTIAL_EXACT_EFFECT
                return OnlySearchProductEffectStateV1.CONFLICT_OR_STALE
            if operation is OnlySearchBoundedOperationV1.RECONCILE_ONE_SYMBOLIC_OCCURRENCE:
                target = expected.target_plan_fingerprint
                if target is None:
                    raise OnlySearchProductExpectedStateMismatch("Symbolic reconcile requires one exact target Plan")
                before = next(
                    (item for item in expected.ordered_plan_states if item.plan_fingerprint == target),
                    None,
                )
                after = next(
                    (item for item in actual.ordered_plan_states if item.plan_fingerprint == target),
                    None,
                )
                if before is None or after is None or before.result_fingerprint is not None:
                    return OnlySearchProductEffectStateV1.CONFLICT_OR_STALE
                if actual == expected:
                    return OnlySearchProductEffectStateV1.EXACT_PRE_STATE
                if after.result_fingerprint is not None or after.research_product_command_id is not None:
                    return OnlySearchProductEffectStateV1.COMPLETE_EXACT_EFFECT
                return OnlySearchProductEffectStateV1.CONFLICT_OR_STALE
        except Exception:
            raise
        return OnlySearchProductEffectStateV1.CONFLICT_OR_STALE

    def advance_one(
        self,
        context: OnlyVerifiedSymbolicSearchContextV1,
        expected: OnlySymbolicExpectedStateV1,
    ) -> OnlySymbolicControllerOutcomeV1:
        if expected.target_plan_fingerprint is not None or (
            expected.ordered_plan_states and expected.ordered_plan_states[-1].result_fingerprint is None
        ):
            raise OnlySearchProductExpectedStateMismatch("open Symbolic Plan requires reconciliation")
        actual = self.expected_state(context)
        intended = self._intended_plan(context, expected)
        if actual == expected:
            return self._commit_exact_occurrence(context, expected, intended)
        occupant = next(
            (
                plan
                for plan in self._provenance.iteration_plans_for_experiment_verified(
                    context.experiment.experiment_fingerprint
                )
                if plan.iteration_index == expected.next_iteration_ordinal
            ),
            None,
        )
        if occupant is not None:
            if occupant != intended:
                raise OnlySearchProductEffectConflict(occupant.iteration_plan_fingerprint)
            verify_symbolic_historical_iteration_occurrence(context.experiment, occupant, context, self._store)
            return OnlySymbolicControllerOutcomeV1(
                occupant,
                self._provenance.terminal_result_for_plan_verified(occupant.iteration_plan_fingerprint),
            )
        if expected.enumeration_result_fingerprint is None and actual.enumeration_result_fingerprint is not None:
            # Enumeration publication is the only valid partial first-occurrence effect.
            if actual.next_iteration_ordinal != 0:
                raise OnlySearchProductEffectConflict(context.experiment.experiment_fingerprint)
            return self._commit_exact_occurrence(context, expected, intended)
        raise OnlySearchProductExpectedStateMismatch(context.experiment.experiment_fingerprint)

    def reconcile_one(
        self,
        context: OnlyVerifiedSymbolicSearchContextV1,
        expected: OnlySymbolicExpectedStateV1,
        *,
        resolver: OnlyResearchSpecificationResolver,
        commands: OnlySymbolicResearchCommandService,
    ) -> OnlySymbolicControllerOutcomeV1:
        target = expected.target_plan_fingerprint
        if target is None:
            raise OnlySearchProductExpectedStateMismatch("Symbolic reconcile requires one exact target Plan")
        actual = self.expected_state(context, target_plan_fingerprint=target)
        plan = next(
            (
                item
                for item in self._provenance.iteration_plans_for_experiment_verified(
                    context.experiment.experiment_fingerprint
                )
                if item.iteration_plan_fingerprint == target
            ),
            None,
        )
        if plan is None:
            raise OnlySearchProductExpectedStateMismatch(target)
        verify_symbolic_historical_iteration_occurrence(context.experiment, plan, context, self._store)
        current_result = self._provenance.terminal_result_for_plan_verified(target)
        expected_target = next(item for item in expected.ordered_plan_states if item.plan_fingerprint == target)
        if expected_target.result_fingerprint is not None:
            raise OnlySearchProductExpectedStateMismatch("Symbolic reconcile target must be open")
        actual_target = next(item for item in actual.ordered_plan_states if item.plan_fingerprint == target)
        if actual != expected:
            # A terminal Result or the stable inner Product receipt is exact monotonic proof of this reconcile effect.
            if current_result is not None or (
                expected_target.research_product_command_id is None
                and actual_target.research_product_command_id == symbolic_submission_key(plan).value
            ):
                return OnlySymbolicControllerOutcomeV1(plan, current_result)
            raise OnlySearchProductExpectedStateMismatch(target)
        if current_result is not None:
            return OnlySymbolicControllerOutcomeV1(plan, current_result)
        if expected.research_attempt_count >= context.experiment.search_budget.research_evaluation_limit:
            raise OnlySearchProductCapabilityUnsupported("Symbolic Research budget is exhausted")
        proposal = verify_symbolic_historical_iteration_occurrence(context.experiment, plan, context, self._store)
        try:
            resolved = resolve_symbolic_research_candidate(proposal, resolver)
        except Exception:
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
            return OnlySymbolicControllerOutcomeV1(plan, result)
        outcome = commands.submit_symbolic_research(plan=plan, resolved=resolved)
        run = outcome.run
        if self._product_receipts is not None and self._research_runs is not None:
            exact_run = only_load_search_research_run_exact(
                command_id=symbolic_submission_key(plan),
                receipts=self._product_receipts,
                runs=self._research_runs,
                expected_specification=resolved.specification,
            )
            if exact_run is None or exact_run != run:
                raise OnlySearchProductEffectConflict(plan.iteration_plan_fingerprint)
        candidate = resolved.candidate.candidate_fingerprint
        if candidate is None:
            raise OnlySearchProductEffectConflict(plan.iteration_plan_fingerprint)
        if run.state in {
            OnlyResearchRunState.QUEUED,
            OnlyResearchRunState.RUNNING,
            OnlyResearchRunState.CANCEL_REQUESTED,
        }:
            return OnlySymbolicControllerOutcomeV1(plan)
        if run.state is OnlyResearchRunState.COMPLETED:
            reference = commands.research_result_reference(outcome=outcome, resolved=resolved)
            result = OnlySearchIterationResultV1(
                plan.iteration_plan_fingerprint,
                candidate,
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
                candidate,
                True,
                None,
                False,
                None,
                OnlySearchIterationDisposition.FAILED,
                OnlySearchFailureCode.RESEARCH_EXECUTION_FAILED,
            )
        else:  # pragma: no cover - enum exhaustiveness
            raise OnlySearchProductEffectConflict(plan.iteration_plan_fingerprint)
        self._provenance.commit_iteration_result(result)
        return OnlySymbolicControllerOutcomeV1(plan, result)

    def apply(
        self,
        context: OnlyVerifiedSymbolicSearchContextV1,
        operation: OnlySearchBoundedOperationV1,
        expected: OnlySymbolicExpectedStateV1,
        *,
        resolver: OnlyResearchSpecificationResolver,
        commands: OnlySymbolicResearchCommandService,
    ) -> OnlySymbolicControllerOutcomeV1:
        if operation is OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE:
            return self.advance_one(context, expected)
        if operation is OnlySearchBoundedOperationV1.RECONCILE_ONE_SYMBOLIC_OCCURRENCE:
            return self.reconcile_one(context, expected, resolver=resolver, commands=commands)
        raise OnlySearchProductExpectedStateMismatch(operation.value)

    def _intended_plan(
        self,
        context: OnlyVerifiedSymbolicSearchContextV1,
        expected: OnlySymbolicExpectedStateV1,
    ) -> OnlySearchIterationPlanV1:
        if expected.enumeration_result_fingerprint is None:
            admit_current_symbolic_algorithm_runtime(context)
            execution = enumerate_symbolic_factor_proposals(
                context.verified_search_space,
                proposal_limit=context.experiment.search_budget.proposal_limit,
            )
            enumeration = build_symbolic_enumeration_result(context.experiment, execution)
        else:
            enumeration = load_symbolic_enumeration_result_historical_verified(
                context.experiment, context, self._store
            ).result
        if expected.enumeration_result_fingerprint is not None and (
            enumeration.enumeration_result_fingerprint != expected.enumeration_result_fingerprint
        ):
            raise OnlySearchProductExpectedStateMismatch(context.experiment.experiment_fingerprint)
        index = expected.next_iteration_ordinal
        if index >= len(enumeration.ordered_proposal_fingerprints):
            raise OnlySearchProductExpectedStateMismatch("Symbolic Enumeration is terminal")
        proposal_fingerprint = enumeration.ordered_proposal_fingerprints[index]
        return OnlySearchIterationPlanV1(
            context.experiment.experiment_fingerprint,
            index,
            SYMBOLIC_PROPOSAL_KIND,
            SYMBOLIC_PROPOSAL_SCHEMA_VERSION,
            proposal_fingerprint,
            (),
            (),
            proposal_fingerprint,
        )

    def _ensure_enumeration(self, context: OnlyVerifiedSymbolicSearchContextV1):  # type: ignore[no-untyped-def]
        admit_current_symbolic_algorithm_runtime(context)
        execution = enumerate_symbolic_factor_proposals(
            context.verified_search_space,
            proposal_limit=context.experiment.search_budget.proposal_limit,
        )
        for proposal in execution.proposals:
            self._store.commit_proposal(proposal)
        result = build_symbolic_enumeration_result(context.experiment, execution)
        commit_symbolic_enumeration_result_verified(result, context, self._store)
        return load_symbolic_enumeration_result_historical_verified(context.experiment, context, self._store).result

    def _commit_exact_occurrence(
        self,
        context: OnlyVerifiedSymbolicSearchContextV1,
        expected: OnlySymbolicExpectedStateV1,
        plan: OnlySearchIterationPlanV1,
    ) -> OnlySymbolicControllerOutcomeV1:
        if expected.enumeration_result_fingerprint is None:
            self._ensure_enumeration(context)
        self._provenance.commit_iteration_plan(plan)
        exact = next(
            item
            for item in self._provenance.iteration_plans_for_experiment_verified(
                context.experiment.experiment_fingerprint
            )
            if item.iteration_index == plan.iteration_index
        )
        if exact != plan:
            raise OnlySearchProductEffectConflict(plan.iteration_plan_fingerprint)
        verify_symbolic_historical_iteration_occurrence(context.experiment, exact, context, self._store)
        return OnlySymbolicControllerOutcomeV1(exact)


def symbolic_submission_key(plan: OnlySearchIterationPlanV1) -> OnlyProductCommandId:
    """Stable UUID4 from the immutable Plan under a Symbolic-only domain."""

    payload = b"ONLYALPHA_SYMBOLIC_PLAN_RESEARCH_COMMAND_V1\x1f" + bytes.fromhex(plan.iteration_plan_fingerprint)
    raw = hashlib.sha256(payload).digest()[:16]
    return OnlyProductCommandId(str(uuid.UUID(bytes=raw, version=4)))


__all__ = [name for name in globals() if name.startswith(("OnlySymbolic", "symbolic_"))]
