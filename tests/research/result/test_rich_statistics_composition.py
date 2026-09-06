from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from onlyalpha.research import (
    OnlyJsonResearchResultStore,
    OnlyResearchParameterNeighborhoodSummaryExecutor,
    OnlyResearchResult,
    OnlyResearchResultAssembler,
    OnlyResearchResultCalculationPlan,
    OnlyResearchResultCandidatePlan,
    OnlyResearchResultError,
    OnlyResearchResultPlan,
    OnlyResearchResultStoreError,
    OnlyResearchStatisticsResultReader,
    only_research_result_fingerprint,
)
from tests.research.evaluation.support import (
    coverage_case,
    factor_pair_effect_case,
    stability_case,
    summary_case,
)
from tests.research.evaluation.test_parameter_neighborhood_summary import _effect_sources


def _calculation_member(calculation_store, fingerprint: str):  # type: ignore[no-untyped-def]
    manifest = calculation_store.load_verified(fingerprint).manifest
    return OnlyResearchResultCalculationPlan(fingerprint, manifest.calculation_graph_fingerprint)


def _candidate(candidate: str, assignment, member, statistics):  # type: ignore[no-untyped-def]
    return OnlyResearchResultCandidatePlan(
        candidate,
        "factor",
        tuple(sorted(assignment.items())),
        member.calculation_fingerprint,
        member.graph_fingerprint,
        tuple(statistics),
    )


def _assembler(reader, calculations):  # type: ignore[no-untyped-def]
    return OnlyResearchResultAssembler(
        reader,
        calculation_result_store=calculations,
        audit_time=lambda: datetime(2026, 9, 6, tzinfo=UTC),
    )


class _MappingReader:
    def __init__(self, values):  # type: ignore[no-untyped-def]
        self._values = values

    def load_verified(self, statistics_fingerprint: str):  # type: ignore[no-untyped-def]
        return self._values[statistics_fingerprint]


@pytest.mark.parametrize("factory", (summary_case, coverage_case, stability_case))
def test_single_owner_summaries_require_dependency_and_exact_candidate_membership(tmp_path, factory) -> None:  # type: ignore[no-untyped-def]
    case = factory(tmp_path / factory.__name__)
    summary_plan, summary_store, executor = case[11], case[12], case[13]
    executor.execute(summary_plan)
    source = summary_plan.source_statistics_fingerprint
    rich = summary_plan.statistics_fingerprint
    member = _calculation_member(case[2], summary_plan.subject.calculation_fingerprint)
    candidate = _candidate(summary_plan.subject_candidate_fingerprint, {}, member, (rich,))
    reader = OnlyResearchStatisticsResultReader(
        tmp_path / factory.__name__ / "statistics-results", case[8], summary_store
    )
    assembler = _assembler(reader, case[2])
    plan = OnlyResearchResultPlan(
        (source, rich),
        2,
        summary_plan.dataset_snapshot_fingerprint,
        (member,),
        (candidate,),
    )

    assert assembler.assemble(plan).manifest.plan == plan

    missing_source = replace(plan, statistics_fingerprints=(rich,))
    with pytest.raises(OnlyResearchResultError, match="dependency is absent"):
        assembler.assemble(missing_source)

    other = _candidate("f" * 64, {}, member, (rich,))
    wrong_owner = replace(plan, candidates=tuple(sorted((replace(candidate, statistics_fingerprints=()), other))))
    with pytest.raises(OnlyResearchResultError, match="only to its exact Candidate"):
        assembler.assemble(wrong_owner)


