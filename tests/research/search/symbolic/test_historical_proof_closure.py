from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, replace

import pytest
from onlyalpha_plugin_targets.registration import registrations as target_registrations

from onlyalpha.canonical import only_canonical_json
from onlyalpha.quant_assets import OnlyQuantAssetCatalogManager
from onlyalpha.research.experiment import (
    OnlyJsonSearchProvenanceStore,
    OnlySearchFailureCode,
    OnlySearchIterationDisposition,
    OnlySearchIterationResultV1,
    OnlySearchProvenanceStoreError,
    OnlySearchResearchResultReferenceV1,
)
from onlyalpha.research.search.symbolic import (
    OnlyJsonSymbolicSearchStore,
    OnlySymbolicEnumerationResultV1,
    OnlySymbolicGraphProposalV1,
    OnlySymbolicSearchError,
    OnlySymbolicSearchStoreError,
    build_symbolic_enumeration_result,
    commit_symbolic_enumeration_result_verified,
    enumerate_symbolic_factor_proposals,
    resolve_symbolic_research_candidate,
    run_symbolic_search_workflow,
    verify_symbolic_proposal_reconstruction,
)
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver

from .support import space
from .test_final_closure import _plan
from .test_research_and_provenance_integration import _Datasets, _verified_context


@dataclass(frozen=True)
class _Candidate:
    candidate_fingerprint: str


class _Candidates:
    def __init__(self, *fingerprints: str) -> None:
        self._fingerprints = frozenset(fingerprints)

    def load_verified(self, fingerprint: str) -> _Candidate:
        if fingerprint not in self._fingerprints:
            raise KeyError(fingerprint)
        return _Candidate(fingerprint)


@dataclass(frozen=True)
class _ResearchPlan:
    candidates: tuple[_Candidate, ...]


@dataclass(frozen=True)
class _ResearchManifest:
    research_result_plan_fingerprint: str
    research_result_fingerprint: str
    dataset_snapshot_fingerprint: str
    plan: _ResearchPlan


@dataclass(frozen=True)
class _ResearchResult:
    manifest: _ResearchManifest


class _ResearchResults:
    def __init__(self, reference: OnlySearchResearchResultReferenceV1, candidate: str, dataset: str) -> None:
        self._reference = reference
        self._value = _ResearchResult(
            _ResearchManifest(
                reference.locator_fingerprint,
                reference.result_fingerprint,
                dataset,
                _ResearchPlan((_Candidate(candidate),)),
            )
        )

    def load_verified(self, fingerprint: str) -> _ResearchResult:
        if fingerprint != self._reference.locator_fingerprint:
            raise KeyError(fingerprint)
        return self._value


def _enumeration_path(root, experiment_fingerprint: str):  # type: ignore[no-untyped-def]
    return (
        root
        / "research"
        / "symbolic-search"
        / "enumeration-results"
        / "sha256"
        / experiment_fingerprint[:2]
        / experiment_fingerprint
        / "manifest.json"
    )


def _provenance(root, generation, resolver):  # type: ignore[no-untyped-def]
    return OnlyJsonSearchProvenanceStore(
        root,
        catalogs=OnlyQuantAssetCatalogManager(generation),
        datasets=_Datasets("a" * 64),
        search_contexts=resolver,
    )


