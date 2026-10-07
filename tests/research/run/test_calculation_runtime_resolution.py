from __future__ import annotations

from copy import deepcopy

import pytest

from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendResolver
from onlyalpha.research.run.calculation_resolution import OnlyResearchCalculationRuntimeResolutionV1
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from tests.research.specification.test_calculation_publication import publication_registry, publication_specification


def resolution(spec=None):
    registry = publication_registry()
    spec = publication_specification() if spec is None else spec
    resolved = OnlyResearchSpecificationResolver(registry).resolve(spec)
    job = resolved.workload.direct_jobs[0]
    manifest = (
        OnlyResearchCalculationBackendResolver(registry)
        .resolve_readiness(job.calculation_graph.nodes[0].definition, job.publication)
        .implementation_manifest
    )
    return OnlyResearchCalculationRuntimeResolutionV1(
        "f" * 64,
        spec,
        spec.specification_fingerprint,
        job,
        resolved.workload.result_plan,
        "average",
        resolved.candidates[0].node_fingerprints,
        resolved.research_implementation_bindings,
        manifest,
    )


def test_calculation_runtime_resolution_round_trip():
    proof = resolution()
    assert OnlyResearchCalculationRuntimeResolutionV1.from_dict(proof.to_dict()) == proof


@pytest.mark.parametrize(
    "mutation",
    (
        "whole-context",
        "specification-owner",
        "dataset",
        "job-family",
        "publication",
        "mapping-missing",
        "mapping-duplicate",
        "binding-duplicate",
        "binding-leaf",
        "output",
        "manifest-boolean",
        "manifest-backend",
        "manifest-leaf",
        "manifest-extra",
        "unknown-field",
    ),
)
def test_calculation_runtime_resolution_rejects_structural_mutations(mutation):
    raw = deepcopy(resolution().to_dict())
    if mutation == "whole-context":
        raw = {}
    elif mutation == "specification-owner":
        raw["specification_fingerprint"] = "e" * 64
    elif mutation == "dataset":
        raw["job_plan"]["dataset_snapshot_fingerprint"] = "e" * 64
    elif mutation == "job-family":
        raw["job_plan"]["schema_version"] = 1
    elif mutation == "publication":
        raw["result_plan"]["publication"]["readiness_contract_version"] = True
    elif mutation == "mapping-missing":
        raw["node_fingerprints"] = {}
    elif mutation == "mapping-duplicate":
        raw["node_fingerprints"]["other"] = next(iter(raw["node_fingerprints"].values()))
    elif mutation == "binding-duplicate":
        raw["research_implementation_bindings"] *= 2
    elif mutation == "binding-leaf":
        raw["research_implementation_bindings"][0]["research_implementation_fingerprint"] = "e" * 64
    elif mutation == "output":
        raw["result_plan"]["published_series"][0]["output_name"] = "missing"
    elif mutation == "manifest-boolean":
        raw["implementation_manifest"]["schema_version"] = True
    elif mutation == "manifest-backend":
        raw["implementation_manifest"]["backend_kind"] = "TRADING"
    elif mutation == "manifest-leaf":
        raw["implementation_manifest"]["resources"][0]["byte_sha256"] = "e" * 64
    elif mutation == "manifest-extra":
        raw["implementation_manifest"]["resources"][0]["unknown"] = 1
    else:
        raw["unknown"] = 1
    with pytest.raises((ValueError, RuntimeError)):
        OnlyResearchCalculationRuntimeResolutionV1.from_dict(raw)


def test_complete_different_manifest_family_is_not_an_exact_binding():
    from dataclasses import replace

    from onlyalpha.calculation.definition import OnlyCalculationTypeReference

    proof = resolution()
    other = replace(
        proof.implementation_manifest,
        calculation_type_reference=OnlyCalculationTypeReference(
            proof.implementation_manifest.calculation_type_reference.kind, "onlyalpha.indicator.ema", "1"
        ),
    )
    raw = proof.to_dict()
    raw["implementation_manifest"] = other.to_dict()
    raw["research_implementation_bindings"][0]["research_implementation_fingerprint"] = other.implementation_fingerprint
    with pytest.raises(ValueError, match="family"):
        OnlyResearchCalculationRuntimeResolutionV1.from_dict(raw)


def test_explicit_source_reference_cannot_be_substituted():
    from dataclasses import replace

    from onlyalpha.calculation import OnlyCalculationGraphDefinition, OnlyCalculationNodeDefinition
    from onlyalpha.calculation.definition import OnlyCalculationReference
    from onlyalpha.research.result.plan import OnlyResearchResultCalculationPlan

    proof = resolution()
    node = proof.calculation_graph.nodes[0]
    definition = replace(node.definition, input_bindings={"value": OnlyCalculationReference(None, "value", "bar.open")})
    graph = OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition),))
    job = replace(proof.job_plan, calculation_graph=graph)
    plan = replace(
        proof.result_plan,
        calculations=(OnlyResearchResultCalculationPlan(job.calculation_fingerprint, graph.fingerprint),),
        published_series=(
            replace(
                proof.result_plan.published_series[0],
                calculation_fingerprint=job.calculation_fingerprint,
                node_fingerprint=graph.nodes[0].fingerprint,
            ),
        ),
    )
    with pytest.raises(ValueError, match="source"):
        replace(
            proof,
            job_plan=job,
            result_plan=plan,
            node_fingerprints={"sma": graph.nodes[0].fingerprint},
            research_implementation_bindings=(
                replace(proof.research_implementation_bindings[0], node_fingerprint=graph.nodes[0].fingerprint),
            ),
        )


