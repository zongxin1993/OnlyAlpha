"""Runtime attestation is bound before execution, not attached to public rows."""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from onlyalpha.research.calculation.errors import OnlyResearchCalculationError
from onlyalpha.research.calculation.execution import _only_require_verified_research_calculation_execution_v2
from onlyalpha.research.calculation.execution_evidence_v2 import OnlyResearchCalculationExecutionEvidenceStoreV2
from onlyalpha.research.calculation.execution_provenance import (
    OnlyResearchRuntimeExecutionProvenanceV1,
    _only_issue_research_runtime_execution_context,
    _only_require_research_runtime_execution_context,
)
from tests.research.calculation.test_execution_readiness_v2 import PUBLICATION
from tests.research.calculation.test_result_v2_store import _case


def _context(executor, graph, generation="a"):
    bindings = executor.plan(graph).implementation_bindings
    return _only_issue_research_runtime_execution_context(
        OnlyResearchRuntimeExecutionProvenanceV1(generation * 64, "b" * 64, "c" * 64, "d" * 64),
        graph.fingerprint,
        tuple((item.node_fingerprint, item.research_implementation_fingerprint) for item in bindings),
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "copy",
        "replace",
        "graph",
        "binding",
        "binding_list",
        "provenance",
        "equal_provenance",
        "nested",
        "complete_different",
    ),
)
def test_context_rejects_copy_replacement_and_in_place_mutation(tmp_path, mutation):
    executor, _, graph, _ = _case(tmp_path)
    context = _context(executor, graph)
    if mutation == "copy":
        context = copy.copy(context)
    elif mutation == "replace":
        context = replace(context)
    elif mutation == "graph":
        object.__setattr__(context, "graph_fingerprint", "f" * 64)
    elif mutation == "binding":
        object.__setattr__(context, "implementation_bindings", (("e" * 64, "f" * 64),))
    elif mutation == "binding_list":
        object.__setattr__(context, "implementation_bindings", list(context.implementation_bindings))
    elif mutation == "provenance":
        object.__setattr__(context, "provenance", None)
    elif mutation == "nested":
        object.__setattr__(context.provenance, "core_execution_fingerprint", "f" * 64)
    elif mutation == "equal_provenance":
        object.__setattr__(context, "provenance", replace(context.provenance))
    else:
        object.__setattr__(context, "provenance", _context(executor, graph, "e").provenance)
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_PUBLICATION_UNAUTHORIZED"):
        _only_require_research_runtime_execution_context(context, graph.fingerprint)


@pytest.mark.parametrize(
    "mutation",
    (
        "copy",
        "replace",
        "detach",
        "replace_context",
        "projection",
        "nested_context",
        "attach_after",
        "equal_execution",
        "output_list",
        "binding_list",
        "equal_publication",
    ),
)
def test_native_execution_rejects_changed_context_and_projection(tmp_path, mutation):
    executor, store, graph, diagnostic = _case(tmp_path)
    context = _context(executor, graph)
    seal = executor._execute_verified_v2(
        diagnostic.execution.dataset_snapshot_fingerprint,
        graph,
        PUBLICATION,
        runtime_context=context,
    )
    if mutation == "copy":
        seal = copy.copy(seal)
    elif mutation == "replace":
        seal = replace(seal)
    elif mutation == "detach":
        object.__setattr__(seal, "runtime_context", None)
    elif mutation == "replace_context":
        object.__setattr__(seal, "runtime_context", _context(executor, graph))
    elif mutation == "projection":
        object.__setattr__(seal.execution, "dataset_snapshot_fingerprint", "e" * 64)
    elif mutation == "nested_context":
        object.__setattr__(context.provenance, "catalog_generation_fingerprint", "e" * 64)
    elif mutation == "equal_execution":
        object.__setattr__(seal, "execution", replace(seal.execution))
    elif mutation == "output_list":
        object.__setattr__(seal.execution, "outputs", list(seal.execution.outputs))
    elif mutation == "binding_list":
        object.__setattr__(
            seal.execution, "research_implementation_bindings", list(seal.execution.research_implementation_bindings)
        )
    elif mutation == "equal_publication":
        object.__setattr__(seal.execution, "publication", replace(seal.execution.publication))
    else:
        seal = diagnostic
        object.__setattr__(seal, "runtime_context", context)
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_EXECUTION_PUBLICATION_UNAUTHORIZED"):
        _only_require_verified_research_calculation_execution_v2(seal)
    assert not (tmp_path / "results").exists()