@pytest.mark.parametrize("membership", (("a",), ("b",), ("a", "b")))
def test_factor_pair_series_and_effect_allow_either_or_both_operand_memberships(tmp_path, membership) -> None:  # type: ignore[no-untyped-def]
    case = factor_pair_effect_case(tmp_path)
    pair_plan, pair_store = case[9], case[10]
    effect_plan, summary_store, effect_executor = case[13], case[14], case[15]
    effect_executor.execute(effect_plan)
    pair_fingerprint = pair_plan.statistics_fingerprint
    effect_fingerprint = effect_plan.statistics_fingerprint
    members = tuple(
        sorted(
            {
                _calculation_member(case[2], pair_plan.first_operand.series.calculation_fingerprint),
                _calculation_member(case[2], pair_plan.second_operand.series.calculation_fingerprint),
            }
        )
    )
    member_by_fingerprint = {item.calculation_fingerprint: item for item in members}
    candidates = []
    for operand, label in zip((pair_plan.first_operand, pair_plan.second_operand), ("a", "b"), strict=True):
        owned = (pair_fingerprint, effect_fingerprint) if label in membership else ()
        candidates.append(
            _candidate(
                operand.candidate_fingerprint,
                {},
                member_by_fingerprint[operand.series.calculation_fingerprint],
                owned,
            )
        )
    reader = OnlyResearchStatisticsResultReader(tmp_path / "statistics-results", case[8], summary_store, pair_store)
    plan = OnlyResearchResultPlan(
        (pair_fingerprint, effect_fingerprint),
        2,
        pair_plan.dataset_snapshot_fingerprint,
        members,
        tuple(sorted(candidates)),
    )

    assert _assembler(reader, case[2]).assemble(plan).manifest.plan == plan


def test_factor_pair_rejects_non_operand_membership_and_missing_pair_effect_dependency(tmp_path) -> None:
    case = factor_pair_effect_case(tmp_path)
    pair_plan, pair_store = case[9], case[10]
    effect_plan, summary_store, effect_executor = case[13], case[14], case[15]
    effect_executor.execute(effect_plan)
    pair_fingerprint = pair_plan.statistics_fingerprint
    effect_fingerprint = effect_plan.statistics_fingerprint
    members = tuple(
        sorted(
            {
                _calculation_member(case[2], pair_plan.first_operand.series.calculation_fingerprint),
                _calculation_member(case[2], pair_plan.second_operand.series.calculation_fingerprint),
            }
        )
    )
    by_calculation = {item.calculation_fingerprint: item for item in members}
    candidates = tuple(
        sorted(
            _candidate(operand.candidate_fingerprint, {}, by_calculation[operand.series.calculation_fingerprint], ())
            for operand in (pair_plan.first_operand, pair_plan.second_operand)
        )
    )
    non_operand = _candidate("c" * 64, {}, members[0], (effect_fingerprint,))
    reader = OnlyResearchStatisticsResultReader(tmp_path / "statistics-results", case[8], summary_store, pair_store)
    assembler = _assembler(reader, case[2])
    wrong_membership = OnlyResearchResultPlan(
        (pair_fingerprint, effect_fingerprint),
        2,
        pair_plan.dataset_snapshot_fingerprint,
        members,
        tuple(sorted((*candidates, non_operand))),
    )
    with pytest.raises(OnlyResearchResultError, match="operand subset"):
        assembler.assemble(wrong_membership)

    owner = replace(candidates[0], statistics_fingerprints=(effect_fingerprint,))
    missing_dependency = OnlyResearchResultPlan(
        (effect_fingerprint,),
        2,
        pair_plan.dataset_snapshot_fingerprint,
        members,
        tuple(sorted((owner, candidates[1]))),
    )
    with pytest.raises(OnlyResearchResultError, match="dependency is absent"):
        assembler.assemble(missing_dependency)


