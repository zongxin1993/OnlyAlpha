"""Generation-local worker for the bounded Search Execution V1 contract."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from importlib import metadata
from pathlib import Path
from typing import Any, cast

from onlyalpha.application.search_generation_execution import (
    ONLYALPHA_SEARCH_GENERATION_EXECUTION_CONTRACT_VERSION,
    ONLYALPHA_SEARCH_GENERATION_EXECUTION_SCHEMA_VERSION,
    OnlyHistoricalGenerationCapabilityUnsupported,
    OnlyHistoricalGenerationExecutionError,
    OnlyHistoricalGenerationExecutionMismatch,
    OnlyHistoricalGenerationHostMismatch,
    OnlyHistoricalGenerationProtocolMismatch,
    OnlySearchGenerationExecutionFailureV1,
    OnlySearchGenerationExecutionRequestV1,
    OnlySearchGenerationExecutionResponseV1,
    OnlySearchGenerationOperationV1,
    OnlySearchGenerationWorkerHandshakeV1,
)
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_json
from onlyalpha.quant_assets import only_discover_quant_asset_providers
from onlyalpha.research.calculation.predicate import only_register_research_predicate_primitives
from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.evaluation.summary.scalar import OnlyResearchSummaryScalar
from onlyalpha.research.experiment import OnlySearchExperimentManifestV2, OnlySearchExperimentManifestV3
from onlyalpha.research.search.parameter.algorithm import decide_parameter_search_v1
from onlyalpha.research.search.parameter.context import (
    OnlyParameterSearchContextResolver,
    OnlyVerifiedParameterSearchContextV1,
    admit_current_parameter_algorithm_runtime,
)
from onlyalpha.research.search.parameter.evidence import OnlyParameterResearchEvidenceV1
from onlyalpha.research.search.parameter.model import (
    OnlyParameterFactorSearchSpaceV1,
    OnlyParameterGraphProposalV1,
    OnlyParameterSearchAlgorithmManifestV1,
    OnlyParameterSearchFeedbackDecisionV1,
    OnlyParameterSearchPolicyV1,
    materialize_parameter_proposals,
)
from onlyalpha.research.search.symbolic.algorithm import (
    OnlySymbolicSearchAlgorithmImplementationManifestV1,
)
from onlyalpha.research.search.symbolic.context import (
    OnlyVerifiedSymbolicEvaluationContextV1,
    OnlyVerifiedSymbolicSearchContextV1,
    admit_current_symbolic_algorithm_runtime,
    verify_symbolic_evaluation_context,
)
from onlyalpha.research.search.symbolic.enumeration import enumerate_symbolic_factor_proposals
from onlyalpha.research.search.symbolic.evaluation import OnlySymbolicResearchEvaluationContractV1
from onlyalpha.research.search.symbolic.execution import build_symbolic_enumeration_result
from onlyalpha.research.search.symbolic.materialization import research_specification_from_candidate_graph
from onlyalpha.research.search.symbolic.model import (
    OnlySymbolicFactorSearchSpaceV2,
    OnlySymbolicGraphProposalV1,
)
from onlyalpha.research.search.symbolic.verification import (
    verify_symbolic_experiment_binding,
    verify_symbolic_search_space,
)
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from onlyalpha.runtime.generation import OnlyRuntimeGenerationValidationEvidence

from .hosted import only_verify_hosted_runtime_generation

_CAPABILITIES = (
    OnlySearchGenerationOperationV1.DERIVE_PARAMETER_DECISION,
    OnlySearchGenerationOperationV1.DERIVE_SYMBOLIC_ENUMERATION,
    OnlySearchGenerationOperationV1.RESOLVE_PARAMETER_RESEARCH,
    OnlySearchGenerationOperationV1.RESOLVE_SYMBOLIC_RESEARCH,
)


def main() -> int:
    evidence: OnlyRuntimeGenerationValidationEvidence | None = None
    try:
        bootstrap = _read_json_line()
        _exact(
            bootstrap,
            {"schema_version", "execution_contract_version", "validation_evidence"},
        )
        if (
            bootstrap["schema_version"] != ONLYALPHA_SEARCH_GENERATION_EXECUTION_SCHEMA_VERSION
            or bootstrap["execution_contract_version"] != ONLYALPHA_SEARCH_GENERATION_EXECUTION_CONTRACT_VERSION
        ):
            raise OnlyHistoricalGenerationProtocolMismatch("bootstrap contract differs")
        evidence = OnlyRuntimeGenerationValidationEvidence.from_dict(
            _mapping(bootstrap["validation_evidence"], "validation_evidence")
        )
        only_verify_hosted_runtime_generation(evidence)
        catalog = only_discover_quant_asset_providers()
        if catalog.generation_fingerprint != evidence.catalog_generation_fingerprint:
            raise OnlyHistoricalGenerationHostMismatch("hosted Catalog differs")
        _write(
            OnlySearchGenerationWorkerHandshakeV1(
                evidence.runtime_generation_fingerprint,
                evidence.core_execution_fingerprint,
                catalog.generation_fingerprint,
                evidence.validation_evidence_fingerprint,
                _CAPABILITIES,
            ).to_dict()
        )
    except Exception as exc:
        _write_failure(
            "0" * 64 if evidence is None else evidence.runtime_generation_fingerprint,
            _as_execution_error(exc),
        )
        return 2

    assert evidence is not None
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            raw: Any = json.loads(line)
            request = OnlySearchGenerationExecutionRequestV1.from_dict(_mapping(raw, "request"))
            if request.runtime_generation_fingerprint != evidence.runtime_generation_fingerprint:
                raise OnlyHistoricalGenerationHostMismatch("request names another Runtime Generation")
            result = _execute(request)
            _write(
                OnlySearchGenerationExecutionResponseV1(
                    evidence.runtime_generation_fingerprint,
                    request.operation_kind,
                    result,
                ).to_dict()
            )
        except Exception as exc:
            _write_failure(evidence.runtime_generation_fingerprint, _as_execution_error(exc))
    return 0


def _execute(request: OnlySearchGenerationExecutionRequestV1) -> Mapping[str, object]:
    if request.operation_kind is OnlySearchGenerationOperationV1.DERIVE_SYMBOLIC_ENUMERATION:
        return _derive_symbolic(request.request_payload)
    if request.operation_kind is OnlySearchGenerationOperationV1.DERIVE_PARAMETER_DECISION:
        return _derive_parameter(request.request_payload)
    if request.operation_kind is OnlySearchGenerationOperationV1.RESOLVE_SYMBOLIC_RESEARCH:
        return _resolve_symbolic_research(request.request_payload)
    if request.operation_kind is OnlySearchGenerationOperationV1.RESOLVE_PARAMETER_RESEARCH:
        return _resolve_parameter_research(request.request_payload)
    raise OnlyHistoricalGenerationCapabilityUnsupported(request.operation_kind.value)


def _derive_symbolic(payload: Mapping[str, object]) -> Mapping[str, object]:
    _exact(
        payload,
        {
            "experiment",
            "search_space",
            "evaluation_contract",
            "algorithm_manifest",
            "dataset_store_root",
        },
    )
    experiment = OnlySearchExperimentManifestV2.from_dict(_mapping(payload["experiment"], "experiment"))
    search_space = OnlySymbolicFactorSearchSpaceV2.from_dict(_mapping(payload["search_space"], "search_space"))
    evaluation = OnlySymbolicResearchEvaluationContractV1.from_dict(
        _mapping(payload["evaluation_contract"], "evaluation_contract")
    )
    historical = OnlySymbolicSearchAlgorithmImplementationManifestV1.from_dict(
        _mapping(payload["algorithm_manifest"], "algorithm_manifest")
    )
    catalog = only_discover_quant_asset_providers()
    dataset = OnlyParquetResearchDatasetSnapshotStore(Path(_string(payload, "dataset_store_root"))).load_verified_table(
        experiment.dataset_snapshot_fingerprint
    )
    verify_symbolic_experiment_binding(experiment, search_space)
    verified_space = verify_symbolic_search_space(search_space, catalog, dataset)
    registry = _calculation_registry(catalog.calculation_registry())
    verified_evaluation: OnlyVerifiedSymbolicEvaluationContextV1 = verify_symbolic_evaluation_context(
        evaluation,
        verified_space,
        registry,
    )
    if historical.implementation_fingerprint != experiment.search_algorithm_binding.implementation_fingerprint:
        raise OnlyHistoricalGenerationExecutionMismatch("historical Symbolic Algorithm binding differs")
    context = OnlyVerifiedSymbolicSearchContextV1(
        experiment,
        verified_space,
        verified_evaluation,
        catalog,
        dataset,
        historical,
    )
    runtime = admit_current_symbolic_algorithm_runtime(context)
    execution = enumerate_symbolic_factor_proposals(
        verified_space,
        proposal_limit=experiment.search_budget.proposal_limit,
    )
    enumeration = build_symbolic_enumeration_result(experiment, execution)
    return {
        "algorithm_implementation_fingerprint": runtime.runtime_algorithm_manifest.implementation_fingerprint,
        "catalog_generation_fingerprint": catalog.generation_fingerprint,
        "enumeration_result": enumeration.to_dict(),
        "proposals": [item.to_dict() for item in execution.proposals],
    }


def _derive_parameter(payload: Mapping[str, object]) -> Mapping[str, object]:
    _exact(
        payload,
        {
            "experiment",
            "search_space",
            "evaluation_contract",
            "search_policy",
            "algorithm_manifest",
            "dataset_store_root",
            "evidence",
            "prior_decisions",
        },
    )
    experiment = OnlySearchExperimentManifestV3.from_dict(_mapping(payload["experiment"], "experiment"))
    space = OnlyParameterFactorSearchSpaceV1.from_dict(_mapping(payload["search_space"], "search_space"))
    evaluation = OnlySymbolicResearchEvaluationContractV1.from_dict(
        _mapping(payload["evaluation_contract"], "evaluation_contract")
    )
    policy = OnlyParameterSearchPolicyV1.from_dict(_mapping(payload["search_policy"], "search_policy"))
    historical = OnlyParameterSearchAlgorithmManifestV1.from_dict(
        _mapping(payload["algorithm_manifest"], "algorithm_manifest")
    )
    catalog = only_discover_quant_asset_providers()
    dataset = OnlyParquetResearchDatasetSnapshotStore(Path(_string(payload, "dataset_store_root"))).load_verified_table(
        experiment.dataset_snapshot_fingerprint
    )
    catalog_registry = catalog.calculation_registry()
    registry = _calculation_registry(catalog_registry)
    OnlyParameterSearchContextResolver._verify_bindings(
        experiment,
        space,
        policy,
        historical,
        evaluation,
        catalog,
        dataset,
    )
    OnlyParameterSearchContextResolver._verify_candidate_authority(space, catalog, catalog_registry)
    OnlyResearchSpecificationResolver(registry).verify_deferred_calculation_template(
        dataset_snapshot_fingerprint=evaluation.dataset_snapshot_fingerprint,
        fixed_calculations=evaluation.fixed_calculations,
        statistics=evaluation.statistics,
        evidence=evaluation.evidence,
        deferred_calculation_id=evaluation.candidate_calculation_id,
    )
    proposals = materialize_parameter_proposals(space, registry)
    context = OnlyVerifiedParameterSearchContextV1(
        experiment,
        space,
        policy,
        evaluation,
        catalog,
        dataset,
        historical,
        proposals,
        registry,
    )
    runtime = admit_current_parameter_algorithm_runtime(context)
    evidence = tuple(_parameter_evidence(item, proposals) for item in _array(payload, "evidence"))
    prior = tuple(
        OnlyParameterSearchFeedbackDecisionV1.from_dict(_mapping(item, "prior decision"))
        for item in _array(payload, "prior_decisions")
    )
    decision = decide_parameter_search_v1(
        experiment_fingerprint=experiment.experiment_fingerprint,
        proposals=proposals,
        policy=policy,
        algorithm_implementation_fingerprint=runtime.implementation_fingerprint,
        budget=experiment.search_budget,
        evidence=evidence,
        prior_decisions=prior,
    )
    return {
        "algorithm_implementation_fingerprint": runtime.implementation_fingerprint,
        "catalog_generation_fingerprint": catalog.generation_fingerprint,
        "decision": decision.to_dict(),
        "proposals": [item.to_dict() for item in proposals],
    }


def _parameter_evidence(
    value: object,
    proposals: tuple[OnlyParameterGraphProposalV1, ...],
) -> OnlyParameterResearchEvidenceV1:
    payload = _mapping(value, "evidence")
    _exact(
        payload,
        {
            "iteration_result_fingerprint",
            "proposal_fingerprint",
            "metric_scalars",
            "research_attempted",
            "available",
        },
    )
    proposal_fingerprint = _string(payload, "proposal_fingerprint")
    matches = tuple(item for item in proposals if item.proposal_fingerprint == proposal_fingerprint)
    if len(matches) != 1:
        raise OnlyHistoricalGenerationExecutionMismatch("Parameter Evidence Proposal differs")
    scalars_payload = _mapping(payload["metric_scalars"], "metric_scalars")
    scalars = {
        name: OnlyResearchSummaryScalar.from_dict(_mapping(item, f"metric {name}"))
        for name, item in scalars_payload.items()
    }
    attempted = payload["research_attempted"]
    available = payload["available"]
    if not isinstance(attempted, bool) or not isinstance(available, bool):
        raise OnlyHistoricalGenerationProtocolMismatch("evidence flags must be booleans")
    return OnlyParameterResearchEvidenceV1(
        _string(payload, "iteration_result_fingerprint"),
        matches[0],
        scalars,
        attempted,
        available,
    )


def _resolve_symbolic_research(payload: Mapping[str, object]) -> Mapping[str, object]:
    _exact(payload, {"evaluation_contract", "proposal"})
    evaluation = OnlySymbolicResearchEvaluationContractV1.from_dict(
        _mapping(payload["evaluation_contract"], "evaluation_contract")
    )
    proposal = OnlySymbolicGraphProposalV1.from_dict(_mapping(payload["proposal"], "proposal"))
    return _resolved_research(evaluation, proposal)


def _resolve_parameter_research(payload: Mapping[str, object]) -> Mapping[str, object]:
    _exact(payload, {"evaluation_contract", "proposal"})
    evaluation = OnlySymbolicResearchEvaluationContractV1.from_dict(
        _mapping(payload["evaluation_contract"], "evaluation_contract")
    )
    proposal = OnlyParameterGraphProposalV1.from_dict(_mapping(payload["proposal"], "proposal"))
    return _resolved_research(evaluation, proposal)


def _resolved_research(
    evaluation: OnlySymbolicResearchEvaluationContractV1,
    proposal: OnlySymbolicGraphProposalV1 | OnlyParameterGraphProposalV1,
) -> Mapping[str, object]:
    if isinstance(proposal, OnlySymbolicGraphProposalV1):
        node_fingerprint = proposal.candidate_output_reference.node_fingerprint
        output_name = proposal.candidate_output_reference.output_name
    else:
        node_fingerprint = proposal.candidate_node_fingerprint
        output_name = proposal.candidate_output_name
    materialized = research_specification_from_candidate_graph(
        evaluation,
        proposal.graph,
        node_fingerprint,
        output_name,
    )
    resolution = OnlyResearchSpecificationResolver(
        _calculation_registry(only_discover_quant_asset_providers().calculation_registry())
    ).resolve(materialized.specification)
    candidates = tuple(
        item
        for item in resolution.candidates
        if item.calculation_id == evaluation.candidate_calculation_id
        and item.candidate_fingerprint is not None
        and item.graph_fingerprint == proposal.graph_fingerprint
    )
    if len(candidates) != 1:
        raise OnlyHistoricalGenerationExecutionMismatch("Research Candidate identity differs")
    return {
        "proposal_fingerprint": proposal.proposal_fingerprint,
        "specification": materialized.specification.to_dict(),
        "candidate_fingerprint": candidates[0].candidate_fingerprint,
        "calculation_fingerprint": candidates[0].calculation_fingerprint,
    }


def _calculation_registry(base: OnlyCalculationRegistry) -> OnlyCalculationRegistry:
    for entry in sorted(
        metadata.entry_points().select(group="onlyalpha.calculations"),
        key=lambda item: (item.name, item.value),
    ):
        loaded = entry.load()
        registrations = loaded() if callable(loaded) else tuple(loaded)
        for registration in registrations:
            try:
                base.register(registration)
            except ValueError:
                definition = registration.type_definition
                existing = base.resolve(
                    definition.kind,
                    definition.type_id,
                    definition.semantic_version,
                    registration.backend,
                )
                if (
                    existing.type_definition != registration.type_definition
                    or existing.implementation_manifest != registration.implementation_manifest
                    or existing.state_capability != registration.state_capability
                    or existing.checkpoint_schema_version != registration.checkpoint_schema_version
                ):
                    raise
    only_register_research_predicate_primitives(base)
    return base


def _as_execution_error(exc: Exception) -> OnlyHistoricalGenerationExecutionError:
    if isinstance(exc, OnlyHistoricalGenerationExecutionError):
        return exc
    if isinstance(exc, (KeyError, TypeError, ValueError)):
        return OnlyHistoricalGenerationExecutionMismatch(str(exc))
    if isinstance(exc, RuntimeError) and str(exc) == "RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH":
        return OnlyHistoricalGenerationHostMismatch()
    return OnlyHistoricalGenerationExecutionMismatch(type(exc).__name__)


def _read_json_line() -> Mapping[str, object]:
    line = sys.stdin.readline()
    if not line:
        raise OnlyHistoricalGenerationProtocolMismatch("bootstrap is absent")
    try:
        payload: Any = json.loads(line)
    except json.JSONDecodeError as exc:
        raise OnlyHistoricalGenerationProtocolMismatch("JSON is invalid") from exc
    return _mapping(payload, "protocol line")


def _write(payload: Mapping[str, object]) -> None:
    sys.stdout.write(only_canonical_json(payload) + "\n")
    sys.stdout.flush()


def _write_failure(generation_fingerprint: str, error: OnlyHistoricalGenerationExecutionError) -> None:
    _write(OnlySearchGenerationExecutionFailureV1(generation_fingerprint, error.code, error.detail).to_dict())


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise OnlyHistoricalGenerationProtocolMismatch(f"{name} must be an object")
    return cast(Mapping[str, object], value)


def _exact(payload: Mapping[str, object], expected: set[str]) -> None:
    if set(payload) != expected:
        raise OnlyHistoricalGenerationProtocolMismatch("operation fields differ")


def _string(payload: Mapping[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise OnlyHistoricalGenerationProtocolMismatch(f"{key} must be a string")
    return value


def _array(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload[key]
    if not isinstance(value, list):
        raise OnlyHistoricalGenerationProtocolMismatch(f"{key} must be an array")
    return value


if __name__ == "__main__":  # pragma: no cover - exercised through the hosted process
    raise SystemExit(main())
