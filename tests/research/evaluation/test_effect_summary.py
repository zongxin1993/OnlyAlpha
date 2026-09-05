from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from decimal import ROUND_DOWN, Decimal, Inexact, Rounded, localcontext

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research import (
    OnlyResearchStatisticRow,
    OnlyResearchStatisticsDisposition,
    OnlyResearchStatisticsMethod,
    OnlyResearchStatisticStatus,
    OnlyResearchSummaryScalarStatus,
    only_compute_research_effect_summary,
)
from onlyalpha.research.evaluation.errors import OnlyResearchEvaluationError
from tests.research.evaluation.support import summary_case


def _source_with(source, rows):
    return replace(source, rows=tuple(rows))


def _row(timestamp: int, value: str | None, status=OnlyResearchStatisticStatus.VALID):
    return OnlyResearchStatisticRow(
        timestamp,
        None if value is None else Decimal(value),
        3,
        status,
    )


def test_effect_summary_golden_mean_sample_stddev_and_nonannualized_ir(tmp_path) -> None:
    case = summary_case(tmp_path)
    source = case[8].load_verified(case[6].statistics_fingerprint)
    summary = only_compute_research_effect_summary(
        _source_with(source, (_row(1, "0.1"), _row(2, "0.2"), _row(3, "0.3"))), case[11]
    )
    assert summary.mean.decimal_value == Decimal("0.200000000000")
    assert summary.stddev_sample.decimal_value == Decimal("0.100000000000")
    assert summary.information_ratio.decimal_value == Decimal("2.000000000000")


def test_effect_summary_sign_counts_ratios_and_mixed_invalid_rows(tmp_path) -> None:
    case = summary_case(tmp_path)
    source = case[8].load_verified(case[6].statistics_fingerprint)
    rows = (
        _row(1, "-0.1"),
        _row(2, "0"),
        _row(3, None, OnlyResearchStatisticStatus.ZERO_VARIANCE_FEATURE),
        _row(4, "0.2"),
    )
    summary = only_compute_research_effect_summary(_source_with(source, rows), case[11])
    assert (
        summary.positive_count.integer_value,
        summary.negative_count.integer_value,
        summary.zero_count.integer_value,
    ) == (1, 1, 1)
    assert summary.valid_count.integer_value == 3
    assert summary.zero_variance_feature_count.integer_value == 1
    third = Decimal("0.333333333333")
    assert (
        summary.positive_ratio.decimal_value,
        summary.negative_ratio.decimal_value,
        summary.zero_ratio.decimal_value,
    ) == (third, third, third)
    assert summary.mean.decimal_value == Decimal("0.033333333333")


def test_all_invalid_single_observation_and_zero_variance_statuses_are_exact(tmp_path) -> None:
    case = summary_case(tmp_path)
    source = case[8].load_verified(case[6].statistics_fingerprint)
    invalid_rows = (
        _row(1, None, OnlyResearchStatisticStatus.INSUFFICIENT_OBSERVATIONS),
        _row(2, None, OnlyResearchStatisticStatus.ZERO_VARIANCE_FEATURE),
        _row(3, None, OnlyResearchStatisticStatus.ZERO_VARIANCE_TARGET),
    )
    invalid = only_compute_research_effect_summary(_source_with(source, invalid_rows), case[11])
    assert invalid.total_count.integer_value == 3
    assert invalid.valid_count.integer_value == 0
    assert invalid.mean.status is OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
    assert invalid.positive_ratio.status is OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
    assert invalid.stddev_sample.status is OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS
    assert invalid.information_ratio.status is OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS
    assert invalid.mean.decimal_value is None

    single = only_compute_research_effect_summary(_source_with(source, (_row(1, "0.05"),)), case[11])
    assert single.mean.decimal_value == Decimal("0.050000000000")
    assert single.stddev_sample.status is OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS

    constant = only_compute_research_effect_summary(
        _source_with(source, (_row(1, "0.05"), _row(2, "0.05"), _row(3, "0.05"))), case[11]
    )
    assert constant.stddev_sample.status is OnlyResearchSummaryScalarStatus.VALID
    assert constant.stddev_sample.decimal_value == Decimal("0E-12")
    assert constant.information_ratio.status is OnlyResearchSummaryScalarStatus.ZERO_VARIANCE
    assert constant.information_ratio.decimal_value is None


def test_rounded_zero_stddev_does_not_masquerade_as_exact_zero_variance(tmp_path) -> None:
    case = summary_case(tmp_path)
    source = case[8].load_verified(case[6].statistics_fingerprint)
    rows = tuple(_row(index, "0") for index in range(1, 10)) + (_row(10, "0.000000000001"),)
    summary = only_compute_research_effect_summary(_source_with(source, rows), case[11])
    assert summary.stddev_sample.decimal_value == Decimal("0E-12")
    assert summary.information_ratio.status is OnlyResearchSummaryScalarStatus.VALID
    assert summary.information_ratio.decimal_value == Decimal("0.316227766017")