def test_factor_pair_verifies_both_operand_candidate_calculation_links(tmp_path) -> None:
    case = factor_pair_effect_case(tmp_path)
    pair_plan, pair_store = case[9], case[10]
    pair = pair_store.load_verified(pair_plan.statistics_fingerprint)
    members = tuple(
        sorted(
            {
                _calculation_member(case[2], pair_plan.first_operand.series.calculation_fingerprint),
                _calculation_member(case[2], pair_plan.second_operand.series.calculation_fingerprint),
            }
        )
    )
    member_by_fingerprint = {item.calculation_fingerprint: item for item in members}
    candidates = tuple(
        sorted(
            _candidate(
                operand.candidate_fingerprint,
                {},
                member_by_fingerprint[operand.series.calculation_fingerprint],
                (pair_plan.statistics_fingerprint,),
            )
            for operand in (pair_plan.first_operand, pair_plan.second_operand)
        )
    )
    plan = OnlyResearchResultPlan(
        (pair_plan.statistics_fingerprint,),
        2,
        pair_plan.dataset_snapshot_fingerprint,
        members,
        candidates,
    )
    original = pair.manifest.plan
    try:
        mixed_second = replace(
            original.second_operand,
            series=replace(
                original.second_operand.series,
                calculation_fingerprint=original.first_operand.series.calculation_fingerprint,
            ),
        )
        object.__setattr__(pair.manifest, "plan", replace(original, second_operand=mixed_second))
        assembler = _assembler(_MappingReader({pair_plan.statistics_fingerprint: pair}), case[2])
        with pytest.raises(OnlyResearchResultError, match="does not match exact Candidate Calculation"):
            assembler.assemble(plan)
    finally:
        object.__setattr__(pair.manifest, "plan", original)


def test_rich_result_with_legacy_only_reader_configuration_fails_closed(tmp_path) -> None:
    case = summary_case(tmp_path)
    summary_plan, executor = case[11], case[13]
    executor.execute(summary_plan)
    member = _calculation_member(case[2], summary_plan.subject.calculation_fingerprint)
    candidate = _candidate(
        summary_plan.subject_candidate_fingerprint, {}, member, (summary_plan.statistics_fingerprint,)
    )
    plan = OnlyResearchResultPlan(
        (summary_plan.source_statistics_fingerprint, summary_plan.statistics_fingerprint),
        2,
        summary_plan.dataset_snapshot_fingerprint,
        (member,),
        (candidate,),
    )
    assembler = _assembler(case[8], case[2])
    with pytest.raises(OnlyResearchResultError):
        assembler.assemble(plan)


def test_assembler_admission_and_store_verified_load_share_rich_rejection_semantics(tmp_path) -> None:
    case = summary_case(tmp_path)
    summary_plan, summary_store, executor = case[11], case[12], case[13]
    executor.execute(summary_plan)
    source = summary_plan.source_statistics_fingerprint
    rich = summary_plan.statistics_fingerprint
    member = _calculation_member(case[2], summary_plan.subject.calculation_fingerprint)
    owner = _candidate(summary_plan.subject_candidate_fingerprint, {}, member, (rich,))
    valid_plan = OnlyResearchResultPlan(
        (source, rich), 2, summary_plan.dataset_snapshot_fingerprint, (member,), (owner,)
    )
    reader = OnlyResearchStatisticsResultReader(tmp_path / "statistics-results", case[8], summary_store)
    assembler = _assembler(reader, case[2])
    valid = assembler.assemble(valid_plan)
    wrong = _candidate("f" * 64, {}, member, (rich,))
    invalid_plan = replace(
        valid_plan,
        candidates=tuple(sorted((replace(owner, statistics_fingerprints=()), wrong))),
    )
    with pytest.raises(OnlyResearchResultError, match="only to its exact Candidate"):
        assembler.assemble(invalid_plan)

    manifest = replace(
        valid.manifest,
        plan=invalid_plan,
        research_result_plan_fingerprint=invalid_plan.fingerprint,
        research_result_fingerprint=only_research_result_fingerprint(
            invalid_plan.fingerprint,
            valid.manifest.research_result_content_fingerprint,
            schema_version=2,
        ),
    )
    store = OnlyJsonResearchResultStore(tmp_path / "research-results", reader, case[2])
    with pytest.raises(OnlyResearchResultStoreError, match="only to its exact Candidate") as admission:
        store.commit(OnlyResearchResult(manifest))
    assert admission.value.code == "RESEARCH_RESULT_INVALID"

    target = tmp_path / "research-results" / "sha256" / invalid_plan.fingerprint[:2] / invalid_plan.fingerprint
    target.mkdir(parents=True)
    (target / "manifest.json").write_text(json.dumps(manifest.to_dict()), encoding="utf-8")
    with pytest.raises(OnlyResearchResultStoreError, match="only to its exact Candidate") as loaded:
        store.load_verified(invalid_plan.fingerprint)
    assert loaded.value.code == "RESEARCH_RESULT_CORRUPT"