def test_enumeration_result_identity_is_complete_deterministic_and_fresh_process_stable(tmp_path) -> None:
    generation, search_space = space(max_nodes=2)
    store, experiment, context, _resolver = _verified_context(tmp_path, generation, search_space, "a" * 64)
    value = store.load_enumeration_result_verified(experiment.experiment_fingerprint)
    assert OnlySymbolicEnumerationResultV1.from_dict(value.to_dict()) == value
    assert value.experiment_fingerprint != value.enumeration_result_fingerprint
    assert replace(value).enumeration_result_fingerprint == value.enumeration_result_fingerprint
    assert (
        replace(value, experiment_fingerprint="b" * 64).enumeration_result_fingerprint
        != value.enumeration_result_fingerprint
    )
    assert (
        replace(value, algorithm_implementation_fingerprint="c" * 64).enumeration_result_fingerprint
        != value.enumeration_result_fingerprint
    )
    assert (
        replace(value, search_space_fingerprint="d" * 64).enumeration_result_fingerprint
        != value.enumeration_result_fingerprint
    )
    if len(value.ordered_proposal_fingerprints) >= 2:
        swapped = (
            value.ordered_proposal_fingerprints[1],
            value.ordered_proposal_fingerprints[0],
            *value.ordered_proposal_fingerprints[2:],
        )
        assert replace(value, ordered_proposal_fingerprints=swapped).enumeration_result_fingerprint != (
            value.enumeration_result_fingerprint
        )
    artificial = OnlySymbolicEnumerationResultV1(
        "1" * 64,
        "2" * 64,
        "3" * 64,
        2,
        ("4" * 64,),
        False,
        True,
    )
    assert replace(artificial, proposal_limit=3).enumeration_result_fingerprint != (
        artificial.enumeration_result_fingerprint
    )
    limited = OnlySymbolicEnumerationResultV1(
        "1" * 64,
        "2" * 64,
        "3" * 64,
        1,
        ("4" * 64,),
        True,
        False,
    )
    assert replace(limited, search_space_exhausted=True).enumeration_result_fingerprint != (
        limited.enumeration_result_fingerprint
    )
    payload = only_canonical_json(value.to_dict())
    program = (
        "import json,sys; "
        "from onlyalpha.research.search.symbolic import OnlySymbolicEnumerationResultV1; "
        "print(OnlySymbolicEnumerationResultV1.from_dict(json.loads(sys.argv[1])).enumeration_result_fingerprint)"
    )
    assert subprocess.check_output([sys.executable, "-c", program, payload], text=True).strip() == (
        value.enumeration_result_fingerprint
    )


def test_enumeration_result_store_is_put_once_and_fail_closed(tmp_path) -> None:
    generation, search_space = space(max_nodes=2)
    store, experiment, context, context_resolver = _verified_context(
        tmp_path / "put-once", generation, search_space, "a" * 64
    )
    value = store.load_enumeration_result_verified(experiment.experiment_fingerprint)
    assert store.commit_enumeration_result(value, context=context).disposition.value == "REUSED"
    assert store.commit_enumeration_result(value, context=context).fingerprint == value.enumeration_result_fingerprint
    swapped = replace(
        value,
        ordered_proposal_fingerprints=tuple(reversed(value.ordered_proposal_fingerprints)),
    )
    if swapped != value:
        with pytest.raises(OnlySymbolicSearchStoreError, match="SEARCH_ENUMERATION_RESULT_CONFLICT"):
            store.commit_enumeration_result(swapped, context=context)
    new_experiment = replace(
        experiment,
        search_budget=replace(experiment.search_budget, proposal_limit=2),
    )
    new_context = context_resolver.resolve_verified_context(new_experiment)
    new_execution = enumerate_symbolic_factor_proposals(
        new_context.verified_search_space,
        proposal_limit=new_experiment.search_budget.proposal_limit,
    )
    for proposal in new_execution.proposals:
        store.commit_proposal(proposal)
    created = commit_symbolic_enumeration_result_verified(
        build_symbolic_enumeration_result(new_experiment, new_execution),
        new_context,
        store,
    )
    assert created.disposition.value == "CREATED"
    with pytest.raises(OnlySymbolicSearchStoreError, match="SEARCH_ENUMERATION_RESULT_NOT_FOUND"):
        OnlyJsonSymbolicSearchStore(tmp_path / "missing").load_enumeration_result_verified("f" * 64)

    for mutation in ("corrupt", "noncanonical", "path", "schema"):
        name = mutation
        root = tmp_path / name
        local, local_experiment, _local_context, _local_resolver = _verified_context(
            root, generation, search_space, "a" * 64
        )
        path = _enumeration_path(root, local_experiment.experiment_fingerprint)
        payload = json.loads(path.read_text())
        if mutation == "corrupt":
            payload["enumeration_result_fingerprint"] = "0" * 64
            path.write_text(only_canonical_json(payload))
        elif mutation == "noncanonical":
            path.write_text(path.read_text() + "\n")
        elif mutation == "path":
            moved = OnlySymbolicEnumerationResultV1.from_dict(payload)
            payload = replace(moved, experiment_fingerprint="e" * 64).to_dict()
            path.write_text(only_canonical_json(payload))
        else:
            payload["schema_version"] = 999
            path.write_text(only_canonical_json(payload))
        with pytest.raises(OnlySymbolicSearchStoreError, match="SEARCH_ENUMERATION_RESULT_CORRUPT"):
            local.load_enumeration_result_verified(local_experiment.experiment_fingerprint)

    root = tmp_path / "symlink"
    local, local_experiment, _context, _resolver = _verified_context(root, generation, search_space, "a" * 64)
    manifest = _enumeration_path(root, local_experiment.experiment_fingerprint)
    backup = root / "enumeration-backup.json"
    backup.write_bytes(manifest.read_bytes())
    manifest.unlink()
    os.symlink(backup, manifest)
    with pytest.raises(OnlySymbolicSearchStoreError, match="SEARCH_ENUMERATION_RESULT_CORRUPT"):
        local.load_enumeration_result_verified(local_experiment.experiment_fingerprint)


