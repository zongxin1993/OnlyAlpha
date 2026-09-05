from __future__ import annotations

import json
import shutil
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research import (
    OnlyResearchEffectSummaryExecution,
    OnlyResearchStatisticsResultReader,
    OnlyResearchStatisticsResultStoreError,
    OnlyResearchSummaryScalar,
    OnlyResearchSummaryScalarStatus,
    OnlyResearchSummaryStatisticsResult,
    OnlyResearchSummaryValueKind,
)
from tests.research.evaluation.support import summary_case


def _result_root(root: Path, fingerprint: str) -> Path:
    return root / "statistics-results" / "sha256" / fingerprint[:2] / fingerprint


def test_summary_store_deterministic_conflict_never_overwrites(tmp_path) -> None:
    case = summary_case(tmp_path)
    case[13].execute(case[11])
    loaded = case[12].load_verified(case[11].statistics_fingerprint)
    changed_mean = replace(loaded.summary.mean, decimal_value=Decimal("0.999999999999"))
    changed = replace(loaded.summary, mean=changed_mean)
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as captured:
        case[12].commit(OnlyResearchEffectSummaryExecution(case[11], changed))
    assert captured.value.code == "DETERMINISTIC_RESULT_CONFLICT"
    assert case[12].load_verified(case[11].statistics_fingerprint) == loaded


def test_typed_reader_dispatches_legacy_and_summary_without_exception_guessing(tmp_path) -> None:
    case = summary_case(tmp_path)
    case[13].execute(case[11])
    reader = OnlyResearchStatisticsResultReader(tmp_path / "statistics-results", case[8], case[12])
    legacy = reader.load_verified(case[6].statistics_fingerprint)
    summary = reader.load_verified(case[11].statistics_fingerprint)
    assert legacy.manifest.statistics_fingerprint == case[6].statistics_fingerprint
    assert isinstance(summary, OnlyResearchSummaryStatisticsResult)
    root = _result_root(tmp_path, case[11].statistics_fingerprint)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["domain"] = "UNKNOWN"
    (root / "manifest.json").write_text(only_canonical_json(manifest))
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as captured:
        reader.load_verified(case[11].statistics_fingerprint)
    assert captured.value.code == "STATISTICS_RESULT_SCHEMA_UNSUPPORTED"


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
        "summary_semantic_payload",
        "missing_summary_file",
        "unexpected_file",
        "unknown_schema",
        "unknown_domain",
        "invalid_scalar_status_value",
        "invalid_metric_id",
        "wrong_metric_value_kind",
    ),
)
def test_summary_corruption_matrix_fails_closed_as_corrupt(tmp_path, mutation: str) -> None:
    root = tmp_path / mutation
    case = summary_case(root)
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
    elif mutation == "summary_semantic_payload":
        summary["mean"]["decimal_value"] = "0.999999999999"
    elif mutation == "missing_summary_file":
        summary_path.unlink()
    elif mutation == "unexpected_file":
        (authority / "extra").write_text("x")
    elif mutation == "unknown_schema":
        manifest["schema_version"] = 2
    elif mutation == "unknown_domain":
        manifest["domain"] = "UNKNOWN"
    elif mutation == "invalid_scalar_status_value":
        summary["mean"]["status"] = "ZERO_VARIANCE"
    elif mutation == "invalid_metric_id":
        summary["mean"]["metric_id"] = "unknown@1"
    elif mutation == "wrong_metric_value_kind":
        summary["mean"]["value_kind"] = "INTEGER"
    else:  # pragma: no cover
        raise AssertionError(mutation)

    if mutation.startswith("manifest_") or mutation in {"summary_byte_hash", "unknown_schema", "unknown_domain"}:
        manifest_path.write_text(only_canonical_json(manifest))
    elif mutation not in {"missing_summary_file", "unexpected_file"}:
        summary_path.write_text(only_canonical_json(summary))

    with pytest.raises(OnlyResearchStatisticsResultStoreError) as captured:
        case[12].load_verified(case[11].statistics_fingerprint)
    assert captured.value.code == "SUMMARY_STATISTICS_RESULT_CORRUPT"


def test_non_valid_corrupt_scalar_cannot_be_constructed() -> None:
    with pytest.raises(ValueError):
        OnlyResearchSummaryScalar(
            "research.factor.ic.mean@1",
            OnlyResearchSummaryValueKind.DECIMAL,
            OnlyResearchSummaryScalarStatus.ZERO_VARIANCE,
            decimal_value=Decimal(0),
        )


def test_existing_summary_with_missing_upstream_is_corrupt_not_missing(tmp_path) -> None:
    case = summary_case(tmp_path)
    case[13].execute(case[11])
    shutil.rmtree(_result_root(tmp_path, case[6].statistics_fingerprint))
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as captured:
        case[12].load_verified(case[11].statistics_fingerprint)
    assert captured.value.code == "SUMMARY_STATISTICS_RESULT_CORRUPT"