def test_neighborhood_closes_direct_transitive_membership_and_exact_assignments(tmp_path) -> None:
    case, effects, bindings, neighborhood_plan = _effect_sources(tmp_path, 3)
    OnlyResearchParameterNeighborhoodSummaryExecutor(case[12]).execute(neighborhood_plan)
    source = case[6].statistics_fingerprint
    effect_fingerprints = tuple(result.manifest.statistics_fingerprint for result in effects)
    neighborhood = neighborhood_plan.statistics_fingerprint
    member = _calculation_member(case[2], case[6].feature.calculation_fingerprint)
    candidates = tuple(
        sorted(
            _candidate(
                binding.candidate_fingerprint,
                dict(binding.assignment),
                member,
                ((effect_fingerprints[index], neighborhood) if index == 0 else (effect_fingerprints[index],)),
            )
            for index, binding in enumerate(bindings)
        )
    )
    reader = OnlyResearchStatisticsResultReader(tmp_path / "statistics-results", case[8], case[12])
    assembler = _assembler(reader, case[2])
    plan = OnlyResearchResultPlan(
        (source, *effect_fingerprints, neighborhood),
        2,
        neighborhood_plan.dataset_snapshot_fingerprint,
        (member,),
        candidates,
    )
    result = assembler.assemble(plan)
    store = OnlyJsonResearchResultStore(tmp_path / "research-results", reader, case[2])
    assert store.commit(result).disposition.value == "EXECUTED"
    assert store.commit(result).disposition.value == "REUSED"
    assert (
        store.load_verified(plan.fingerprint).manifest.research_result_fingerprint
        == result.manifest.research_result_fingerprint
    )

    without_neighbor_effect = effect_fingerprints[1]
    direct_missing_candidates = tuple(
        replace(
            candidate,
            statistics_fingerprints=tuple(x for x in candidate.statistics_fingerprints if x != without_neighbor_effect),
        )
        for candidate in candidates
    )
    direct_missing = replace(
        plan,
        statistics_fingerprints=tuple(x for x in plan.statistics_fingerprints if x != without_neighbor_effect),
        candidates=direct_missing_candidates,
    )
    with pytest.raises(OnlyResearchResultError, match="dependency is absent"):
        assembler.assemble(direct_missing)

    transitive_missing = replace(
        plan, statistics_fingerprints=tuple(x for x in plan.statistics_fingerprints if x != source)
    )
    with pytest.raises(OnlyResearchResultError, match="dependency is absent"):
        assembler.assemble(transitive_missing)

    changed = replace(candidates[1], assignment=(("threshold", bindings[1].assignment["threshold"]), ("window", 999)))
    wrong_assignment = replace(plan, candidates=tuple(sorted((candidates[0], changed, candidates[2]))))
    with pytest.raises(OnlyResearchResultError, match="assignment does not match"):
        assembler.assemble(wrong_assignment)

    plan_path = tmp_path / "rich-plan.json"
    plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
    script = r"""
import json, sys
from datetime import UTC, datetime
from pathlib import Path
from onlyalpha.research import *
root = Path(sys.argv[1])
plan = OnlyResearchResultPlan.from_dict(json.loads((root / "rich-plan.json").read_text()))
datasets = OnlyParquetResearchDatasetSnapshotStore(root / "datasets")
calculations = OnlyParquetResearchCalculationResultStore(root / "calculation-results", datasets)
legacy = OnlyParquetResearchStatisticsResultStore(root / "statistics-results", calculations)
summaries = OnlyJsonResearchSummaryStatisticsResultStore(root / "statistics-results", legacy)
reader = OnlyResearchStatisticsResultReader(root / "statistics-results", legacy, summaries)
assembler = OnlyResearchResultAssembler(
    reader, calculation_result_store=calculations, audit_time=lambda: datetime(2030, 1, 1, tzinfo=UTC)
)
store = OnlyJsonResearchResultStore(root / "research-results", reader, calculations)
outcome = store.commit(assembler.assemble(plan))
print(outcome.disposition.value, outcome.research_result_fingerprint)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert completed.stdout.strip() == f"REUSED {result.manifest.research_result_fingerprint}"


def test_rich_candidate_calculation_graph_node_and_output_linkage_fail_closed(tmp_path) -> None:
    case = summary_case(tmp_path)
    summary_plan, summary_store, executor = case[11], case[12], case[13]
    executor.execute(summary_plan)
    member = _calculation_member(case[2], summary_plan.subject.calculation_fingerprint)
    rich = summary_plan.statistics_fingerprint
    source = summary_plan.source_statistics_fingerprint
    candidate = _candidate(summary_plan.subject_candidate_fingerprint, {}, member, (rich,))
    reader = OnlyResearchStatisticsResultReader(tmp_path / "statistics-results", case[8], summary_store)
    assembler = _assembler(reader, case[2])
    base = OnlyResearchResultPlan((source, rich), 2, summary_plan.dataset_snapshot_fingerprint, (member,), (candidate,))

    with pytest.raises(OnlyResearchResultError, match="Candidate Graph"):
        assembler.assemble(replace(base, candidates=(replace(candidate, graph_fingerprint="f" * 64),)))

    rich_result = summary_store.load_verified(rich)
    source_result = case[8].load_verified(source)
    tampered_assembler = _assembler(_MappingReader({source: source_result, rich: rich_result}), case[2])
    original_plan = rich_result.manifest.plan
    try:
        object.__setattr__(
            rich_result.manifest,
            "plan",
            replace(original_plan, subject=replace(original_plan.subject, node_fingerprint="f" * 64)),
        )
        with pytest.raises(OnlyResearchResultError, match="node is absent"):
            tampered_assembler.assemble(base)
        object.__setattr__(
            rich_result.manifest,
            "plan",
            replace(original_plan, subject=replace(original_plan.subject, output_name="missing")),
        )
        with pytest.raises(OnlyResearchResultError, match="output is absent"):
            tampered_assembler.assemble(base)
    finally:
        object.__setattr__(rich_result.manifest, "plan", original_plan)


def test_rich_factor_series_cannot_mix_candidate_and_calculation(tmp_path) -> None:
    case = summary_case(tmp_path)
    summary_plan, summary_store, executor = case[11], case[12], case[13]
    executor.execute(summary_plan)
    feature_member = _calculation_member(case[2], summary_plan.subject.calculation_fingerprint)
    target_member = _calculation_member(case[2], case[6].target.calculation_fingerprint)
    rich = summary_plan.statistics_fingerprint
    source = summary_plan.source_statistics_fingerprint
    candidate = _candidate(summary_plan.subject_candidate_fingerprint, {}, feature_member, (rich,))
    plan = OnlyResearchResultPlan(
        (source, rich),
        2,
        summary_plan.dataset_snapshot_fingerprint,
        tuple(sorted((feature_member, target_member))),
        (candidate,),
    )
    rich_result = summary_store.load_verified(rich)
    source_result = case[8].load_verified(source)
    original = rich_result.manifest.plan
    try:
        object.__setattr__(
            rich_result.manifest,
            "plan",
            replace(
                original,
                subject=replace(original.subject, calculation_fingerprint=target_member.calculation_fingerprint),
            ),
        )
        assembler = _assembler(_MappingReader({source: source_result, rich: rich_result}), case[2])
        with pytest.raises(OnlyResearchResultError, match="does not match exact Candidate Calculation"):
            assembler.assemble(plan)
    finally:
        object.__setattr__(rich_result.manifest, "plan", original)
