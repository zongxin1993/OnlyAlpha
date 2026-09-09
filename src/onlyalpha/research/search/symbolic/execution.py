"""Current-runtime enumeration and reproduction certification boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from onlyalpha.application.product_command_authority import OnlyProductCommandReceiptAuthority
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.application.search_generation_execution import (
    OnlyHistoricalGenerationExecutionMismatch,
    OnlySearchGenerationExecutionPort,
    OnlySearchGenerationExecutionRequestV1,
    OnlySearchGenerationExecutionResponseV1,
    OnlySearchGenerationOperationV1,
)
from onlyalpha.application.search_product import OnlySearchResearchRunReader
from onlyalpha.research.evaluation.plan import OnlyResearchStatisticsPlan
from onlyalpha.research.experiment import OnlySearchExperimentManifestV2, OnlySearchIterationPlanV1
from onlyalpha.research.experiment.store import OnlyHostedSearchAdmission, _hosted_search_admission
from onlyalpha.research.result.plan import OnlyResearchResultPlan
from onlyalpha.research.run.model import OnlyResearchRun
from onlyalpha.research.specification.model import OnlyResearchSpecification

from .context import (
    OnlyExecutableSymbolicSearchContextV1,
    OnlyHistoricalSymbolicSearchFactsV1,
    OnlyVerifiedSymbolicSearchContextV1,
    admit_current_symbolic_algorithm_runtime,
)
from .enumeration import OnlySymbolicEnumerationExecutionV1, enumerate_symbolic_factor_proposals
from .enumeration_result import OnlySymbolicEnumerationResultV1
from .errors import OnlySymbolicSearchError
from .evaluation import OnlySymbolicResearchEvaluationContractV1
from .historical import (
    OnlySymbolicHistoricalStore,
    load_symbolic_enumeration_result_historical_verified,
)
from .model import OnlySymbolicGraphProposalV1


@dataclass(frozen=True, slots=True)
class OnlyHostedResolvedResearchV1:
    """Canonical computation output; no Resolver/Registry/Workload crosses IPC."""

    specification: OnlyResearchSpecification
    proposal_fingerprint: str
    candidate_fingerprint: str
    calculation_fingerprint: str
    result_plan: OnlyResearchResultPlan
    statistics_plans: tuple[OnlyResearchStatisticsPlan, ...]

    @property
    def research_result_plan_fingerprint(self) -> str:
        return self.result_plan.fingerprint


def verify_hosted_specification_binding(
    specification: OnlyResearchSpecification, evaluation: OnlySymbolicResearchEvaluationContractV1, proposal: object
) -> None:
    """Compare canonical authored fields; never resolve or materialize a Graph."""
    candidate_id = evaluation.candidate_calculation_id
    candidates = tuple(item for item in specification.calculations if item.calculation_id == candidate_id)
    graph = getattr(proposal, "graph", None)
    candidate_ref = getattr(proposal, "candidate_output_reference", None)
    node_fingerprint = getattr(candidate_ref, "node_fingerprint", getattr(proposal, "candidate_node_fingerprint", None))
    output_name = getattr(candidate_ref, "output_name", getattr(proposal, "candidate_output_name", None))
    if (
        specification.schema_version != evaluation.research_specification_schema_version
        or specification.dataset_snapshot_fingerprint != evaluation.dataset_snapshot_fingerprint
        or tuple(item for item in specification.calculations if item.calculation_id != candidate_id)
        != evaluation.fixed_calculations
        or len(candidates) != 1
        or candidates[0].sweep_dimensions
        or graph is None
    ):
        raise OnlyHistoricalGenerationExecutionMismatch("Research fixed input binding differs")
    nodes = {item.template_node_id: item for item in candidates[0].graph_template.nodes}
    if len(nodes) != len(graph.nodes):
        raise OnlyHistoricalGenerationExecutionMismatch("Research Proposal nodes differ")
    # Template IDs are local authoring names, not historical executable identity.
    # Match the two data graphs by declared inputs, without rematerializing nodes.
    node_mapping: dict[str | None, str] = {}
    remaining = dict(nodes)
    while remaining:
        progress = False
        for identifier, actual_node in tuple(remaining.items()):
            bindings = {item.input_name: item.reference for item in actual_node.input_bindings}
            if any(
                ref.template_node_id is not None and ref.template_node_id not in node_mapping
                for ref in bindings.values()
            ):
                continue
            matches = []
            for node in graph.nodes:
                definition = node.definition
                if node.fingerprint in node_mapping.values():
                    continue
                if (
                    actual_node.type_reference.kind,
                    actual_node.type_reference.type_id,
                    actual_node.type_reference.semantic_version,
                ) != (definition.kind, definition.type_id, definition.semantic_version):
                    continue
                if dict(actual_node.parameters) != dict(definition.parameters) or set(bindings) != set(
                    definition.input_bindings
                ):
                    continue
                if all(
                    (
                        node_mapping.get(bindings[name].template_node_id),
                        bindings[name].output_name,
                        bindings[name].source,
                    )
                    == (ref.node_fingerprint, ref.output_name, ref.source)
                    for name, ref in definition.input_bindings.items()
                ):
                    matches.append(node.fingerprint)
            if len(matches) != 1:
                raise OnlyHistoricalGenerationExecutionMismatch(
                    "Research Proposal node binding is ambiguous or different"
                )
            node_mapping[identifier] = matches[0]
            del remaining[identifier]
            progress = True
        if not progress:
            raise OnlyHistoricalGenerationExecutionMismatch("Research Proposal dependency binding differs")

    def selector_matches(actual: object, fixed: object) -> bool:
        if fixed is None or getattr(fixed, "calculation_id", None) != candidate_id:
            return actual == fixed
        return (
            getattr(actual, "calculation_id", None) == candidate_id
            and node_mapping.get(getattr(actual, "template_node_id", None)) == node_fingerprint
            and getattr(actual, "output_name", None) == output_name
        )

    if len(specification.statistics) != len(evaluation.statistics):
        raise OnlyHistoricalGenerationExecutionMismatch("Research Statistics membership differs")
    for actual_statistics, fixed in zip(specification.statistics, evaluation.statistics, strict=True):
        if (
            actual_statistics.definition != fixed.definition
            or actual_statistics.expansion != fixed.expansion
            or not selector_matches(actual_statistics.feature, fixed.feature)
            or not selector_matches(actual_statistics.target, fixed.target)
        ):
            raise OnlyHistoricalGenerationExecutionMismatch("Research Statistics binding differs")
    actual_evidence = specification.evidence
    fixed_evidence = evaluation.evidence
    if (
        actual_evidence is None
        or actual_evidence.candidate_calculation_id != candidate_id
        or len(actual_evidence.published_series) != len(fixed_evidence.published_series)
    ):
        raise OnlyHistoricalGenerationExecutionMismatch("Research Evidence membership differs")
    if not all(
        selector_matches(a, b)
        for a, b in zip(actual_evidence.published_series, fixed_evidence.published_series, strict=True)
    ) or not all(
        selector_matches(getattr(actual_evidence.signals, role), getattr(fixed_evidence.signals, role))
        for role in ("eligibility", "entry", "exit")
    ):
        raise OnlyHistoricalGenerationExecutionMismatch("Research Evidence selectors differ")


def decode_hosted_research(
    payload: Mapping[str, object], evaluation: OnlySymbolicResearchEvaluationContractV1, proposal: object
) -> OnlyHostedResolvedResearchV1:
    if set(payload) != {
        "proposal_fingerprint",
        "specification",
        "candidate_fingerprint",
        "calculation_fingerprint",
        "result_plan",
        "statistics_plans",
    }:
        raise OnlyHistoricalGenerationExecutionMismatch("Research resolution fields differ")

    def mapping(value: object) -> Mapping[str, object]:
        if not isinstance(value, Mapping):
            raise OnlyHistoricalGenerationExecutionMismatch("Research resolution shape differs")
        return cast(Mapping[str, object], value)

    specification = OnlyResearchSpecification.from_dict(mapping(payload["specification"]))
    verify_hosted_specification_binding(specification, evaluation, proposal)
    result_plan = OnlyResearchResultPlan.from_dict(mapping(payload["result_plan"]))
    raw_statistics = payload["statistics_plans"]
    if not isinstance(raw_statistics, list):
        raise OnlyHistoricalGenerationExecutionMismatch("Statistics shape differs")
    statistics = tuple(OnlyResearchStatisticsPlan.from_dict(mapping(item)) for item in raw_statistics)
    candidate = payload["candidate_fingerprint"]
    calculation = payload["calculation_fingerprint"]
    for value in (candidate, calculation, payload["proposal_fingerprint"]):
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise OnlyHistoricalGenerationExecutionMismatch("Research fingerprint differs")
    matches = tuple(item for item in result_plan.candidates if item.candidate_fingerprint == candidate)
    if (
        payload["proposal_fingerprint"] != getattr(proposal, "proposal_fingerprint", None)
        or specification.dataset_snapshot_fingerprint != evaluation.dataset_snapshot_fingerprint
        or result_plan.dataset_snapshot_fingerprint != evaluation.dataset_snapshot_fingerprint
        or len(matches) != 1
        or matches[0].calculation_fingerprint != calculation
        or matches[0].graph_fingerprint != getattr(proposal, "graph_fingerprint", None)
        or set(item.statistics_fingerprint for item in statistics) != set(result_plan.statistics_fingerprints)
    ):
        raise OnlyHistoricalGenerationExecutionMismatch("Research resolution identity differs")
    return OnlyHostedResolvedResearchV1(
        specification,
        cast(str, payload["proposal_fingerprint"]),
        cast(str, candidate),
        calculation,
        result_plan,
        statistics,
    )


def load_hosted_research_run_historical(
    *,
    plan: OnlySearchIterationPlanV1,
    command_id: OnlyProductCommandId,
    receipts: OnlyProductCommandReceiptAuthority,
    runs: OnlySearchResearchRunReader,
    evaluation: OnlySymbolicResearchEvaluationContractV1,
    proposal: object,
) -> OnlyResearchRun | None:
    """Verify existing Product/Run intent without recomputing a Resolver result."""
    from onlyalpha.application.search_product import only_load_search_research_run_exact, only_search_experiment_work_id
    from onlyalpha.research.command.model import OnlyDerivedResearchSubmitCommandV2, only_derived_research_run_id

    run = only_load_search_research_run_exact(command_id=command_id, receipts=receipts, runs=runs)
    if run is None:
        return None
    specification = run.specification
    verify_hosted_specification_binding(specification, evaluation, proposal)
    command = OnlyDerivedResearchSubmitCommandV2(
        command_id,
        specification,
        only_search_experiment_work_id(plan.experiment_fingerprint),
        run.authoring_provenance,
    )
    receipt = receipts.load_verified_receipt(command_id)
    if (
        receipt is None
        or receipt.command_fingerprint != command.command_fingerprint
        or run.run_id != only_derived_research_run_id(command_id)
        or specification.dataset_snapshot_fingerprint != evaluation.dataset_snapshot_fingerprint
        or plan.proposal_fingerprint != getattr(proposal, "proposal_fingerprint", None)
        or tuple(
            item for item in specification.calculations if item.calculation_id != evaluation.candidate_calculation_id
        )
        != evaluation.fixed_calculations
    ):
        raise OnlyHistoricalGenerationExecutionMismatch("historical Research intent differs")
    return run


@dataclass(frozen=True, slots=True)
class OnlyHostedSymbolicGenerationExecutionV1:
    execution: OnlySearchGenerationExecutionPort
    dataset_store_root: Path

    def admit_experiment(
        self, runtime_generation_fingerprint: str, context: OnlyHistoricalSymbolicSearchFactsV1
    ) -> OnlyHostedSearchAdmission:
        self.derive_enumeration(runtime_generation_fingerprint, context)
        return _hosted_search_admission(context.experiment.experiment_fingerprint, runtime_generation_fingerprint)

    def derive_enumeration(
        self,
        runtime_generation_fingerprint: str,
        context: OnlyVerifiedSymbolicSearchContextV1 | OnlyHistoricalSymbolicSearchFactsV1,
    ) -> tuple[OnlySymbolicEnumerationExecutionV1, OnlySymbolicEnumerationResultV1]:
        request = OnlySearchGenerationExecutionRequestV1(
            runtime_generation_fingerprint,
            OnlySearchGenerationOperationV1.DERIVE_SYMBOLIC_ENUMERATION,
            {
                "experiment": context.experiment.to_dict(),
                "search_space": (
                    context.search_space
                    if isinstance(context, OnlyHistoricalSymbolicSearchFactsV1)
                    else context.verified_search_space.search_space
                ).to_dict(),
                "evaluation_contract": context.evaluation_contract.to_dict(),
                "algorithm_manifest": context.historical_algorithm_manifest.to_dict(),
                "dataset_store_root": str(self.dataset_store_root.resolve()),
            },
        )
        response = OnlySearchGenerationExecutionResponseV1.from_dict(self.execution.execute(request).to_dict())
        if (
            response.runtime_generation_fingerprint != runtime_generation_fingerprint
            or response.operation_kind != request.operation_kind
        ):
            raise OnlyHistoricalGenerationExecutionMismatch("Symbolic response envelope differs")
        payload = response.result_payload
        expected = {
            "algorithm_implementation_fingerprint",
            "catalog_generation_fingerprint",
            "enumeration_result",
            "proposals",
        }
        if set(payload) != expected:
            raise OnlyHistoricalGenerationExecutionMismatch("Symbolic result fields differ")
        proposals_raw = payload["proposals"]
        enumeration_raw = payload["enumeration_result"]
        if not isinstance(proposals_raw, list) or not isinstance(enumeration_raw, Mapping):
            raise OnlyHistoricalGenerationExecutionMismatch("Symbolic result shape differs")
        proposals = tuple(
            OnlySymbolicGraphProposalV1.from_dict(cast(Mapping[str, object], item))
            for item in proposals_raw
            if isinstance(item, Mapping)
        )
        if len(proposals) != len(proposals_raw):
            raise OnlyHistoricalGenerationExecutionMismatch("Symbolic Proposal shape differs")
        result = OnlySymbolicEnumerationResultV1.from_dict(cast(Mapping[str, object], enumeration_raw))
        if (
            payload["algorithm_implementation_fingerprint"]
            != context.historical_algorithm_manifest.implementation_fingerprint
            or payload["catalog_generation_fingerprint"] != context.experiment.catalog_generation_fingerprint
            or result.experiment_fingerprint != context.experiment.experiment_fingerprint
            or result.algorithm_implementation_fingerprint
            != context.historical_algorithm_manifest.implementation_fingerprint
            or result.search_space_fingerprint != context.experiment.search_space_reference.search_space_fingerprint
            or result.proposal_limit != context.experiment.search_budget.proposal_limit
            or any(item.search_space_fingerprint != result.search_space_fingerprint for item in proposals)
            or result.ordered_proposal_fingerprints != tuple(item.proposal_fingerprint for item in proposals)
        ):
            raise OnlyHistoricalGenerationExecutionMismatch("Symbolic execution identity differs")
        return (
            OnlySymbolicEnumerationExecutionV1(
                proposals=proposals,
                search_space_exhausted=result.search_space_exhausted,
                proposal_limit_reached=result.proposal_limit_reached,
            ),
            result,
        )

    def derive_verified_enumeration(
        self, runtime_generation_fingerprint: str, context: OnlyHistoricalSymbolicSearchFactsV1
    ) -> tuple[OnlySymbolicEnumerationExecutionV1, OnlySymbolicEnumerationResultV1, OnlyHostedSearchAdmission]:
        execution, result = self.derive_enumeration(runtime_generation_fingerprint, context)
        return (
            execution,
            result,
            _hosted_search_admission(
                context.experiment.experiment_fingerprint,
                runtime_generation_fingerprint,
                result.enumeration_result_fingerprint,
            ),
        )

    def resolve_research(
        self,
        runtime_generation_fingerprint: str,
        context: OnlyVerifiedSymbolicSearchContextV1 | OnlyHistoricalSymbolicSearchFactsV1,
        proposal: OnlySymbolicGraphProposalV1,
    ) -> OnlyHostedResolvedResearchV1:
        response = self.execution.execute(
            OnlySearchGenerationExecutionRequestV1(
                runtime_generation_fingerprint,
                OnlySearchGenerationOperationV1.RESOLVE_SYMBOLIC_RESEARCH,
                {
                    "evaluation_contract": context.evaluation_contract.to_dict(),
                    "proposal": proposal.to_dict(),
                },
            )
        )
        response = OnlySearchGenerationExecutionResponseV1.from_dict(response.to_dict())
        if (
            response.runtime_generation_fingerprint != runtime_generation_fingerprint
            or response.operation_kind is not OnlySearchGenerationOperationV1.RESOLVE_SYMBOLIC_RESEARCH
        ):
            raise OnlyHistoricalGenerationExecutionMismatch("Research response envelope differs")
        return decode_hosted_research(response.result_payload, context.evaluation_contract, proposal)


def build_symbolic_enumeration_result(
    experiment: OnlySearchExperimentManifestV2,
    execution: OnlySymbolicEnumerationExecutionV1,
) -> OnlySymbolicEnumerationResultV1:
    return OnlySymbolicEnumerationResultV1(
        experiment.experiment_fingerprint,
        experiment.search_algorithm_binding.implementation_fingerprint,
        experiment.search_space_reference.search_space_fingerprint,
        experiment.search_budget.proposal_limit,
        tuple(item.proposal_fingerprint for item in execution.proposals),
        execution.proposal_limit_reached,
        execution.search_space_exhausted,
    )


def enumerate_symbolic_executable_context(
    executable: OnlyExecutableSymbolicSearchContextV1,
) -> tuple[OnlySymbolicEnumerationExecutionV1, OnlySymbolicEnumerationResultV1]:
    context = executable.historical_context
    execution = enumerate_symbolic_factor_proposals(
        context.verified_search_space,
        proposal_limit=context.experiment.search_budget.proposal_limit,
    )
    return execution, build_symbolic_enumeration_result(context.experiment, execution)


def certify_symbolic_enumeration_reproduction(
    context: OnlyVerifiedSymbolicSearchContextV1,
    store: OnlySymbolicHistoricalStore,
) -> OnlySymbolicEnumerationResultV1:
    """Admit current code, re-enumerate, and require equality with durable history."""

    executable = admit_current_symbolic_algorithm_runtime(context)
    _execution, reproduced = enumerate_symbolic_executable_context(executable)
    stored = load_symbolic_enumeration_result_historical_verified(context.experiment, context, store).result
    if reproduced != stored:
        raise OnlySymbolicSearchError("SEARCH_ENUMERATION_REPRODUCTION_MISMATCH", stored.enumeration_result_fingerprint)
    return reproduced


__all__ = [name for name in globals() if name.startswith(("Only", "build_", "certify_", "enumerate_"))]