def test_actual_context_seal_publishes_exact_provenance_and_legacy_omits_it(tmp_path):
    executor, store, graph, diagnostic = _case(tmp_path)
    context = _context(executor, graph)
    seal = executor._execute_verified_v2(
        diagnostic.execution.dataset_snapshot_fingerprint,
        graph,
        PUBLICATION,
        runtime_context=context,
    )
    result = store.commit(seal, graph)
    root = tmp_path / "semantic"
    root.mkdir()
    evidence = OnlyResearchCalculationExecutionEvidenceStoreV2(root, store)
    selected = evidence._publish_verified(seal, result)
    assert selected.runtime_execution_provenance == context.provenance
    assert (
        evidence.require_exact_for_result(
            result,
            seal.execution.research_implementation_bindings,
            context.provenance,
        )
        == selected
    )
    old = evidence._publish_verified(diagnostic, result)
    assert "runtime_execution_provenance" not in old.to_dict()
    assert selected.evidence_fingerprint != old.evidence_fingerprint
    assert selected.calculation_result_fingerprint == old.calculation_result_fingerprint
    with pytest.raises(OnlyResearchCalculationError, match="incomplete"):
        evidence.require_exact_for_result(
            result, seal.execution.research_implementation_bindings, _context(executor, graph, "e").provenance
        )


@pytest.mark.parametrize("mutation", ("null", "bool_version", "unknown", "missing", "uppercase"))
def test_provenance_parser_rejects_incomplete_and_noncanonical_proof(mutation):
    payload = OnlyResearchRuntimeExecutionProvenanceV1("a" * 64, "b" * 64, "c" * 64, "d" * 64).to_dict()
    if mutation == "null":
        payload = None
    elif mutation == "bool_version":
        payload["schema_version"] = True
    elif mutation == "unknown":
        payload["unknown"] = "x"
    elif mutation == "missing":
        del payload["validation_evidence_fingerprint"]
    else:
        payload["runtime_generation_fingerprint"] = "A" * 64
    with pytest.raises(ValueError):
        OnlyResearchRuntimeExecutionProvenanceV1.from_dict(payload)


@pytest.mark.parametrize("proof", ("missing_authoring", "complete_different_authoring"))
def test_exact_runtime_reuse_requires_complete_mandatory_authoring_proof(tmp_path, proof):
    from onlyalpha.research.job import OnlyResearchJobDisposition, OnlyResearchJobError, OnlyResearchJobExecutor
    from tests.research.job.support import readiness_job_case

    plan, executor, legacy, results, evidence = readiness_job_case(tmp_path)
    context = _context(executor, plan.calculation_graph)
    first = OnlyResearchJobExecutor(
        executor,
        legacy,
        legacy._test_execution_evidence_store,
        None if proof == "missing_authoring" else "e" * 64,
        readiness_result_store=results,
        readiness_execution_evidence_store=evidence,
        runtime_execution_context=context,
    ).execute(plan)
    calls = []

    class TrappedExecutor:
        def _execute_verified_v2(self, *args, **kwargs):
            calls.append(1)
            return executor._execute_verified_v2(*args, **kwargs)

    second = OnlyResearchJobExecutor(
        TrappedExecutor(),
        legacy,
        legacy._test_execution_evidence_store,
        "f" * 64,
        readiness_result_store=results,
        readiness_execution_evidence_store=evidence,
        runtime_execution_context=context,
    )
    if proof == "missing_authoring":
        with pytest.raises(OnlyResearchJobError, match="incomplete"):
            second.execute(plan)
        assert calls == []
    else:
        outcome = second.execute(plan)
        assert calls == [1]
        assert outcome.disposition is OnlyResearchJobDisposition.EXECUTED
        assert outcome.calculation_result_fingerprint == first.calculation_result_fingerprint
        assert outcome.calculation_execution_evidence_fingerprint != first.calculation_execution_evidence_fingerprint