def test_enumeration_result_context_rejects_cross_authority_contradictions(tmp_path) -> None:
    generation, search_space = space(max_nodes=2)
    store, experiment, context, _resolver = _verified_context(tmp_path, generation, search_space, "a" * 64)
    value = store.load_enumeration_result_verified(experiment.experiment_fingerprint)
    for changed in (
        replace(value, experiment_fingerprint="1" * 64),
        replace(value, algorithm_implementation_fingerprint="2" * 64),
        replace(value, search_space_fingerprint="3" * 64),
    ):
        with pytest.raises(OnlySymbolicSearchError):
            commit_symbolic_enumeration_result_verified(
                changed, context, OnlyJsonSymbolicSearchStore(tmp_path / changed.enumeration_result_fingerprint)
            )
    missing = replace(
        value,
        ordered_proposal_fingerprints=("f" * 64,),
        proposal_limit_reached=False,
        search_space_exhausted=True,
    )
    with pytest.raises(OnlySymbolicSearchError, match="SEARCH_ENUMERATION_PROPOSAL_INVALID"):
        commit_symbolic_enumeration_result_verified(missing, context, store)
    original = store.load_proposal_intrinsic_verified(value.ordered_proposal_fingerprints[0])
    wrong = OnlySymbolicGraphProposalV1(
        "e" * 64,
        original.graph,
        original.candidate_output_reference,
    )
    wrong_root = OnlyJsonSymbolicSearchStore(tmp_path / "wrong-space")
    wrong_root.commit_proposal(wrong)
    wrong_result = replace(
        value,
        ordered_proposal_fingerprints=(wrong.proposal_fingerprint,),
        proposal_limit_reached=False,
        search_space_exhausted=True,
    )
    with pytest.raises(OnlySymbolicSearchError):
        commit_symbolic_enumeration_result_verified(wrong_result, context, wrong_root)


