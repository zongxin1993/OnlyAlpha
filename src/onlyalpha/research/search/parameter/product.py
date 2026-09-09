"""Product adapter for ADR 0122 without owning adaptive decisions."""

from __future__ import annotations

from typing import Protocol, cast

from onlyalpha.application.product_command_authority import OnlyProductCommandReceiptAuthority
from onlyalpha.application.product_command_receipt import OnlyProductCommandOutcomeKind
from onlyalpha.application.search_product import (
    OnlyAdvanceSearchExperimentV1,
    OnlyParameterExpectedStateV1,
    OnlySearchBoundedOperationV1,
    OnlySearchIterationLedgerProjectionV1,
    OnlySearchMethodV1,
    OnlySearchPlanExpectedStateV1,
    OnlySearchProductEffectConflict,
    OnlySearchProductEffectStateV1,
    OnlySearchProductExpectedStateMismatch,
    OnlySearchProductMethodUnsupported,
    OnlySearchProductSemanticFactCorrupt,
    OnlySearchResearchRunReader,
    OnlySearchSubmitCommandV1,
    OnlySearchTerminalKindV1,
    OnlySearchTerminalProjectionV1,
    OnlySubmitParameterSearchExperimentV1,
    OnlySubmitParameterSearchExperimentV2,
    only_load_search_research_run_exact,
)
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.research.experiment import (
    OnlySearchAlgorithmBindingV1,
    OnlySearchEvaluationContextReferenceV1,
    OnlySearchExperimentManifestV3,
    OnlySearchIterationPlanV1,
    OnlySearchPolicyReferenceV1,
    OnlySearchRandomnessMode,
    OnlySearchSpaceReferenceV1,
)
from onlyalpha.research.experiment.model import OnlySearchExperimentManifest
from onlyalpha.research.search.symbolic.evaluation import (
    SYMBOLIC_EVALUATION_CONTRACT_KIND,
    OnlySymbolicResearchEvaluationContractV1,
)
from onlyalpha.research.search.symbolic.store import OnlyJsonSymbolicSearchStore
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver

from .context import OnlyParameterSearchContextResolver, OnlyVerifiedParameterSearchContextV1
from .controller import OnlyParameterControllerProvenance, OnlyParameterSearchControllerV1
from .evidence import OnlyParameterResearchEvidenceReader
from .integration import (
    OnlyParameterResearchCommandService,
    commit_feedback_plan_batch,
    parameter_submission_key,
    plans_for_feedback_decision,
    resolve_parameter_research_candidate,
)
from .model import (
    PARAMETER_SEARCH_POLICY_KIND,
    PARAMETER_SEARCH_SPACE_KIND,
    OnlyParameterFactorSearchSpaceV1,
    OnlyParameterFeedbackDecisionKind,
    OnlyParameterSearchAlgorithmManifestV1,
    OnlyParameterSearchFeedbackDecisionV1,
    OnlyParameterSearchPolicyV1,
    materialize_parameter_proposals,
)
from .store import OnlyJsonParameterSearchStore


class _ParameterProvenance(OnlyParameterControllerProvenance, Protocol):
    def commit_experiment(self, value: OnlySearchExperimentManifestV3) -> object: ...

    def load_experiment_verified(self, fingerprint: str) -> object: ...


