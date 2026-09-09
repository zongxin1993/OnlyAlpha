"""Product adapter for ADR 0121 without owning symbolic semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast

from onlyalpha.application.product_command_authority import OnlyProductCommandReceiptAuthority
from onlyalpha.application.search_product import (
    OnlyAdvanceSearchExperimentV1,
    OnlySearchBoundedOperationV1,
    OnlySearchIterationLedgerProjectionV1,
    OnlySearchMethodV1,
    OnlySearchProductCapabilityUnsupported,
    OnlySearchProductEffectConflict,
    OnlySearchProductEffectStateV1,
    OnlySearchProductMethodUnsupported,
    OnlySearchProductSemanticFactCorrupt,
    OnlySearchResearchRunReader,
    OnlySearchSubmitCommandV1,
    OnlySearchTerminalKindV1,
    OnlySearchTerminalProjectionV1,
    OnlySubmitSymbolicSearchExperimentV1,
    OnlySubmitSymbolicSearchExperimentV2,
    OnlySymbolicExpectedStateV1,
    only_search_experiment_work_id,
)
from onlyalpha.research.command.model import OnlyResearchSubmitOutcome
from onlyalpha.research.experiment import (
    OnlySearchAlgorithmBindingV1,
    OnlySearchEvaluationContextReferenceV1,
    OnlySearchExperimentManifestV2,
    OnlySearchRandomnessMode,
    OnlySearchResearchResultReferenceV1,
    OnlySearchSpaceReferenceV1,
)
from onlyalpha.research.experiment.model import OnlySearchExperimentManifest
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver

from .algorithm import OnlySymbolicSearchAlgorithmImplementationManifestV1
from .context import OnlySymbolicSearchContextResolver
from .controller import (
    OnlySymbolicControllerProvenance,
    OnlySymbolicResearchCommandService,
    OnlySymbolicSearchControllerV1,
    symbolic_submission_key,
)
from .evaluation import (
    SYMBOLIC_EVALUATION_CONTRACT_KIND,
    OnlySymbolicResearchEvaluationContractV1,
)
from .execution import OnlyHostedSymbolicGenerationExecutionV1
from .historical import (
    load_optional_symbolic_enumeration_result_historical_verified,
    load_symbolic_enumeration_result_historical_verified,
)
from .integration import OnlySymbolicResolvedResearchCandidateV1
from .model import SYMBOLIC_SEARCH_SPACE_KIND, OnlySymbolicFactorSearchSpaceV2
from .store import OnlyJsonSymbolicSearchStore


class _ResearchSubmitter(Protocol):
    def submit_research_run(
        self,
        submission_key: object,
        specification: object,
        provenance: object | None = None,
        *,
        parent_runtime_work_id: str | None = None,
    ) -> OnlyResearchSubmitOutcome: ...


class OnlySymbolicResearchResultReader(Protocol):
    def load_verified(self, locator_fingerprint: str) -> object: ...


@dataclass(frozen=True, slots=True)
class OnlySymbolicResearchCommandGatewayV1:
    """Normal Research Product Command and exact Result verification gateway."""

    commands: _ResearchSubmitter
    research_results: OnlySymbolicResearchResultReader

    def submit_symbolic_research(
        self,
        *,
        plan: object,
        resolved: OnlySymbolicResolvedResearchCandidateV1,
    ) -> OnlyResearchSubmitOutcome:
        from onlyalpha.research.experiment import OnlySearchIterationPlanV1

        if not isinstance(plan, OnlySearchIterationPlanV1):
            raise OnlySearchProductSemanticFactCorrupt("Symbolic Research Plan is invalid")
        return self.commands.submit_research_run(
            symbolic_submission_key(plan),
            resolved.specification,
            parent_runtime_work_id=only_search_experiment_work_id(plan.experiment_fingerprint),
        )

    def research_result_reference(
        self,
        *,
        outcome: OnlyResearchSubmitOutcome,
        resolved: OnlySymbolicResolvedResearchCandidateV1,
    ) -> OnlySearchResearchResultReferenceV1:
        run = outcome.run
        result_fingerprint = run.research_result_fingerprint
        locator = resolved.resolution.workload.result_plan.fingerprint
        if result_fingerprint is None:
            raise OnlySearchProductSemanticFactCorrupt(run.run_id.value)
        exact = self.research_results.load_verified(locator)
        manifest = getattr(exact, "manifest", None)
        if (
            getattr(manifest, "research_result_plan_fingerprint", None) != locator
            or getattr(manifest, "research_result_fingerprint", None) != result_fingerprint
        ):
            raise OnlySearchProductSemanticFactCorrupt(locator)
        return OnlySearchResearchResultReferenceV1(locator, result_fingerprint)


class OnlySymbolicSearchProductAdapterV1:
    method = OnlySearchMethodV1.SYMBOLIC

    def __init__(
        self,
        *,
        symbolic_store: OnlyJsonSymbolicSearchStore,
        provenance: OnlySymbolicControllerProvenance,
        contexts: OnlySymbolicSearchContextResolver,
        resolver: OnlyResearchSpecificationResolver,
        research_commands: OnlySymbolicResearchCommandService,
        generation_execution: OnlyHostedSymbolicGenerationExecutionV1,
        product_receipts: OnlyProductCommandReceiptAuthority | None = None,
        research_runs: OnlySearchResearchRunReader | None = None,
    ) -> None:
        self._store = symbolic_store
        self._provenance = provenance
        self._contexts = contexts
        self._resolver = resolver
        self._research_commands = research_commands
        if (product_receipts is None) != (research_runs is None):
            raise ValueError("Research Receipt and Run Authorities must be configured together")
        self._product_receipts = product_receipts
        self._research_runs = research_runs
        self._controller = OnlySymbolicSearchControllerV1(
            symbolic_store=symbolic_store,
            provenance=provenance,
            resolver=resolver,
            generation_execution=generation_execution,
            product_receipts=product_receipts,
            research_runs=research_runs,
        )

    def derive_submit_experiment(self, command: OnlySearchSubmitCommandV1) -> OnlySearchExperimentManifestV2:
        if not isinstance(command, (OnlySubmitSymbolicSearchExperimentV1, OnlySubmitSymbolicSearchExperimentV2)):
            raise OnlySearchProductSemanticFactCorrupt("Symbolic Submit command type differs")
        space = command.search_space
        evaluation = command.evaluation_contract
        algorithm = command.algorithm_manifest
        if (
            not isinstance(space, OnlySymbolicFactorSearchSpaceV2)
            or not isinstance(evaluation, OnlySymbolicResearchEvaluationContractV1)
            or not isinstance(algorithm, OnlySymbolicSearchAlgorithmImplementationManifestV1)
        ):
            raise OnlySearchProductSemanticFactCorrupt("Symbolic Submit immutable input type differs")
        if (
            command.workflow_binding.workflow_id != "symbolic.factor.search"
            or command.workflow_binding.workflow_semantic_version != "1"
        ):
            raise OnlySearchProductCapabilityUnsupported(
                "Product-driven Symbolic V1 supports Research Evidence evaluation only"
            )
        if (
            command.catalog_generation_fingerprint != space.catalog_generation_fingerprint
            or command.dataset_snapshot_fingerprint != evaluation.dataset_snapshot_fingerprint
        ):
            raise OnlySearchProductSemanticFactCorrupt("Symbolic Submit context identity differs")
        return OnlySearchExperimentManifestV2(
            command.hypothesis,
            OnlySearchAlgorithmBindingV1(
                algorithm.algorithm_id,
                algorithm.algorithm_semantic_version,
                algorithm.implementation_fingerprint,
                algorithm.source_revision,
            ),
            OnlySearchSpaceReferenceV1(
                SYMBOLIC_SEARCH_SPACE_KIND,
                space.schema_version,
                space.search_space_fingerprint,
            ),
            OnlySearchEvaluationContextReferenceV1(
                SYMBOLIC_EVALUATION_CONTRACT_KIND,
                evaluation.schema_version,
                evaluation.evaluation_contract_fingerprint,
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
    ) -> OnlySearchExperimentManifestV2:
        if not isinstance(
            command, (OnlySubmitSymbolicSearchExperimentV1, OnlySubmitSymbolicSearchExperimentV2)
        ) or not isinstance(experiment, OnlySearchExperimentManifestV2):
            raise OnlySearchProductSemanticFactCorrupt("Symbolic Submit shape differs")
        self._store.commit_search_space(cast(OnlySymbolicFactorSearchSpaceV2, command.search_space))
        self._store.commit_evaluation_contract(
            cast(OnlySymbolicResearchEvaluationContractV1, command.evaluation_contract)
        )
        self._store.commit_algorithm_implementation_manifest(
            cast(OnlySymbolicSearchAlgorithmImplementationManifestV1, command.algorithm_manifest)
        )
        self._provenance.commit_experiment(experiment)  # type: ignore[attr-defined]
        exact = self.load_experiment_verified(experiment.experiment_fingerprint)
        self.verify_submit(command, exact)
        return exact

    def load_experiment_verified(self, experiment_fingerprint: str) -> OnlySearchExperimentManifestV2:
        experiment = self._provenance.load_experiment_verified(experiment_fingerprint)  # type: ignore[attr-defined]
        if not isinstance(experiment, OnlySearchExperimentManifestV2):
            raise OnlySearchProductMethodUnsupported(experiment_fingerprint)
        self._contexts.resolve_verified_context(experiment)
        return experiment

    def verify_submit(
        self,
        command: OnlySearchSubmitCommandV1,
        experiment: OnlySearchExperimentManifestV2 | object,
    ) -> None:
        if not isinstance(experiment, OnlySearchExperimentManifestV2) or experiment != (
            self.derive_submit_experiment(command)
        ):
            raise OnlySearchProductSemanticFactCorrupt(getattr(experiment, "experiment_fingerprint", "unknown"))
        self._contexts.resolve_verified_context(experiment)

    def apply_advance(
        self,
        command: OnlyAdvanceSearchExperimentV1,
        runtime_generation_fingerprint: str,
    ) -> None:
        expected = command.expected_state
        if not isinstance(expected, OnlySymbolicExpectedStateV1):
            raise OnlySearchProductSemanticFactCorrupt(command.experiment_fingerprint)
        experiment = self.load_experiment_verified(command.experiment_fingerprint)
        context = self._contexts.resolve_verified_context(experiment)
        self._controller.apply(
            context,
            command.operation,
            expected,
            resolver=self._resolver,
            commands=self._research_commands,
            runtime_generation_fingerprint=runtime_generation_fingerprint,
        )

    def assess_advance_effect(
        self,
        command: OnlyAdvanceSearchExperimentV1,
        runtime_generation_fingerprint: str,
    ) -> OnlySearchProductEffectStateV1:
        expected = command.expected_state
        if not isinstance(expected, OnlySymbolicExpectedStateV1):
            return OnlySearchProductEffectStateV1.CONFLICT_OR_STALE
        experiment = self.load_experiment_verified(command.experiment_fingerprint)
        context = self._contexts.resolve_verified_context(experiment)
        return self._controller.assess_effect(context, command.operation, expected, runtime_generation_fingerprint)

    def verify_advance_effect(self, command: OnlyAdvanceSearchExperimentV1) -> None:
        expected = command.expected_state
        if not isinstance(expected, OnlySymbolicExpectedStateV1):
            raise OnlySearchProductSemanticFactCorrupt(command.experiment_fingerprint)
        experiment = self.load_experiment_verified(command.experiment_fingerprint)
        context = self._contexts.resolve_verified_context(experiment)
        actual = self._controller.expected_state(
            context,
            target_plan_fingerprint=expected.target_plan_fingerprint,
        )
        if command.operation is OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE:
            if expected.target_plan_fingerprint is not None or (
                expected.ordered_plan_states and expected.ordered_plan_states[-1].result_fingerprint is None
            ):
                raise OnlySearchProductEffectConflict(command.experiment_fingerprint)
            plans = self._provenance.iteration_plans_for_experiment_verified(command.experiment_fingerprint)
            occupant = next(
                (item for item in plans if item.iteration_index == expected.next_iteration_ordinal),
                None,
            )
            if occupant is None:
                raise OnlySearchProductEffectConflict(command.experiment_fingerprint)
            enumeration = load_symbolic_enumeration_result_historical_verified(experiment, context, self._store).result
            if (
                expected.enumeration_result_fingerprint is not None
                and expected.enumeration_result_fingerprint != enumeration.enumeration_result_fingerprint
            ):
                raise OnlySearchProductEffectConflict(enumeration.enumeration_result_fingerprint)
            if (
                expected.next_iteration_ordinal >= len(enumeration.ordered_proposal_fingerprints)
                or occupant.proposal_fingerprint
                != enumeration.ordered_proposal_fingerprints[expected.next_iteration_ordinal]
            ):
                raise OnlySearchProductEffectConflict(occupant.iteration_plan_fingerprint)
            from .historical import verify_symbolic_historical_iteration_occurrence

            verify_symbolic_historical_iteration_occurrence(experiment, occupant, context, self._store)
            return
        if command.operation is OnlySearchBoundedOperationV1.RECONCILE_ONE_SYMBOLIC_OCCURRENCE:
            target = expected.target_plan_fingerprint
            if target is None:
                raise OnlySearchProductEffectConflict(command.experiment_fingerprint)
            expected_target = next(
                (item for item in expected.ordered_plan_states if item.plan_fingerprint == target),
                None,
            )
            actual_target = next(
                (item for item in actual.ordered_plan_states if item.plan_fingerprint == target),
                None,
            )
            if expected_target is None or actual_target is None:
                raise OnlySearchProductEffectConflict(target)
            if expected_target.result_fingerprint is not None:
                raise OnlySearchProductEffectConflict(target)
            if actual_target.result_fingerprint is not None:
                return
            if (
                actual_target.research_product_command_id
                == symbolic_submission_key(
                    next(
                        item
                        for item in self._provenance.iteration_plans_for_experiment_verified(
                            command.experiment_fingerprint
                        )
                        if item.iteration_plan_fingerprint == target
                    )
                ).value
            ):
                return
            raise OnlySearchProductEffectConflict(target)
        raise OnlySearchProductEffectConflict(command.operation.value)

    def ledger(self, experiment_fingerprint: str) -> OnlySearchIterationLedgerProjectionV1:
        experiment = self.load_experiment_verified(experiment_fingerprint)
        context = self._contexts.resolve_verified_context(experiment)
        plans = tuple(
            sorted(
                self._provenance.iteration_plans_for_experiment_verified(experiment_fingerprint),
                key=lambda item: item.iteration_index,
            )
        )
        results = tuple(
            self._provenance.terminal_result_for_plan_verified(item.iteration_plan_fingerprint) for item in plans
        )
        verified_enumeration = load_optional_symbolic_enumeration_result_historical_verified(
            experiment, context, self._store
        )
        enumeration = None if verified_enumeration is None else verified_enumeration.result
        return OnlySearchIterationLedgerProjectionV1(
            self.method,
            experiment_fingerprint,
            plans,
            results,
            self._controller.expected_state(context),
            enumeration_result=enumeration,
        )

    def terminal(self, experiment_fingerprint: str) -> OnlySearchTerminalProjectionV1:
        ledger = self.ledger(experiment_fingerprint)
        enumeration = ledger.enumeration_result
        if enumeration is None or any(item is None for item in ledger.results):
            return OnlySearchTerminalProjectionV1(
                self.method, experiment_fingerprint, OnlySearchTerminalKindV1.NON_TERMINAL
            )
        from .enumeration_result import OnlySymbolicEnumerationResultV1

        if not isinstance(enumeration, OnlySymbolicEnumerationResultV1):
            raise OnlySearchProductSemanticFactCorrupt(experiment_fingerprint)
        if len(ledger.plans) != len(enumeration.ordered_proposal_fingerprints):
            return OnlySearchTerminalProjectionV1(
                self.method, experiment_fingerprint, OnlySearchTerminalKindV1.NON_TERMINAL
            )
        return OnlySearchTerminalProjectionV1(
            self.method,
            experiment_fingerprint,
            OnlySearchTerminalKindV1.TERMINAL_SYMBOLIC_COMPLETION,
            enumeration,
            "SEARCH_SPACE_EXHAUSTED" if enumeration.search_space_exhausted else "PROPOSAL_LIMIT_REACHED",
        )


__all__ = [name for name in globals() if name.startswith("OnlySymbolic")]