@pytest.mark.parametrize("mutation", ("dataset", "graph", "job-family", "duplicate-owner", "statistics", "sweeps"))
def test_workload_publication_requires_exact_closure(mutation):
    from dataclasses import replace

    from onlyalpha.research.result.plan import OnlyResearchResultCalculationPlan
    from onlyalpha.research.workload import OnlyResearchWorkloadPlan

    proof = resolution()
    job, plan = proof.job_plan, proof.result_plan
    jobs, statistics, sweeps = (job,), (), ()
    if mutation == "dataset":
        job = replace(job, dataset_snapshot_fingerprint="e" * 64)
        jobs = (job,)
    elif mutation == "graph":
        plan = replace(plan, calculations=(OnlyResearchResultCalculationPlan(job.calculation_fingerprint, "e" * 64),))
    elif mutation == "job-family":
        jobs = (replace(job, schema_version=1, publication=None),)
    elif mutation == "duplicate-owner":
        jobs = (job, job)
    elif mutation == "statistics":
        statistics = (object(),)
    else:
        sweeps = (object(),)
    with pytest.raises(RuntimeError):
        OnlyResearchWorkloadPlan(jobs, sweeps, statistics, plan)


@pytest.mark.parametrize("mutation", ("specification", "generation", "operation"))
def test_hosted_adapter_rejects_complete_alternative_response(mutation):
    from unittest.mock import Mock

    from onlyalpha.application.search_generation_execution import (
        OnlyHistoricalGenerationExecutionMismatch,
        OnlySearchGenerationExecutionResponseV1,
        OnlySearchGenerationOperationV1,
    )
    from onlyalpha.research.run.generation import OnlyResearchHostedRuntimeGenerationResolver

    requested = publication_specification()
    proof = resolution(publication_specification(period=7) if mutation == "specification" else requested)
    operation = OnlySearchGenerationOperationV1.RESOLVE_RESEARCH_CALCULATION_PUBLICATION
    response = OnlySearchGenerationExecutionResponseV1(
        "e" * 64 if mutation == "generation" else "f" * 64,
        OnlySearchGenerationOperationV1.RESOLVE_RESEARCH_ADMISSION if mutation == "operation" else operation,
        proof.to_dict(),
    )
    execution = Mock()
    execution.execute.return_value = response
    adapter = OnlyResearchHostedRuntimeGenerationResolver(execution=execution, dataset_store_root="fixture-datasets")
    with pytest.raises(OnlyHistoricalGenerationExecutionMismatch):
        adapter.resolve_calculation_publication("f" * 64, requested)


@pytest.mark.parametrize("implicit_inputs", (False, True))
def test_canonical_normalization_and_default_sources_survive_dto_and_adapter(implicit_inputs):
    from dataclasses import replace
    from unittest.mock import Mock

    from onlyalpha.application.search_generation_execution import (
        OnlySearchGenerationExecutionResponseV1,
        OnlySearchGenerationOperationV1,
    )
    from onlyalpha.research.run.generation import OnlyResearchHostedRuntimeGenerationResolver
    from onlyalpha.research.specification.model import OnlyResearchCalculationSpec
    from onlyalpha.research.sweep.template import OnlyResearchGraphTemplate

    spec = publication_specification()
    node = spec.calculations[0].graph_template.nodes[0]
    template = OnlyResearchGraphTemplate(
        (
            replace(
                node,
                parameters={"period": 3, "price_field": "close"},
                input_bindings=() if implicit_inputs else node.input_bindings,
            ),
        )
    )
    spec = replace(spec, calculations=(OnlyResearchCalculationSpec("average", template),))
    proof = resolution(spec)
    assert proof.calculation_graph.nodes[0].definition.parameters["price_field"] == "CLOSE"
    assert OnlyResearchCalculationRuntimeResolutionV1.from_dict(proof.to_dict()) == proof
    execution = Mock()
    execution.execute.return_value = OnlySearchGenerationExecutionResponseV1(
        "f" * 64, OnlySearchGenerationOperationV1.RESOLVE_RESEARCH_CALCULATION_PUBLICATION, proof.to_dict()
    )
    adapter = OnlyResearchHostedRuntimeGenerationResolver(execution=execution, dataset_store_root="fixture-datasets")
    assert adapter.resolve_calculation_publication("f" * 64, spec) == proof
