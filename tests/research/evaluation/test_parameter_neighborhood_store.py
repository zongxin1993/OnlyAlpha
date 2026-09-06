from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research import (
    OnlyResearchParameterNeighborhoodSummaryExecution,
    OnlyResearchParameterNeighborhoodSummaryExecutor,
    OnlyResearchParameterNeighborhoodSummaryPlan,
    OnlyResearchStatisticsDisposition,
    OnlyResearchStatisticsResultStoreError,
    only_research_parameter_neighborhood_result_content_fingerprint,
)
from tests.research.evaluation.support import coverage_case, factor_pair_effect_case, stability_case
from tests.research.evaluation.test_parameter_neighborhood_summary import _effect_sources


def _authority(root, fingerprint):
    return root / "statistics-results" / "sha256" / fingerprint[:2] / fingerprint


def test_neighborhood_store_execute_reuse_and_ordered_multi_upstream_identity(tmp_path) -> None:
    case, results, _, plan = _effect_sources(tmp_path, 4)
    executor = OnlyResearchParameterNeighborhoodSummaryExecutor(case[12])
    first = executor.execute(plan)
    second = executor.execute(OnlyResearchParameterNeighborhoodSummaryPlan.from_dict(plan.to_dict()))
    assert first.disposition is OnlyResearchStatisticsDisposition.EXECUTED
    assert second.disposition is OnlyResearchStatisticsDisposition.REUSED
    loaded = case[12].load_verified(plan.statistics_fingerprint)
    references = loaded.manifest.upstream_statistics_references
    assert references.focal.statistics_fingerprint == plan.focal.source_statistics_fingerprint
    assert tuple(item.statistics_fingerprint for item in references.neighbors) == tuple(
        item.source_statistics_fingerprint for item in plan.neighbors
    )
    reversed_plan = replace(plan, neighbors=tuple(reversed(plan.neighbors)))
    reversed_result = executor.execute(reversed_plan)
    assert reversed_result.statistics_fingerprint != first.statistics_fingerprint
    assert reversed_result.statistics_result_fingerprint != first.statistics_result_fingerprint

    changed_exact = replace(
        plan,
        focal=replace(plan.focal, source_statistics_result_fingerprint="f" * 64),
    )
    assert changed_exact.statistics_fingerprint == plan.statistics_fingerprint
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as execution_conflict:
        executor.execute(changed_exact)
    assert execution_conflict.value.code == "DETERMINISTIC_RESULT_CONFLICT"
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as captured:
        case[12].commit(OnlyResearchParameterNeighborhoodSummaryExecution(changed_exact, loaded.summary))
    assert captured.value.code == "DETERMINISTIC_RESULT_CONFLICT"
    changed_summary = replace(
        loaded.summary,
        focal_value=replace(loaded.summary.focal_value, decimal_value=Decimal("0.999999999999")),
        focal_minus_neighbor_mean=replace(
            loaded.summary.focal_minus_neighbor_mean,
            decimal_value=Decimal("0.999999999999") - loaded.summary.neighbor_mean.decimal_value,
        ),
    )
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as changed_content:
        case[12].commit(OnlyResearchParameterNeighborhoodSummaryExecution(plan, changed_summary))
    assert changed_content.value.code == "DETERMINISTIC_RESULT_CONFLICT"


def test_neighborhood_result_content_fingerprint_binds_exact_ordered_results(tmp_path) -> None:
    _, _, _, plan = _effect_sources(tmp_path, 3)
    pairs = tuple(
        (item.source_statistics_fingerprint, item.source_statistics_result_fingerprint) for item in plan.neighbors
    )
    first = only_research_parameter_neighborhood_result_content_fingerprint(
        plan.focal.source_statistics_fingerprint,
        plan.focal.source_statistics_result_fingerprint,
        pairs,
        {"payload": 1},
    )
    changed_result = only_research_parameter_neighborhood_result_content_fingerprint(
        plan.focal.source_statistics_fingerprint,
        "f" * 64,
        pairs,
        {"payload": 1},
    )
    reversed_order = only_research_parameter_neighborhood_result_content_fingerprint(
        plan.focal.source_statistics_fingerprint,
        plan.focal.source_statistics_result_fingerprint,
        tuple(reversed(pairs)),
        {"payload": 1},
    )
    assert len({first, changed_result, reversed_order}) == 3