def test_ambient_decimal_poisoning_cannot_change_summary_or_identity(tmp_path) -> None:
    case = summary_case(tmp_path)
    source = case[8].load_verified(case[6].statistics_fingerprint)
    source = _source_with(source, (_row(1, "0.1"), _row(2, "0.2"), _row(3, "0.3")))
    expected = only_compute_research_effect_summary(source, case[11])
    with localcontext() as context:
        context.prec = 4
        context.rounding = ROUND_DOWN
        context.Emin = -5
        context.Emax = 5
        context.clamp = 1
        context.traps[Inexact] = True
        context.flags[Rounded] = True
        actual = only_compute_research_effect_summary(source, case[11])
    assert actual == expected
    assert case[11].statistics_fingerprint == case[11].statistics_fingerprint


def test_executor_commits_then_reuses_exact_verified_summary(tmp_path) -> None:
    case = summary_case(tmp_path)
    first = case[13].execute(case[11])
    second = case[13].execute(case[11])
    assert first.disposition is OnlyResearchStatisticsDisposition.EXECUTED
    assert second.disposition is OnlyResearchStatisticsDisposition.REUSED
    assert first.statistics_result_fingerprint == second.statistics_result_fingerprint
    loaded = case[12].load_verified(case[11].statistics_fingerprint)
    assert loaded.manifest.plan == case[11]


def test_rank_ic_source_produces_rank_ic_typed_metrics(tmp_path) -> None:
    case = summary_case(tmp_path, OnlyResearchStatisticsMethod.RANK_IC)
    outcome = case[13].execute(case[11])
    loaded = case[12].load_verified(outcome.statistics_fingerprint)
    assert loaded.summary.source_method is OnlyResearchStatisticsMethod.RANK_IC
    assert loaded.summary.mean.metric_id == "research.factor.rank_ic.mean@1"


def test_source_dataset_method_factor_and_result_bindings_fail_closed(tmp_path) -> None:
    case = summary_case(tmp_path)
    source = case[8].load_verified(case[6].statistics_fingerprint)
    mutations = (
        replace(case[11], dataset_snapshot_fingerprint="1" * 64),
        replace(case[11], subject=replace(case[11].subject, output_name="other")),
        replace(case[11], source_statistics_fingerprint="3" * 64),
        replace(case[11], source_statistics_result_fingerprint="2" * 64),
        replace(
            case[11],
            definition=replace(case[11].definition, source_method=type(case[11].definition.source_method).RANK_IC),
        ),
    )
    for plan in mutations:
        with pytest.raises(OnlyResearchEvaluationError):
            only_compute_research_effect_summary(source, plan)


def test_fresh_process_plan_identity_and_persisted_reuse_are_stable(tmp_path) -> None:
    case = summary_case(tmp_path)
    first = case[13].execute(case[11])
    manifest_path = (
        tmp_path
        / "statistics-results"
        / "sha256"
        / case[11].statistics_fingerprint[:2]
        / case[11].statistics_fingerprint
        / "manifest.json"
    )
    script = r"""
import json, sys
from pathlib import Path
from onlyalpha.research import (
    OnlyJsonResearchSummaryStatisticsResultStore, OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore, OnlyParquetResearchStatisticsResultStore,
    OnlyResearchEffectSummaryExecutor, OnlyResearchEffectSummaryPlan,
)
root = Path(sys.argv[1])
payload = json.loads(Path(sys.argv[2]).read_text())
plan = OnlyResearchEffectSummaryPlan.from_dict(payload["plan"])
datasets = OnlyParquetResearchDatasetSnapshotStore(root / "datasets")
calculations = OnlyParquetResearchCalculationResultStore(root / "calculation-results", datasets)
legacy = OnlyParquetResearchStatisticsResultStore(root / "statistics-results", calculations)
summaries = OnlyJsonResearchSummaryStatisticsResultStore(root / "statistics-results", legacy)
outcome = OnlyResearchEffectSummaryExecutor(legacy, summaries).execute(plan)
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
    payload = json.loads(completed.stdout)
    assert payload == {
        "logical": case[11].statistics_fingerprint,
        "result": first.statistics_result_fingerprint,
        "disposition": "REUSED",
    }


def test_b3_0_1_effect_identities_and_canonical_payloads_are_pinned(tmp_path) -> None:
    case = summary_case(tmp_path)
    case[13].execute(case[11])
    loaded = case[12].load_verified(case[11].statistics_fingerprint)

    def canonical_sha(payload: object) -> str:
        return hashlib.sha256(only_canonical_json(payload).encode()).hexdigest()

    assert case[11].statistics_fingerprint == "869301b91160a95029ce6c1150d52f525016b6a15e244bcc6e4fe20a709ecc5e"
    assert loaded.manifest.result_content_fingerprint == (
        "a7f8ad66f4e07d174b2e242faf2e26781d8bbd48b3ae7f7d874426e98870955f"
    )
    assert loaded.manifest.statistics_result_fingerprint == (
        "0ae0f83b091d95e4eb8921d4c991f0bcca98a8d86f689b102a0d29e529c045a1"
    )
    assert canonical_sha(case[11].to_dict()) == "1d6570e48f129863b62db6db9ee2438f3f73c93d92ea840a6becdd1bae72ff9d"
    assert canonical_sha(loaded.summary.to_dict()) == (
        "8809f819090d139cc055e546dc566fb35a00d616cc8565f1addb8437192ca607"
    )
    assert canonical_sha(loaded.manifest.to_dict()) == (
        "a0f350fd59345ac6d9a9b7ed2fc2c4a33d15d53f0f39dad0d89f50e6d396e26b"
    )