class OnlyParameterSearchProductAdapterV1:
    method = OnlySearchMethodV1.PARAMETER

    def __init__(
        self,
        *,
        parameter_store: OnlyJsonParameterSearchStore,
        evaluation_store: OnlyJsonSymbolicSearchStore,
        provenance: _ParameterProvenance,
        contexts: OnlyParameterSearchContextResolver,
        calculation_registry: OnlyCalculationRegistry,
        evidence_reader: OnlyParameterResearchEvidenceReader,
        resolver: OnlyResearchSpecificationResolver,
        research_commands: OnlyParameterResearchCommandService,
        product_receipts: OnlyProductCommandReceiptAuthority | None = None,
        research_runs: OnlySearchResearchRunReader | None = None,
    ) -> None:
        self._store = parameter_store
        self._evaluations = evaluation_store
        self._provenance = provenance
        self._contexts = contexts
        self._registry = calculation_registry
        self._evidence_reader = evidence_reader
        self._resolver = resolver
        self._research_commands = research_commands
        if (product_receipts is None) != (research_runs is None):
            raise ValueError("Research Receipt and Run Authorities must be configured together")
        self._product_receipts = product_receipts
        self._research_runs = research_runs
        self._controller = OnlyParameterSearchControllerV1(
            parameter_store=parameter_store,
            provenance=provenance,
            evidence_reader=evidence_reader,
        )

    def derive_submit_experiment(self, command: OnlySearchSubmitCommandV1) -> OnlySearchExperimentManifestV3:
        if not isinstance(command, (OnlySubmitParameterSearchExperimentV1, OnlySubmitParameterSearchExperimentV2)):
            raise OnlySearchProductSemanticFactCorrupt("Parameter Submit command type differs")
        space = command.search_space
        evaluation = command.evaluation_contract
        policy = command.search_policy
        algorithm = command.algorithm_manifest
        if (
            not isinstance(space, OnlyParameterFactorSearchSpaceV1)
            or not isinstance(evaluation, OnlySymbolicResearchEvaluationContractV1)
            or not isinstance(policy, OnlyParameterSearchPolicyV1)
            or not isinstance(algorithm, OnlyParameterSearchAlgorithmManifestV1)
        ):
            raise OnlySearchProductSemanticFactCorrupt("Parameter Submit immutable input type differs")
        if (
            command.catalog_generation_fingerprint != space.catalog_generation_fingerprint
            or command.dataset_snapshot_fingerprint != evaluation.dataset_snapshot_fingerprint
            or command.dataset_snapshot_fingerprint != space.sweep_definition.dataset_snapshot_fingerprint
        ):
            raise OnlySearchProductSemanticFactCorrupt("Parameter Submit context identity differs")
        return OnlySearchExperimentManifestV3(
            command.hypothesis,
            OnlySearchAlgorithmBindingV1(
                algorithm.algorithm_id,
                algorithm.algorithm_semantic_version,
                algorithm.implementation_fingerprint,
                algorithm.source_revision,
            ),
            OnlySearchSpaceReferenceV1(
                PARAMETER_SEARCH_SPACE_KIND,
                space.schema_version,
                space.search_space_fingerprint,
            ),
            OnlySearchEvaluationContextReferenceV1(
                SYMBOLIC_EVALUATION_CONTRACT_KIND,
                evaluation.schema_version,
                evaluation.evaluation_contract_fingerprint,
            ),
            OnlySearchPolicyReferenceV1(
                PARAMETER_SEARCH_POLICY_KIND,
                policy.schema_version,
                policy.policy_fingerprint,
            ),
            OnlySearchRandomnessMode.NONE,
            None,
            command.search_budget,
            command.catalog_generation_fingerprint,
            command.dataset_snapshot_fingerprint,
            command.workflow_binding,
            command.decision_engine_binding,
            command.parent_experiment_fingerprint,
        )

    def commit_submit(
        self,
        command: OnlySearchSubmitCommandV1,
        experiment: OnlySearchExperimentManifest,
    ) -> OnlySearchExperimentManifestV3:
        if not isinstance(
            command, (OnlySubmitParameterSearchExperimentV1, OnlySubmitParameterSearchExperimentV2)
        ) or not isinstance(experiment, OnlySearchExperimentManifestV3):
            raise OnlySearchProductSemanticFactCorrupt("Parameter Submit shape differs")
        space = cast(OnlyParameterFactorSearchSpaceV1, command.search_space)
        self._store.commit_search_space(space)
        self._store.commit_policy(cast(OnlyParameterSearchPolicyV1, command.search_policy))
        self._store.commit_algorithm_manifest(cast(OnlyParameterSearchAlgorithmManifestV1, command.algorithm_manifest))
        self._evaluations.commit_evaluation_contract(
            cast(OnlySymbolicResearchEvaluationContractV1, command.evaluation_contract)
        )
        for proposal in materialize_parameter_proposals(space, self._registry):
            self._store.commit_proposal(proposal)
        self._provenance.commit_experiment(experiment)
        exact = self.load_experiment_verified(experiment.experiment_fingerprint)
        self.verify_submit(command, exact)
        return exact

    def load_experiment_verified(self, experiment_fingerprint: str) -> OnlySearchExperimentManifestV3:
        experiment = self._provenance.load_experiment_verified(experiment_fingerprint)
        if not isinstance(experiment, OnlySearchExperimentManifestV3):
            raise OnlySearchProductMethodUnsupported(experiment_fingerprint)
        self._contexts.resolve_verified_context(experiment)
        return experiment

    def verify_submit(self, command: OnlySearchSubmitCommandV1, experiment: object) -> None:
        if not isinstance(experiment, OnlySearchExperimentManifestV3) or experiment != (
            self.derive_submit_experiment(command)
        ):
            raise OnlySearchProductSemanticFactCorrupt(getattr(experiment, "experiment_fingerprint", "unknown"))
        self._contexts.resolve_verified_context(experiment)

    def expected_state(self, experiment_fingerprint: str) -> OnlyParameterExpectedStateV1:
        experiment = self.load_experiment_verified(experiment_fingerprint)
        context = self._contexts.resolve_verified_context(experiment)
        plans = tuple(
            sorted(
                self._provenance.iteration_plans_for_experiment_verified(experiment_fingerprint),
                key=lambda item: item.iteration_index,
            )
        )
        if tuple(item.iteration_index for item in plans) != tuple(range(len(plans))):
            raise OnlySearchProductEffectConflict(experiment_fingerprint)
        decision_ids: list[str] = []
        for plan in plans:
            if not decision_ids or decision_ids[-1] != plan.decision_output_fingerprint:
                decision_ids.append(plan.decision_output_fingerprint)
        frontier = self._store.load_frontier_fingerprint(experiment_fingerprint)
        if frontier is not None and (not decision_ids or decision_ids[-1] != frontier):
            decision_ids.append(frontier)
        self._historical_decision_chain(context, plans, tuple(decision_ids), frontier)
        frontier_plans = tuple(item for item in plans if item.decision_output_fingerprint == frontier)
        states = []
        research_attempts = 0
        qualification_attempts = 0
        for plan in plans:
            result = self._provenance.terminal_result_for_plan_verified(plan.iteration_plan_fingerprint)
            if result is not None:
                research_attempts += int(result.research_attempted)
                qualification_attempts += int(result.qualification_attempted)
            if plan not in frontier_plans:
                continue
            command_id = parameter_submission_key(plan)
            receipt = (
                None if self._product_receipts is None else self._product_receipts.load_verified_receipt(command_id)
            )
            if receipt is not None and receipt.outcome_ref.kind is not OnlyProductCommandOutcomeKind.RESEARCH_RUN:
                raise OnlySearchProductEffectConflict(plan.iteration_plan_fingerprint)
            if receipt is not None:
                if self._research_runs is None or self._product_receipts is None:
                    raise OnlySearchProductEffectConflict(plan.iteration_plan_fingerprint)
                proposal = next(
                    (item for item in context.proposals if item.proposal_fingerprint == plan.proposal_fingerprint),
                    None,
                )
                if proposal is None:
                    raise OnlySearchProductEffectConflict(plan.iteration_plan_fingerprint)
                resolved = resolve_parameter_research_candidate(context, proposal, self._resolver)
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
        return OnlyParameterExpectedStateV1(
            experiment_fingerprint,
            frontier,
            tuple(decision_ids),
            tuple(states),
            len(plans),
            research_attempts,
            qualification_attempts,
        )

    def _historical_decision_chain(
        self,
        context: OnlyVerifiedParameterSearchContextV1,
        plans: tuple[OnlySearchIterationPlanV1, ...],
        decision_ids: tuple[str, ...],
        frontier: str | None,
    ) -> tuple[OnlyParameterSearchFeedbackDecisionV1, ...]:
        """Verify immutable Decision lineage without current-runtime admission."""

        decisions = tuple(self._store.load_feedback_decision_intrinsic_verified(item) for item in decision_ids)
        prior_plans: list[OnlySearchIterationPlanV1] = []
        by_index = {item.iteration_index: item for item in plans}
        for position, decision in enumerate(decisions):
            if (
                decision.experiment_fingerprint != context.experiment.experiment_fingerprint
                or decision.search_policy_fingerprint != context.policy.policy_fingerprint
                or decision.algorithm_implementation_fingerprint
                != context.historical_algorithm_manifest.implementation_fingerprint
                or decision.start_iteration_index != len(prior_plans)
            ):
                raise OnlySearchProductEffectConflict(decision.feedback_decision_fingerprint)
            input_results = []
            for plan in prior_plans:
                terminal = self._provenance.terminal_result_for_plan_verified(plan.iteration_plan_fingerprint)
                if terminal is None:
                    raise OnlySearchProductEffectConflict(plan.iteration_plan_fingerprint)
                input_results.append(terminal.iteration_result_fingerprint)
            if decision.ordered_input_iteration_result_fingerprints != tuple(input_results):
                raise OnlySearchProductEffectConflict(decision.feedback_decision_fingerprint)
            exact_batch = plans_for_feedback_decision(decision, context.proposals)
            for plan in exact_batch:
                occupant = by_index.get(plan.iteration_index)
                if occupant is not None and occupant != plan:
                    raise OnlySearchProductEffectConflict(plan.iteration_plan_fingerprint)
                if occupant is None and (
                    position != len(decisions) - 1 or frontier != decision.feedback_decision_fingerprint
                ):
                    raise OnlySearchProductEffectConflict(plan.iteration_plan_fingerprint)
            prior_plans.extend(exact_batch)
        return decisions

    def apply_advance(self, command: OnlyAdvanceSearchExperimentV1) -> None:
        expected = command.expected_state
        if not isinstance(expected, OnlyParameterExpectedStateV1):
            raise OnlySearchProductSemanticFactCorrupt(command.experiment_fingerprint)
        experiment = self.load_experiment_verified(command.experiment_fingerprint)
        context = self._contexts.resolve_verified_context(experiment)
        actual = self.expected_state(command.experiment_fingerprint)
        if command.operation is OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION:
            if any(item.result_fingerprint is None for item in expected.frontier_plan_states):
                raise OnlySearchProductExpectedStateMismatch("open Parameter batch requires reconciliation")
            self._advance_or_recover(context, expected, actual)
            return
        if command.operation is OnlySearchBoundedOperationV1.RECONCILE_OPEN_PARAMETER_BATCH:
            if not expected.frontier_plan_states or all(
                item.result_fingerprint is not None for item in expected.frontier_plan_states
            ):
                raise OnlySearchProductExpectedStateMismatch("Parameter reconcile requires an open Plan")
            self._reconcile_or_recover(context, expected, actual)
            return
        raise OnlySearchProductExpectedStateMismatch(command.operation.value)

    def assess_advance_effect(self, command: OnlyAdvanceSearchExperimentV1) -> OnlySearchProductEffectStateV1:
        expected = command.expected_state
        if not isinstance(expected, OnlyParameterExpectedStateV1):
            return OnlySearchProductEffectStateV1.CONFLICT_OR_STALE
        actual = self.expected_state(command.experiment_fingerprint)
        if command.operation is OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION:
            if any(item.result_fingerprint is None for item in expected.frontier_plan_states):
                raise OnlySearchProductExpectedStateMismatch("open Parameter batch requires reconciliation")
            if actual == expected:
                return OnlySearchProductEffectStateV1.EXACT_PRE_STATE
            decisions = actual.ordered_feedback_decision_fingerprints
            prefix = expected.ordered_feedback_decision_fingerprints
            if decisions[: len(prefix)] != prefix or len(decisions) <= len(prefix):
                return OnlySearchProductEffectStateV1.CONFLICT_OR_STALE
            effect = self._store.load_feedback_decision_intrinsic_verified(decisions[len(prefix)])
            context = self._contexts.resolve_verified_context(
                self.load_experiment_verified(command.experiment_fingerprint)
            )
            if (
                effect.experiment_fingerprint != command.experiment_fingerprint
                or effect.start_iteration_index != expected.proposal_count
            ):
                return OnlySearchProductEffectStateV1.CONFLICT_OR_STALE
            exact_plans = plans_for_feedback_decision(effect, context.proposals)
            committed = {
                item.iteration_plan_fingerprint
                for item in self._provenance.iteration_plans_for_experiment_verified(command.experiment_fingerprint)
            }
            present = sum(item.iteration_plan_fingerprint in committed for item in exact_plans)
            if present == len(exact_plans):
                return OnlySearchProductEffectStateV1.COMPLETE_EXACT_EFFECT
            if len(decisions) == len(prefix) + 1:
                return OnlySearchProductEffectStateV1.PARTIAL_EXACT_EFFECT
            return OnlySearchProductEffectStateV1.CONFLICT_OR_STALE
        if command.operation is OnlySearchBoundedOperationV1.RECONCILE_OPEN_PARAMETER_BATCH:
            if not expected.frontier_plan_states or all(
                item.result_fingerprint is not None for item in expected.frontier_plan_states
            ):
                raise OnlySearchProductExpectedStateMismatch("Parameter reconcile requires an open Plan")
            if actual == expected:
                return OnlySearchProductEffectStateV1.EXACT_PRE_STATE
            prefix = expected.ordered_feedback_decision_fingerprints
            if actual.ordered_feedback_decision_fingerprints[: len(prefix)] != prefix:
                return OnlySearchProductEffectStateV1.CONFLICT_OR_STALE
            actual_by_plan = {item.plan_fingerprint: item for item in actual.frontier_plan_states}
            witnessed = 0
            unchanged = 0
            for before in expected.frontier_plan_states:
                if before.result_fingerprint is not None:
                    continue
                after = actual_by_plan.get(before.plan_fingerprint)
                if after is None:
                    if self._provenance.terminal_result_for_plan_verified(before.plan_fingerprint) is None:
                        return OnlySearchProductEffectStateV1.CONFLICT_OR_STALE
                    witnessed += 1
                elif after == before:
                    unchanged += 1
                elif after.result_fingerprint is not None or after.research_product_command_id is not None:
                    witnessed += 1
                else:
                    return OnlySearchProductEffectStateV1.CONFLICT_OR_STALE
            if witnessed and not unchanged:
                return OnlySearchProductEffectStateV1.COMPLETE_EXACT_EFFECT
            if witnessed:
                return OnlySearchProductEffectStateV1.PARTIAL_EXACT_EFFECT
            return OnlySearchProductEffectStateV1.CONFLICT_OR_STALE
        return OnlySearchProductEffectStateV1.CONFLICT_OR_STALE

    def verify_advance_effect(self, command: OnlyAdvanceSearchExperimentV1) -> None:
        expected = command.expected_state
        if not isinstance(expected, OnlyParameterExpectedStateV1):
            raise OnlySearchProductSemanticFactCorrupt(command.experiment_fingerprint)
        actual = self.expected_state(command.experiment_fingerprint)
        if command.operation is OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION:
            if any(item.result_fingerprint is None for item in expected.frontier_plan_states):
                raise OnlySearchProductEffectConflict(command.experiment_fingerprint)
            decisions = actual.ordered_feedback_decision_fingerprints
            prefix = expected.ordered_feedback_decision_fingerprints
            if decisions[: len(prefix)] != prefix or len(decisions) <= len(prefix):
                raise OnlySearchProductEffectConflict(command.experiment_fingerprint)
            effect = self._store.load_feedback_decision_intrinsic_verified(decisions[len(prefix)])
            context = self._contexts.resolve_verified_context(
                self.load_experiment_verified(command.experiment_fingerprint)
            )
            exact_plans = plans_for_feedback_decision(effect, context.proposals)
            committed = {
                item.iteration_plan_fingerprint
                for item in self._provenance.iteration_plans_for_experiment_verified(command.experiment_fingerprint)
            }
            if effect.start_iteration_index != expected.proposal_count or any(
                item.iteration_plan_fingerprint not in committed for item in exact_plans
            ):
                raise OnlySearchProductEffectConflict(effect.feedback_decision_fingerprint)
            return
        if command.operation is OnlySearchBoundedOperationV1.RECONCILE_OPEN_PARAMETER_BATCH:
            if not expected.frontier_plan_states or all(
                item.result_fingerprint is not None for item in expected.frontier_plan_states
            ):
                raise OnlySearchProductEffectConflict(command.experiment_fingerprint)
            expected_plans = {item.plan_fingerprint: item for item in expected.frontier_plan_states}
            actual_plans = {item.plan_fingerprint: item for item in actual.frontier_plan_states}
            for fingerprint, before in expected_plans.items():
                after = actual_plans.get(fingerprint)
                if after is None:
                    if self._provenance.terminal_result_for_plan_verified(fingerprint) is None:
                        raise OnlySearchProductEffectConflict(fingerprint)
                elif after == before or (
                    after.result_fingerprint is None and after.research_product_command_id is None
                ):
                    raise OnlySearchProductEffectConflict(fingerprint)
            return
        raise OnlySearchProductEffectConflict(command.operation.value)

    def _advance_or_recover(self, context, expected, actual) -> None:  # type: ignore[no-untyped-def]
        if actual == expected:
            self._controller.advance(context)
            return
        decisions = actual.ordered_feedback_decision_fingerprints
        prefix = expected.ordered_feedback_decision_fingerprints
        if decisions[: len(prefix)] != prefix or len(decisions) <= len(prefix):
            raise OnlySearchProductExpectedStateMismatch(context.experiment.experiment_fingerprint)
        effect_fingerprint = decisions[len(prefix)]
        effect = self._store.load_feedback_decision_intrinsic_verified(effect_fingerprint)
        if (
            effect.experiment_fingerprint != context.experiment.experiment_fingerprint
            or effect.start_iteration_index != expected.proposal_count
        ):
            raise OnlySearchProductEffectConflict(effect_fingerprint)
        exact_plans = plans_for_feedback_decision(effect, context.proposals)
        committed = {
            item.iteration_plan_fingerprint: item
            for item in self._provenance.iteration_plans_for_experiment_verified(
                context.experiment.experiment_fingerprint
            )
        }
        for plan in exact_plans:
            occupant = next(
                (item for item in committed.values() if item.iteration_index == plan.iteration_index),
                None,
            )
            if occupant is not None and occupant != plan:
                raise OnlySearchProductEffectConflict(plan.iteration_plan_fingerprint)
        if len(decisions) == len(prefix) + 1:
            # Complete only this already committed Decision's frozen batch.
            commit_feedback_plan_batch(effect, context.proposals, self._provenance)
        elif any(plan.iteration_plan_fingerprint not in committed for plan in exact_plans):
            raise OnlySearchProductEffectConflict(effect_fingerprint)

    def _reconcile_or_recover(self, context, expected, actual) -> None:  # type: ignore[no-untyped-def]
        if expected.frontier_fingerprint is None:
            raise OnlySearchProductExpectedStateMismatch("Parameter reconcile requires a frontier")
        if actual == expected:
            self._controller.reconcile_open_plans(
                context,
                resolver=self._resolver,
                commands=self._research_commands,
            )
            return
        if actual.ordered_feedback_decision_fingerprints[: len(expected.ordered_feedback_decision_fingerprints)] != (
            expected.ordered_feedback_decision_fingerprints
        ):
            raise OnlySearchProductEffectConflict(expected.frontier_fingerprint)
        actual_by_plan = {item.plan_fingerprint: item for item in actual.frontier_plan_states}
        for item in expected.frontier_plan_states:
            observed = actual_by_plan.get(item.plan_fingerprint)
            if observed is None:
                # A later frontier is legal only after every old Plan became terminal.
                terminal = self._provenance.terminal_result_for_plan_verified(item.plan_fingerprint)
                if terminal is None:
                    raise OnlySearchProductEffectConflict(item.plan_fingerprint)
                continue
            if observed == item:
                continue
            if observed.result_fingerprint is None and observed.research_product_command_id is None:
                raise OnlySearchProductEffectConflict(item.plan_fingerprint)
        if actual.frontier_fingerprint == expected.frontier_fingerprint:
            # A partial Research batch is completed/replayed through the same Plan identities only.
            self._controller.reconcile_open_plans(
                context,
                resolver=self._resolver,
                commands=self._research_commands,
            )

    def ledger(self, experiment_fingerprint: str) -> OnlySearchIterationLedgerProjectionV1:
        state = self.expected_state(experiment_fingerprint)
        plans = tuple(
            sorted(
                self._provenance.iteration_plans_for_experiment_verified(experiment_fingerprint),
                key=lambda item: item.iteration_index,
            )
        )
        results = tuple(
            self._provenance.terminal_result_for_plan_verified(item.iteration_plan_fingerprint) for item in plans
        )
        decisions = tuple(
            self._store.load_feedback_decision_intrinsic_verified(item)
            for item in state.ordered_feedback_decision_fingerprints
        )
        return OnlySearchIterationLedgerProjectionV1(
            self.method,
            experiment_fingerprint,
            plans,
            results,
            state,
            feedback_decisions=decisions,
            frontier_fingerprint=state.frontier_fingerprint,
        )

    def terminal(self, experiment_fingerprint: str) -> OnlySearchTerminalProjectionV1:
        state = self.expected_state(experiment_fingerprint)
        if state.frontier_fingerprint is None:
            return OnlySearchTerminalProjectionV1(
                self.method, experiment_fingerprint, OnlySearchTerminalKindV1.NON_TERMINAL
            )
        decision = self._store.load_feedback_decision_intrinsic_verified(state.frontier_fingerprint)
        if decision.decision_kind is not OnlyParameterFeedbackDecisionKind.STOP:
            return OnlySearchTerminalProjectionV1(
                self.method, experiment_fingerprint, OnlySearchTerminalKindV1.NON_TERMINAL
            )
        if decision.stop_reason is None:
            raise OnlySearchProductSemanticFactCorrupt(decision.feedback_decision_fingerprint)
        return OnlySearchTerminalProjectionV1(
            self.method,
            experiment_fingerprint,
            OnlySearchTerminalKindV1.TERMINAL_PARAMETER_STOP,
            decision,
            decision.stop_reason.value,
        )


__all__ = [name for name in globals() if name.startswith("OnlyParameter")]