def test_all_historical_paths_work_when_current_enumerator_raises(tmp_path, monkeypatch) -> None:
    generation, search_space = space(max_nodes=2)
    store, experiment, context, resolver = _verified_context(tmp_path, generation, search_space, "a" * 64)
    provenance = _provenance(tmp_path, generation, resolver)
    provenance.commit_experiment(experiment)
    enumeration = store.load_enumeration_result_verified(experiment.experiment_fingerprint)
    proposal = store.load_proposal_intrinsic_verified(enumeration.ordered_proposal_fingerprints[0])
    plan = _plan(experiment, proposal, 0)
    provenance.commit_iteration_plan(plan)
    terminal = OnlySearchIterationResultV1(
        plan.iteration_plan_fingerprint,
        None,
        False,
        None,
        False,
        None,
        OnlySearchIterationDisposition.SKIPPED,
        OnlySearchFailureCode.SEARCH_BUDGET_EXHAUSTED,
    )
    provenance.commit_iteration_result(terminal)

    def forbidden(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("historical path touched current enumerator")

    monkeypatch.setattr(
        "onlyalpha.research.search.symbolic.enumeration.enumerate_symbolic_factor_proposals",
        forbidden,
    )
    assert resolver.resolve_verified_context(experiment).verified_evaluation.fixed_resolution.fixed_candidates
    assert resolver.load_enumeration_result_contextual_verified(experiment).result == enumeration
    assert resolver.load_proposal_contextual_verified(experiment, plan).proposal == proposal
    assert provenance.load_iteration_result_verified(terminal.iteration_result_fingerprint) == terminal


def test_symbolic_plan_ledger_is_unique_contiguous_and_restartable(tmp_path) -> None:
    generation, search_space = space(max_nodes=2)

    gap_root = tmp_path / "gap"
    store, experiment, _context, resolver = _verified_context(gap_root, generation, search_space, "a" * 64)
    provenance = _provenance(gap_root, generation, resolver)
    provenance.commit_experiment(experiment)
    result = store.load_enumeration_result_verified(experiment.experiment_fingerprint)
    proposals = tuple(store.load_proposal_intrinsic_verified(item) for item in result.ordered_proposal_fingerprints)
    assert len(proposals) >= 3
    with pytest.raises(OnlySearchProvenanceStoreError, match="SEARCH_ITERATION_PREFIX_GAP"):
        provenance.commit_iteration_plan(_plan(experiment, proposals[2], 2))
    with pytest.raises(OnlySearchProvenanceStoreError, match="SEARCH_ITERATION_PREFIX_GAP"):
        provenance.commit_iteration_plan(_plan(experiment, proposals[0], 57))

    plans = tuple(_plan(experiment, proposal, index) for index, proposal in enumerate(proposals[:3]))
    for plan in plans:
        assert provenance.commit_iteration_plan(plan).disposition.value == "CREATED"
    assert provenance.commit_iteration_plan(plans[2]).disposition.value == "REUSED"
    with pytest.raises(OnlySearchProvenanceStoreError, match="SEARCH_ITERATION_ORDINAL_CONFLICT"):
        provenance.commit_iteration_plan(_plan(experiment, proposals[1], 0))
    for item in plans:
        provenance.commit_iteration_result(
            OnlySearchIterationResultV1(
                item.iteration_plan_fingerprint,
                None,
                False,
                None,
                False,
                None,
                OnlySearchIterationDisposition.SKIPPED,
                OnlySearchFailureCode.SEARCH_BUDGET_EXHAUSTED,
            )
        )
    assert provenance.next_iteration_ordinal_verified(experiment.experiment_fingerprint) == 3

    restarted = _provenance(gap_root, generation, resolver)
    assert restarted.next_iteration_ordinal_verified(experiment.experiment_fingerprint) == 3

    plan_one_path = (
        gap_root
        / "research"
        / "search-provenance"
        / "iteration-plans"
        / "sha256"
        / plans[1].iteration_plan_fingerprint[:2]
        / plans[1].iteration_plan_fingerprint
    )
    plan_one_path.rename(gap_root / "removed-plan-one")
    with pytest.raises(OnlySearchProvenanceStoreError, match="SEARCH_ITERATION_PREFIX_CORRUPT"):
        restarted.load_iteration_plan_verified(plans[2].iteration_plan_fingerprint)


def test_workflow_restart_fails_closed_for_plan_without_terminal_result(tmp_path) -> None:
    generation, search_space = space(max_nodes=2)
    store, experiment, context, context_resolver = _verified_context(tmp_path, generation, search_space, "a" * 64)
    provenance = _provenance(tmp_path, generation, context_resolver)
    provenance.commit_experiment(experiment)
    enumeration = store.load_enumeration_result_verified(experiment.experiment_fingerprint)
    first_proposal = store.load_proposal_intrinsic_verified(enumeration.ordered_proposal_fingerprints[0])
    provenance.commit_iteration_plan(_plan(experiment, first_proposal, 0))

    registry = generation.calculation_registry()
    for registration in target_registrations():
        registry.register(registration)
    with pytest.raises(OnlySearchProvenanceStoreError, match="SEARCH_ITERATION_TERMINAL_RESULT_MISSING"):
        run_symbolic_search_workflow(
            context=context,
            symbolic_store=store,
            provenance=provenance,
            resolver=OnlyResearchSpecificationResolver(registry),
        )


def test_restart_projects_consumed_attempt_budgets_without_regaining_them(tmp_path) -> None:
    generation, search_space = space(max_nodes=2)
    dataset = "a" * 64
    reference = OnlySearchResearchResultReferenceV1("c" * 64, "d" * 64)

    def setup(root):  # type: ignore[no-untyped-def]
        symbolic, experiment, context, context_resolver = _verified_context(root, generation, search_space, dataset)
        registry = generation.calculation_registry()
        for registration in target_registrations():
            registry.register(registration)
        research_resolver = OnlyResearchSpecificationResolver(registry)
        enumeration = symbolic.load_enumeration_result_verified(experiment.experiment_fingerprint)
        proposals = tuple(
            symbolic.load_proposal_intrinsic_verified(item) for item in enumeration.ordered_proposal_fingerprints
        )
        candidates = tuple(
            resolve_symbolic_research_candidate(
                verify_symbolic_proposal_reconstruction(proposal, context), research_resolver
            ).candidate.candidate_fingerprint
            for proposal in proposals
        )
        assert all(candidates)
        provenance = OnlyJsonSearchProvenanceStore(
            root,
            catalogs=OnlyQuantAssetCatalogManager(generation),
            datasets=_Datasets(dataset),
            candidates=_Candidates(*(item for item in candidates if item is not None)),
            research_results=_ResearchResults(reference, candidates[1], dataset),
            search_contexts=context_resolver,
        )
        provenance.commit_experiment(experiment)
        return (
            symbolic,
            experiment,
            context,
            context_resolver,
            research_resolver,
            provenance,
            proposals,
            candidates,
        )

    split = setup(tmp_path / "split")
    symbolic, experiment, context, context_resolver, research_resolver, provenance, proposals, candidates = split
    plans = tuple(_plan(experiment, proposal, index) for index, proposal in enumerate(proposals[:2]))
    for plan in plans:
        provenance.commit_iteration_plan(plan)
    prefix_results = (
        OnlySearchIterationResultV1(
            plans[0].iteration_plan_fingerprint,
            candidates[0],
            True,
            None,
            False,
            None,
            OnlySearchIterationDisposition.FAILED,
            OnlySearchFailureCode.RESEARCH_EXECUTION_FAILED,
        ),
        OnlySearchIterationResultV1(
            plans[1].iteration_plan_fingerprint,
            candidates[1],
            True,
            reference,
            True,
            None,
            OnlySearchIterationDisposition.FAILED,
            OnlySearchFailureCode.QUALIFICATION_EXECUTION_FAILED,
        ),
    )
    for result in prefix_results:
        provenance.commit_iteration_result(result)

    restarted = OnlyJsonSearchProvenanceStore(
        tmp_path / "split",
        catalogs=OnlyQuantAssetCatalogManager(generation),
        datasets=_Datasets(dataset),
        candidates=_Candidates(*(item for item in candidates if item is not None)),
        research_results=_ResearchResults(reference, candidates[1], dataset),
        search_contexts=context_resolver,
    )
    assert restarted.search_restart_state_verified(experiment.experiment_fingerprint) == (2, 2, 1)

    class _NoMoreResearch:
        calls = 0

        def execute(self, *_args):  # type: ignore[no-untyped-def]
            self.calls += 1
            raise AssertionError("consumed Research budget was regained")

    class _NoMoreQualification:
        calls = 0

        def evaluate(self, *_args):  # type: ignore[no-untyped-def]
            self.calls += 1
            raise AssertionError("consumed Qualification budget was regained")

    research = _NoMoreResearch()
    qualification = _NoMoreQualification()
    resumed = run_symbolic_search_workflow(
        context=context,
        symbolic_store=symbolic,
        provenance=restarted,
        resolver=research_resolver,
        research_executor=research,
        qualification_executor=qualification,
    )
    assert research.calls == qualification.calls == 0
    assert resumed.iteration_results[0].disposition is OnlySearchIterationDisposition.CANDIDATE_BOUND

    continuous_setup = setup(tmp_path / "continuous")
    (
        continuous_symbolic,
        _continuous_experiment,
        continuous_context,
        _continuous_context_resolver,
        continuous_research_resolver,
        continuous_provenance,
        _continuous_proposals,
        _continuous_candidates,
    ) = continuous_setup

    class _ScriptedResearch:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, *_args):  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("controlled first Research failure")
            return reference

    class _ScriptedQualification:
        def evaluate(self, *_args):  # type: ignore[no-untyped-def]
            raise RuntimeError("controlled Qualification failure")

    continuous = run_symbolic_search_workflow(
        context=continuous_context,
        symbolic_store=continuous_symbolic,
        provenance=continuous_provenance,
        resolver=continuous_research_resolver,
        research_executor=_ScriptedResearch(),
        qualification_executor=_ScriptedQualification(),
    )
    assert continuous.iteration_plans == (*plans, *resumed.iteration_plans)
    assert continuous.iteration_results == (*prefix_results, *resumed.iteration_results)


