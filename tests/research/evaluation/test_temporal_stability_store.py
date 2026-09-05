from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research import (
    OnlyResearchStatisticsResultReader,
    OnlyResearchStatisticsResultStoreError,
    OnlyResearchSummaryStatisticsResult,
    OnlyResearchTemporalStabilityExecution,
)
from tests.research.evaluation.support import coverage_case, stability_case, summary_case


def _result_root(root: Path, fingerprint: str) -> Path:
    return root / "statistics-results" / "sha256" / fingerprint[:2] / fingerprint


def test_shared_store_and_reader_support_all_three_summary_kinds(tmp_path) -> None:
    effect = summary_case(tmp_path)
    effect_outcome = effect[13].execute(effect[11])
    coverage = coverage_case(tmp_path)
    coverage_outcome = coverage[13].execute(coverage[11])
    stability = stability_case(tmp_path)
    stability_outcome = stability[13].execute(stability[11])
    assert (
        len(
            {
                effect_outcome.statistics_fingerprint,
                coverage_outcome.statistics_fingerprint,
                stability_outcome.statistics_fingerprint,
            }
        )
        == 3
    )
    reader = OnlyResearchStatisticsResultReader(tmp_path / "statistics-results", effect[8], effect[12])
    for fingerprint in (
        effect_outcome.statistics_fingerprint,
        coverage_outcome.statistics_fingerprint,
        stability_outcome.statistics_fingerprint,
    ):
        assert isinstance(reader.load_verified(fingerprint), OnlyResearchSummaryStatisticsResult)


def test_stability_deterministic_conflict_never_overwrites(tmp_path) -> None:
    case = stability_case(tmp_path)
    case[13].execute(case[11])
    loaded = case[12].load_verified(case[11].statistics_fingerprint)
    changed = replace(
        loaded.summary,
        min_slice_mean=replace(
            loaded.summary.min_slice_mean,
            decimal_value=Decimal("0.999999999999"),
        ),
    )
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as captured:
        case[12].commit(OnlyResearchTemporalStabilityExecution(case[11], changed))
    assert captured.value.code == "DETERMINISTIC_RESULT_CONFLICT"
    assert case[12].load_verified(case[11].statistics_fingerprint) == loaded

    changed_dependency = replace(case[11], source_statistics_result_fingerprint="4" * 64)
    assert changed_dependency.statistics_fingerprint == case[11].statistics_fingerprint
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as dependency_conflict:
        case[12].commit(OnlyResearchTemporalStabilityExecution(changed_dependency, loaded.summary))
    assert dependency_conflict.value.code == "DETERMINISTIC_RESULT_CONFLICT"