def test_neighborhood_store_fresh_process_reuses_exact_result(tmp_path) -> None:
    case, _, _, plan = _effect_sources(tmp_path, 3)
    first = OnlyResearchParameterNeighborhoodSummaryExecutor(case[12]).execute(plan)
    plan_path = tmp_path / "neighborhood-plan.json"
    plan_path.write_text(only_canonical_json(plan.to_dict()), encoding="utf-8")
    script = r"""
import json, sys
from pathlib import Path
from onlyalpha.research import *
root = Path(sys.argv[1])
plan = OnlyResearchParameterNeighborhoodSummaryPlan.from_dict(json.loads((root / "neighborhood-plan.json").read_text()))
datasets = OnlyParquetResearchDatasetSnapshotStore(root / "datasets")
calculations = OnlyParquetResearchCalculationResultStore(root / "calculation-results", datasets)
legacy = OnlyParquetResearchStatisticsResultStore(root / "statistics-results", calculations)
summaries = OnlyJsonResearchSummaryStatisticsResultStore(root / "statistics-results", legacy)
outcome = OnlyResearchParameterNeighborhoodSummaryExecutor(summaries).execute(plan)
print(outcome.disposition.value, outcome.statistics_fingerprint, outcome.statistics_result_fingerprint)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert completed.stdout.strip() == (f"REUSED {plan.statistics_fingerprint} {first.statistics_result_fingerprint}")


def test_shared_summary_store_supports_all_five_summary_kinds(tmp_path) -> None:
    effect_case, _, _, neighborhood_plan = _effect_sources(tmp_path, 2)
    effect_plan = effect_case[11]
    effect_case[13].execute(effect_plan)
    coverage = coverage_case(tmp_path)
    coverage[13].execute(coverage[11])
    stability = stability_case(tmp_path)
    stability[13].execute(stability[11])
    pair = factor_pair_effect_case(tmp_path)
    pair[15].execute(pair[13])
    OnlyResearchParameterNeighborhoodSummaryExecutor(pair[14]).execute(neighborhood_plan)
    assert {
        pair[14].load_verified(plan.statistics_fingerprint).summary.summary_kind.value
        for plan in (effect_plan, coverage[11], stability[11], pair[13], neighborhood_plan)
    } == {
        "EFFECT_SUMMARY",
        "COVERAGE_SUMMARY",
        "TEMPORAL_STABILITY",
        "FACTOR_PAIR_EFFECT_SUMMARY",
        "PARAMETER_NEIGHBORHOOD_SUMMARY",
    }


@pytest.mark.parametrize(
    "mutation",
    (
        "manifest_unknown",
        "domain",
        "schema",
        "kind",
        "source_metric",
        "dataset",
        "focal_candidate",
        "focal_assignment",
        "focal_logical",
        "focal_result",
        "neighbor_candidate",
        "neighbor_assignment",
        "neighbor_order",
        "duplicate_neighbor",
        "neighbor_logical",
        "neighbor_result",
        "dependency_focal_logical",
        "dependency_focal_result",
        "dependency_neighbor_order",
        "focal_value",
        "focal_metric",
        "focal_status",
        "neighbor_count",
        "count_metric",
        "count_status",
        "valid_neighbor_count",
        "invalid_neighbor_count",
        "neighbor_mean",
        "neighbor_mean_metric",
        "neighbor_mean_status",
        "neighbor_min",
        "neighbor_max",
        "neighbor_stddev",
        "local_range",
        "difference",
        "summary_hash",
        "content",
        "result",
        "missing_summary",
        "missing_manifest",
        "unexpected_file",
        "symlink_summary",
    ),
)
def test_neighborhood_corruption_matrix_fails_closed(tmp_path, mutation: str) -> None:
    root = tmp_path / mutation
    case, _, _, plan = _effect_sources(root, 3)
    OnlyResearchParameterNeighborhoodSummaryExecutor(case[12]).execute(plan)
    authority = _authority(root, plan.statistics_fingerprint)
    manifest_path = authority / "manifest.json"
    summary_path = authority / "summary.json"
    manifest = json.loads(manifest_path.read_text())
    summary = json.loads(summary_path.read_text())
    replacement = "a" * 64

    if mutation == "manifest_unknown":
        manifest["unknown"] = True
    elif mutation == "domain":
        manifest["domain"] = "UNKNOWN"
    elif mutation == "schema":
        manifest["schema_version"] = 2
    elif mutation == "kind":
        manifest["plan"]["definition"]["summary_kind"] = "COVERAGE_SUMMARY"
    elif mutation == "source_metric":
        manifest["plan"]["source_metric_id"] = "research.factor.rank_ic.mean@1"
    elif mutation == "dataset":
        manifest["plan"]["dataset_snapshot_fingerprint"] = replacement
    elif mutation == "focal_candidate":
        manifest["plan"]["focal"]["candidate_fingerprint"] = replacement
    elif mutation == "focal_assignment":
        manifest["plan"]["focal"]["assignment"]["window"]["value"] = 99
    elif mutation == "focal_logical":
        manifest["plan"]["focal"]["source_statistics_fingerprint"] = replacement
    elif mutation == "focal_result":
        manifest["plan"]["focal"]["source_statistics_result_fingerprint"] = replacement
    elif mutation == "neighbor_candidate":
        manifest["plan"]["neighbors"][0]["candidate_fingerprint"] = replacement
    elif mutation == "neighbor_assignment":
        manifest["plan"]["neighbors"][0]["assignment"]["window"]["value"] = 99
    elif mutation == "neighbor_order":
        manifest["plan"]["neighbors"].reverse()
    elif mutation == "duplicate_neighbor":
        manifest["plan"]["neighbors"][1]["candidate_fingerprint"] = manifest["plan"]["neighbors"][0][
            "candidate_fingerprint"
        ]
    elif mutation == "neighbor_logical":
        manifest["plan"]["neighbors"][0]["source_statistics_fingerprint"] = replacement
    elif mutation == "neighbor_result":
        manifest["plan"]["neighbors"][0]["source_statistics_result_fingerprint"] = replacement
    elif mutation == "dependency_focal_logical":
        manifest["upstream_statistics_references"]["focal"]["statistics_fingerprint"] = replacement
    elif mutation == "dependency_focal_result":
        manifest["upstream_statistics_references"]["focal"]["statistics_result_fingerprint"] = replacement
    elif mutation == "dependency_neighbor_order":
        manifest["upstream_statistics_references"]["neighbors"].reverse()
    elif mutation == "focal_value":
        summary["focal_value"]["decimal_value"] = "0.999999999999"
    elif mutation == "focal_metric":
        summary["focal_value"]["metric_id"] = "research.factor.ic.mean@1"
    elif mutation == "focal_status":
        summary["focal_value"]["status"] = "NO_VALID_OBSERVATIONS"
    elif mutation == "neighbor_count":
        summary["neighbor_count"]["integer_value"] = 99
    elif mutation == "count_metric":
        summary["neighbor_count"]["metric_id"] = "research.factor.ic.total_count@1"
    elif mutation == "count_status":
        summary["neighbor_count"]["status"] = "NO_VALID_OBSERVATIONS"
    elif mutation == "valid_neighbor_count":
        summary["valid_neighbor_count"]["integer_value"] = 99
    elif mutation == "invalid_neighbor_count":
        summary["neighbor_no_valid_observations_count"]["integer_value"] = 99
    elif mutation == "neighbor_mean":
        summary["neighbor_mean"]["decimal_value"] = "0.999999999999"
    elif mutation == "neighbor_mean_metric":
        summary["neighbor_mean"]["metric_id"] = "research.factor.ic.mean@1"
    elif mutation == "neighbor_mean_status":
        summary["neighbor_mean"]["status"] = "NO_VALID_OBSERVATIONS"
    elif mutation == "neighbor_min":
        summary["neighbor_min"]["decimal_value"] = "0.999999999999"
    elif mutation == "neighbor_max":
        summary["neighbor_max"]["decimal_value"] = "0.999999999999"
    elif mutation == "neighbor_stddev":
        summary["neighbor_stddev_sample"]["decimal_value"] = "0.999999999999"
    elif mutation == "local_range":
        summary["local_range"]["decimal_value"] = "0.999999999999"
    elif mutation == "difference":
        summary["focal_minus_neighbor_mean"]["decimal_value"] = "0.999999999999"
    elif mutation == "summary_hash":
        manifest["summary_byte_sha256"] = replacement
    elif mutation == "content":
        manifest["result_content_fingerprint"] = replacement
    elif mutation == "result":
        manifest["statistics_result_fingerprint"] = replacement
    elif mutation == "missing_summary":
        summary_path.unlink()
    elif mutation == "missing_manifest":
        manifest_path.unlink()
    elif mutation == "unexpected_file":
        (authority / "extra").write_text("x")
    elif mutation == "symlink_summary":
        summary_path.unlink()
        summary_path.symlink_to(manifest_path)
    else:  # pragma: no cover
        raise AssertionError(mutation)

    if mutation in {
        "manifest_unknown",
        "domain",
        "schema",
        "kind",
        "source_metric",
        "dataset",
        "focal_candidate",
        "focal_assignment",
        "focal_logical",
        "focal_result",
        "neighbor_candidate",
        "neighbor_assignment",
        "neighbor_order",
        "duplicate_neighbor",
        "neighbor_logical",
        "neighbor_result",
        "dependency_focal_logical",
        "dependency_focal_result",
        "dependency_neighbor_order",
        "summary_hash",
        "content",
        "result",
    }:
        manifest_path.write_text(only_canonical_json(manifest))
    elif mutation not in {"missing_summary", "missing_manifest", "unexpected_file", "symlink_summary"}:
        summary_path.write_text(only_canonical_json(summary))

    with pytest.raises(OnlyResearchStatisticsResultStoreError) as captured:
        case[12].load_verified(plan.statistics_fingerprint)
    assert captured.value.code == "SUMMARY_STATISTICS_RESULT_CORRUPT"


@pytest.mark.parametrize("role", ("focal", "neighbor"))
@pytest.mark.parametrize("failure", ("missing", "corrupt"))
def test_neighborhood_missing_or_corrupt_upstream_fails_existing_result_closed(
    tmp_path, role: str, failure: str
) -> None:
    case, _, _, plan = _effect_sources(tmp_path, 3)
    OnlyResearchParameterNeighborhoodSummaryExecutor(case[12]).execute(plan)
    fingerprint = (
        plan.focal.source_statistics_fingerprint if role == "focal" else plan.neighbors[0].source_statistics_fingerprint
    )
    upstream = _authority(tmp_path, fingerprint)
    if failure == "missing":
        shutil.rmtree(upstream)
    else:
        (upstream / "summary.json").write_text("{}")
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as captured:
        case[12].load_verified(plan.statistics_fingerprint)
    assert captured.value.code == "SUMMARY_STATISTICS_RESULT_CORRUPT"