def test_matching_runtime_reproduces_stored_result_and_changed_runtime_only_blocks_execution(tmp_path) -> None:
    generation, search_space = space(max_nodes=2)
    store, experiment, _context, resolver = _verified_context(tmp_path, generation, search_space, "a" * 64)
    stored = store.load_enumeration_result_verified(experiment.experiment_fingerprint)
    assert resolver.certify_current_runtime_enumeration_reproduction(experiment) == stored

    execution = enumerate_symbolic_factor_proposals(
        resolver.resolve_verified_context(experiment).verified_search_space,
        proposal_limit=experiment.search_budget.proposal_limit,
    )
    assert build_symbolic_enumeration_result(experiment, execution) == stored


def test_reproduction_mismatch_fails_before_publishing_new_proposal(tmp_path, monkeypatch) -> None:
    generation, search_space = space(max_nodes=3)
    store, experiment, context, _resolver = _verified_context(tmp_path, generation, search_space, "a" * 64)
    stored = store.load_enumeration_result_verified(experiment.experiment_fingerprint)
    expanded = enumerate_symbolic_factor_proposals(
        context.verified_search_space,
        proposal_limit=experiment.search_budget.proposal_limit + 1,
    )
    assert len(expanded.proposals) > len(stored.ordered_proposal_fingerprints)
    outside = expanded.proposals[-1]
    changed = replace(
        expanded,
        proposals=(*expanded.proposals[: experiment.search_budget.proposal_limit - 1], outside),
        search_space_exhausted=False,
        proposal_limit_reached=True,
    )
    monkeypatch.setattr(
        "onlyalpha.research.search.symbolic.integration.enumerate_symbolic_factor_proposals",
        lambda *_args, **_kwargs: changed,
    )

    with pytest.raises(OnlySymbolicSearchError, match="SEARCH_ENUMERATION_REPRODUCTION_MISMATCH"):
        run_symbolic_search_workflow(
            context=context,
            symbolic_store=store,
            provenance=object(),
            resolver=OnlyResearchSpecificationResolver(generation.calculation_registry()),
        )
    with pytest.raises(OnlySymbolicSearchStoreError, match="SEARCH_PROPOSAL_NOT_FOUND"):
        store.load_proposal_intrinsic_verified(outside.proposal_fingerprint)