def test_fresh_process_stability_identity_and_reuse_are_stable(tmp_path) -> None:
    case = stability_case(tmp_path)
    first = case[13].execute(case[11])
    manifest_path = _result_root(tmp_path, case[11].statistics_fingerprint) / "manifest.json"
    script = r"""
import json, sys
from pathlib import Path
from onlyalpha.research import (
    OnlyJsonResearchSummaryStatisticsResultStore, OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore, OnlyParquetResearchStatisticsResultStore,
    OnlyResearchTemporalStabilityExecutor, OnlyResearchTemporalStabilityPlan,
)
root = Path(sys.argv[1])
payload = json.loads(Path(sys.argv[2]).read_text())
plan = OnlyResearchTemporalStabilityPlan.from_dict(payload["plan"])
datasets = OnlyParquetResearchDatasetSnapshotStore(root / "datasets")
calculations = OnlyParquetResearchCalculationResultStore(root / "calculation-results", datasets)
legacy = OnlyParquetResearchStatisticsResultStore(root / "statistics-results", calculations)
summaries = OnlyJsonResearchSummaryStatisticsResultStore(root / "statistics-results", legacy)
outcome = OnlyResearchTemporalStabilityExecutor(legacy, summaries).execute(plan)
print(json.dumps({"logical": plan.statistics_fingerprint, "result": outcome.statistics_result_fingerprint, "disposition": outcome.disposition.value}))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, ("src", env.get("PYTHONPATH", ""))))
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), str(manifest_path)],
        cwd=os.getcwd(),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == {
        "logical": case[11].statistics_fingerprint,
        "result": first.statistics_result_fingerprint,
        "disposition": "REUSED",
    }


@pytest.mark.parametrize(
    "mutation",
    (
        "manifest_unknown_field",
        "manifest_statistics_fingerprint",
        "manifest_content_fingerprint",
        "manifest_result_fingerprint",
        "manifest_dataset",
        "manifest_source_logical",
        "manifest_source_result",
        "summary_byte_hash",
        "plan_summary_kind",
        "payload_summary_kind",
        "interval_start",
        "interval_end",
        "slice_order",
        "missing_slice",
        "extra_slice",
        "slice_mean_status",
        "slice_valid_ratio",
        "slice_count",
        "valid_slice_count",
        "sign_counts",
        "ratios",
        "min_max",
        "stddev",
        "metric_id",
        "value_kind",
        "unknown_schema",
        "unknown_domain",
        "missing_summary_file",
        "unexpected_file",
    ),
)
def test_stability_corruption_matrix_fails_closed(tmp_path, mutation: str) -> None:
    root = tmp_path / mutation
    case = stability_case(root)
    case[13].execute(case[11])
    authority = _result_root(root, case[11].statistics_fingerprint)
    manifest_path = authority / "manifest.json"
    summary_path = authority / "summary.json"
    manifest = json.loads(manifest_path.read_text())
    summary = json.loads(summary_path.read_text())

    if mutation == "manifest_unknown_field":
        manifest["unknown"] = True
    elif mutation == "manifest_statistics_fingerprint":
        manifest["statistics_fingerprint"] = "1" * 64
    elif mutation == "manifest_content_fingerprint":
        manifest["result_content_fingerprint"] = "2" * 64
    elif mutation == "manifest_result_fingerprint":
        manifest["statistics_result_fingerprint"] = "3" * 64
    elif mutation == "manifest_dataset":
        manifest["dataset_snapshot_fingerprint"] = "4" * 64
    elif mutation == "manifest_source_logical":
        manifest["source_statistics_fingerprint"] = "5" * 64
    elif mutation == "manifest_source_result":
        manifest["source_statistics_result_fingerprint"] = "6" * 64
    elif mutation == "summary_byte_hash":
        manifest["summary_byte_sha256"] = "7" * 64
    elif mutation == "plan_summary_kind":
        manifest["plan"]["definition"]["summary_kind"] = "COVERAGE_SUMMARY"
    elif mutation == "payload_summary_kind":
        summary["summary_kind"] = "COVERAGE_SUMMARY"
    elif mutation == "interval_start":
        summary["slices"][0]["start_ts_event_ns"] += 1
    elif mutation == "interval_end":
        summary["slices"][0]["end_ts_event_ns"] += 1
    elif mutation == "slice_order":
        summary["slices"].reverse()
    elif mutation == "missing_slice":
        summary["slices"].pop()
    elif mutation == "extra_slice":
        summary["slices"].append(summary["slices"][0])
    elif mutation == "slice_mean_status":
        summary["slices"][0]["mean"] = {"status": "NO_VALID_OBSERVATIONS", "decimal_value": None}
    elif mutation == "slice_valid_ratio":
        summary["slices"][0]["valid_timestamp_ratio"]["decimal_value"] = "0.999999999999"
    elif mutation == "slice_count":
        summary["slice_count"]["integer_value"] += 1
    elif mutation == "valid_slice_count":
        summary["valid_slice_count"]["integer_value"] += 1
    elif mutation == "sign_counts":
        summary["positive_mean_slice_count"]["integer_value"] += 1
    elif mutation == "ratios":
        summary["positive_mean_slice_ratio"]["decimal_value"] = "0.999999999999"
    elif mutation == "min_max":
        summary["min_slice_mean"]["decimal_value"] = "0.999999999999"
    elif mutation == "stddev":
        summary["stddev_of_slice_means"]["decimal_value"] = "0.999999999999"
    elif mutation == "metric_id":
        summary["slice_count"]["metric_id"] = "research.factor.ic.total_count@1"
    elif mutation == "value_kind":
        summary["stddev_of_slice_means"]["value_kind"] = "INTEGER"
    elif mutation == "unknown_schema":
        manifest["schema_version"] = 2
    elif mutation == "unknown_domain":
        manifest["domain"] = "UNKNOWN"
    elif mutation == "missing_summary_file":
        summary_path.unlink()
    elif mutation == "unexpected_file":
        (authority / "extra").write_text("x")
    else:  # pragma: no cover
        raise AssertionError(mutation)

    manifest_mutations = {
        "manifest_unknown_field",
        "manifest_statistics_fingerprint",
        "manifest_content_fingerprint",
        "manifest_result_fingerprint",
        "manifest_dataset",
        "manifest_source_logical",
        "manifest_source_result",
        "summary_byte_hash",
        "plan_summary_kind",
        "unknown_schema",
        "unknown_domain",
    }
    if mutation in manifest_mutations:
        manifest_path.write_text(only_canonical_json(manifest))
    elif mutation not in {"missing_summary_file", "unexpected_file"}:
        summary_path.write_text(only_canonical_json(summary))

    with pytest.raises(OnlyResearchStatisticsResultStoreError) as captured:
        case[12].load_verified(case[11].statistics_fingerprint)
    assert captured.value.code == "SUMMARY_STATISTICS_RESULT_CORRUPT"
