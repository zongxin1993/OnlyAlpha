from __future__ import annotations

import json
from pathlib import Path

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research import OnlyResearchStatisticsResultStoreError
from tests.research.evaluation.support import coverage_case


def _result_root(root: Path, fingerprint: str) -> Path:
    return root / "statistics-results" / "sha256" / fingerprint[:2] / fingerprint


@pytest.mark.parametrize(
    "mutation",
    (
        "manifest_unknown_field",
        "manifest_statistics_fingerprint",
        "manifest_content_fingerprint",
        "manifest_result_fingerprint",
        "manifest_dataset_fingerprint",
        "manifest_source_logical_fingerprint",
        "manifest_source_result_fingerprint",
        "summary_byte_hash",
        "plan_summary_kind",
        "summary_kind",
        "metric_id",
        "value_kind",
        "total_timestamp_count",
        "valid_timestamp_count",
        "invalid_status_counts",
        "valid_ratio_status",
        "pair_count_total",
        "pair_count_mean",
        "pair_count_min_max",
        "missing_summary_file",
        "unexpected_file",
        "unknown_schema",
        "unknown_domain",
    ),
)
def test_coverage_corruption_matrix_fails_closed_as_corrupt(tmp_path, mutation: str) -> None:
    root = tmp_path / mutation
    case = coverage_case(root)
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
    elif mutation == "manifest_dataset_fingerprint":
        manifest["dataset_snapshot_fingerprint"] = "4" * 64
    elif mutation == "manifest_source_logical_fingerprint":
        manifest["source_statistics_fingerprint"] = "5" * 64
    elif mutation == "manifest_source_result_fingerprint":
        manifest["source_statistics_result_fingerprint"] = "6" * 64
    elif mutation == "summary_byte_hash":
        manifest["summary_byte_sha256"] = "7" * 64
    elif mutation == "plan_summary_kind":
        manifest["plan"]["definition"]["summary_kind"] = "TEMPORAL_STABILITY"
    elif mutation == "summary_kind":
        summary["summary_kind"] = "EFFECT_SUMMARY"
    elif mutation == "metric_id":
        summary["pair_count_total"]["metric_id"] = "research.factor.ic.total_count@1"
    elif mutation == "value_kind":
        summary["pair_count_mean"]["value_kind"] = "INTEGER"
    elif mutation == "total_timestamp_count":
        summary["total_timestamp_count"]["integer_value"] += 1
    elif mutation == "valid_timestamp_count":
        summary["valid_timestamp_count"]["integer_value"] += 1
    elif mutation == "invalid_status_counts":
        summary["insufficient_timestamp_count"]["status"] = "NO_VALID_OBSERVATIONS"
        summary["insufficient_timestamp_count"]["integer_value"] = None
    elif mutation == "valid_ratio_status":
        summary["valid_timestamp_ratio"]["status"] = "NO_VALID_OBSERVATIONS"
        summary["valid_timestamp_ratio"]["decimal_value"] = None
    elif mutation == "pair_count_total":
        summary["pair_count_total"]["integer_value"] += 1
    elif mutation == "pair_count_mean":
        summary["pair_count_mean"]["decimal_value"] = "999.000000000000"
    elif mutation == "pair_count_min_max":
        summary["pair_count_min"]["integer_value"] = 1000
        summary["pair_count_max"]["integer_value"] = 1
    elif mutation == "missing_summary_file":
        summary_path.unlink()
    elif mutation == "unexpected_file":
        (authority / "extra").write_text("x")
    elif mutation == "unknown_schema":
        manifest["schema_version"] = 2
    elif mutation == "unknown_domain":
        manifest["domain"] = "UNKNOWN"
    else:  # pragma: no cover
        raise AssertionError(mutation)

    if mutation.startswith("manifest_") or mutation in {
        "summary_byte_hash",
        "plan_summary_kind",
        "unknown_schema",
        "unknown_domain",
    }:
        manifest_path.write_text(only_canonical_json(manifest))
    elif mutation not in {"missing_summary_file", "unexpected_file"}:
        summary_path.write_text(only_canonical_json(summary))

    with pytest.raises(OnlyResearchStatisticsResultStoreError) as captured:
        case[12].load_verified(case[11].statistics_fingerprint)
    assert captured.value.code == "SUMMARY_STATISTICS_RESULT_CORRUPT"


def test_unknown_summary_kind_is_not_inferred_from_coverage_fields(tmp_path) -> None:
    case = coverage_case(tmp_path)
    case[13].execute(case[11])
    authority = _result_root(tmp_path, case[11].statistics_fingerprint)
    summary_path = authority / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary["summary_kind"] = "TEMPORAL_STABILITY"
    summary_path.write_text(only_canonical_json(summary))
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as captured:
        case[12].load_verified(case[11].statistics_fingerprint)
    assert captured.value.code == "SUMMARY_STATISTICS_RESULT_CORRUPT"
