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
    OnlyResearchCoverageSummaryExecution,
    OnlyResearchStatisticRow,
    OnlyResearchStatisticsDisposition,
    OnlyResearchStatisticsMethod,
    OnlyResearchStatisticsResultReader,
    OnlyResearchStatisticsResultStoreError,
    OnlyResearchStatisticStatus,
    OnlyResearchSummaryScalarStatus,
    OnlyResearchSummaryStatisticsResult,
    only_compute_research_coverage_summary,
)
from onlyalpha.research.evaluation.errors import OnlyResearchEvaluationError
from onlyalpha.research.evaluation.summary import only_research_summary_result_content_fingerprint
from tests.research.evaluation.support import coverage_case, summary_case


def _source_with(source, rows):
    return replace(source, rows=tuple(rows))


def _row(timestamp: int, status: OnlyResearchStatisticStatus, sample_count: int):
    return OnlyResearchStatisticRow(
        timestamp,
        Decimal("0.1") if status is OnlyResearchStatisticStatus.VALID else None,
        sample_count,
        status,
    )


def test_coverage_summary_golden_observed_timestamp_and_pair_facts(tmp_path) -> None:
    case = coverage_case(tmp_path)
    source = case[8].load_verified(case[6].statistics_fingerprint)
    rows = (
        _row(1, OnlyResearchStatisticStatus.VALID, 10),
        _row(2, OnlyResearchStatisticStatus.VALID, 20),
        _row(3, OnlyResearchStatisticStatus.INSUFFICIENT_OBSERVATIONS, 5),
        _row(4, OnlyResearchStatisticStatus.ZERO_VARIANCE_FEATURE, 0),
        _row(5, OnlyResearchStatisticStatus.ZERO_VARIANCE_TARGET, 7),
    )
    summary = only_compute_research_coverage_summary(_source_with(source, rows), case[11])
    assert (
        summary.total_timestamp_count.integer_value,
        summary.valid_timestamp_count.integer_value,
        summary.insufficient_timestamp_count.integer_value,
        summary.zero_variance_feature_count.integer_value,
        summary.zero_variance_target_count.integer_value,
    ) == (5, 2, 1, 1, 1)
    assert summary.valid_timestamp_ratio.decimal_value == Decimal("0.400000000000")
    assert summary.pair_count_total.integer_value == 42
    assert summary.pair_count_mean.decimal_value == Decimal("8.400000000000")
    assert (summary.pair_count_min.integer_value, summary.pair_count_max.integer_value) == (0, 20)


def test_empty_and_all_invalid_nonempty_coverage_statuses_are_exact(tmp_path) -> None:
    case = coverage_case(tmp_path)
    source = case[8].load_verified(case[6].statistics_fingerprint)
    empty = only_compute_research_coverage_summary(_source_with(source, ()), case[11])
    for name in (
        "total_timestamp_count",
        "valid_timestamp_count",
        "insufficient_timestamp_count",
        "zero_variance_feature_count",
        "zero_variance_target_count",
        "pair_count_total",
    ):
        scalar = getattr(empty, name)
        assert scalar.status is OnlyResearchSummaryScalarStatus.VALID
        assert scalar.integer_value == 0
    for name in ("valid_timestamp_ratio", "pair_count_mean", "pair_count_min", "pair_count_max"):
        scalar = getattr(empty, name)
        assert scalar.status is OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS
        assert scalar.integer_value is None and scalar.decimal_value is None

    rows = (
        _row(1, OnlyResearchStatisticStatus.INSUFFICIENT_OBSERVATIONS, 2),
        _row(2, OnlyResearchStatisticStatus.ZERO_VARIANCE_FEATURE, 4),
        _row(3, OnlyResearchStatisticStatus.ZERO_VARIANCE_TARGET, 6),
    )
    invalid = only_compute_research_coverage_summary(_source_with(source, rows), case[11])
    assert invalid.valid_timestamp_count.integer_value == 0
    assert invalid.valid_timestamp_ratio.status is OnlyResearchSummaryScalarStatus.VALID
    assert invalid.valid_timestamp_ratio.decimal_value == Decimal("0.000000000000")
    assert invalid.pair_count_total.integer_value == 12
    assert invalid.pair_count_mean.decimal_value == Decimal("4.000000000000")


def test_pair_counts_include_invalid_rows_and_mean_uses_all_timestamps(tmp_path) -> None:
    case = coverage_case(tmp_path)
    source = case[8].load_verified(case[6].statistics_fingerprint)
    rows = (
        _row(1, OnlyResearchStatisticStatus.VALID, 100),
        _row(2, OnlyResearchStatisticStatus.INSUFFICIENT_OBSERVATIONS, 1),
    )
    summary = only_compute_research_coverage_summary(_source_with(source, rows), case[11])
    assert summary.pair_count_total.integer_value == 101
    assert summary.pair_count_mean.decimal_value == Decimal("50.500000000000")


def test_coverage_result_conservation_and_pair_bounds_fail_closed(tmp_path) -> None:
    case = coverage_case(tmp_path)
    source = case[8].load_verified(case[6].statistics_fingerprint)
    summary = only_compute_research_coverage_summary(source, case[11])
    with pytest.raises(ValueError, match="status counts"):
        replace(
            summary,
            valid_timestamp_count=replace(
                summary.valid_timestamp_count,
                integer_value=(summary.valid_timestamp_count.integer_value or 0) + 1,
            ),
        )
    with pytest.raises(ValueError, match="bounds"):
        replace(
            summary,
            pair_count_min=replace(summary.pair_count_min, integer_value=1000),
            pair_count_max=replace(summary.pair_count_max, integer_value=1),
        )


def test_coverage_decimal_poisoning_cannot_change_values_or_identity(tmp_path) -> None:
    case = coverage_case(tmp_path)
    source = case[8].load_verified(case[6].statistics_fingerprint)
    rows = (
        _row(1, OnlyResearchStatisticStatus.VALID, 1),
        _row(2, OnlyResearchStatisticStatus.INSUFFICIENT_OBSERVATIONS, 2),
        _row(3, OnlyResearchStatisticStatus.VALID, 2),
    )
    source = _source_with(source, rows)
    expected = only_compute_research_coverage_summary(source, case[11])
    identity = case[11].statistics_fingerprint
    with localcontext() as context:
        context.prec = 4
        context.rounding = ROUND_DOWN
        context.Emin = -5
        context.Emax = 5
        context.clamp = 1
        context.traps[Inexact] = True
        context.flags[Rounded] = True
        actual = only_compute_research_coverage_summary(source, case[11])
    assert actual == expected
    assert case[11].statistics_fingerprint == identity


def test_coverage_executor_commits_then_reuses_and_rank_ic_is_typed(tmp_path) -> None:
    case = coverage_case(tmp_path)
    first = case[13].execute(case[11])
    second = case[13].execute(case[11])
    assert first.disposition is OnlyResearchStatisticsDisposition.EXECUTED
    assert second.disposition is OnlyResearchStatisticsDisposition.REUSED
    assert first.statistics_result_fingerprint == second.statistics_result_fingerprint

    rank_case = coverage_case(tmp_path / "rank", OnlyResearchStatisticsMethod.RANK_IC)
    rank = rank_case[13].execute(rank_case[11])
    loaded = rank_case[12].load_verified(rank.statistics_fingerprint)
    assert loaded.summary.valid_timestamp_ratio.metric_id == "research.factor.rank_ic.coverage.valid_timestamp_ratio@1"


def test_shared_store_and_reader_coexist_for_effect_and_coverage(tmp_path) -> None:
    effect = summary_case(tmp_path)
    effect_outcome = effect[13].execute(effect[11])
    source = effect[8].load_verified(effect[6].statistics_fingerprint)
    coverage = coverage_case(tmp_path)
    coverage_outcome = coverage[13].execute(coverage[11])
    assert effect_outcome.statistics_fingerprint != coverage_outcome.statistics_fingerprint
    reader = OnlyResearchStatisticsResultReader(tmp_path / "statistics-results", effect[8], effect[12])
    assert reader.load_verified(source.manifest.statistics_fingerprint) == source
    assert isinstance(reader.load_verified(effect_outcome.statistics_fingerprint), OnlyResearchSummaryStatisticsResult)
    assert isinstance(
        reader.load_verified(coverage_outcome.statistics_fingerprint), OnlyResearchSummaryStatisticsResult
    )


def test_coverage_identity_sensitivity_and_source_result_layering(tmp_path) -> None:
    case = coverage_case(tmp_path)
    plan = case[11]
    changes = (
        replace(plan, dataset_snapshot_fingerprint="1" * 64),
        replace(plan, subject_candidate_fingerprint="2" * 64),
        replace(plan, subject=replace(plan.subject, output_name="other")),
        replace(plan, source_statistics_fingerprint="3" * 64),
        replace(
            plan,
            definition=replace(plan.definition, source_method=OnlyResearchStatisticsMethod.RANK_IC),
        ),
    )
    assert all(item.statistics_fingerprint != plan.statistics_fingerprint for item in changes)
    changed_result = replace(plan, source_statistics_result_fingerprint="4" * 64)
    assert changed_result.statistics_fingerprint == plan.statistics_fingerprint
    payload = {"fixed": "coverage"}
    assert only_research_summary_result_content_fingerprint(
        plan.source_statistics_fingerprint,
        plan.source_statistics_result_fingerprint,
        payload,
    ) != only_research_summary_result_content_fingerprint(
        changed_result.source_statistics_fingerprint,
        changed_result.source_statistics_result_fingerprint,
        payload,
    )


def test_coverage_source_bindings_fail_closed(tmp_path) -> None:
    case = coverage_case(tmp_path)
    source = case[8].load_verified(case[6].statistics_fingerprint)
    mutations = (
        replace(case[11], dataset_snapshot_fingerprint="1" * 64),
        replace(case[11], subject=replace(case[11].subject, output_name="other")),
        replace(case[11], source_statistics_fingerprint="3" * 64),
        replace(case[11], source_statistics_result_fingerprint="2" * 64),
        replace(
            case[11],
            definition=replace(case[11].definition, source_method=OnlyResearchStatisticsMethod.RANK_IC),
        ),
    )
    for plan in mutations:
        with pytest.raises(OnlyResearchEvaluationError):
            only_compute_research_coverage_summary(source, plan)


def test_fresh_process_coverage_identity_and_persisted_reuse_are_stable(tmp_path) -> None:
    case = coverage_case(tmp_path)
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
    OnlyResearchCoverageSummaryExecutor, OnlyResearchCoverageSummaryPlan,
)
root = Path(sys.argv[1])
payload = json.loads(Path(sys.argv[2]).read_text())
plan = OnlyResearchCoverageSummaryPlan.from_dict(payload["plan"])
datasets = OnlyParquetResearchDatasetSnapshotStore(root / "datasets")
calculations = OnlyParquetResearchCalculationResultStore(root / "calculation-results", datasets)
legacy = OnlyParquetResearchStatisticsResultStore(root / "statistics-results", calculations)
summaries = OnlyJsonResearchSummaryStatisticsResultStore(root / "statistics-results", legacy)
outcome = OnlyResearchCoverageSummaryExecutor(legacy, summaries).execute(plan)
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


def test_coverage_deterministic_conflict_never_overwrites(tmp_path) -> None:
    case = coverage_case(tmp_path)
    case[13].execute(case[11])
    loaded = case[12].load_verified(case[11].statistics_fingerprint)
    changed = replace(
        loaded.summary,
        pair_count_total=replace(
            loaded.summary.pair_count_total,
            integer_value=(loaded.summary.pair_count_total.integer_value or 0) + 1,
        ),
    )
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as captured:
        case[12].commit(OnlyResearchCoverageSummaryExecution(case[11], changed))
    assert captured.value.code == "DETERMINISTIC_RESULT_CONFLICT"


def test_b3_0_2_coverage_identities_and_canonical_payloads_are_pinned(tmp_path) -> None:
    case = coverage_case(tmp_path)
    case[13].execute(case[11])
    loaded = case[12].load_verified(case[11].statistics_fingerprint)

    def canonical_sha(payload: object) -> str:
        return hashlib.sha256(only_canonical_json(payload).encode()).hexdigest()

    assert case[11].statistics_fingerprint == "adfdc933cb0e3f127de4d7a80cd8e36ffe5b5aada1f450d8c21656920add07dd"
    assert loaded.manifest.result_content_fingerprint == (
        "05bb370907f742f220d0a9079da83f44efba6cb2dbb9d79249d7dfe81e44dde1"
    )
    assert loaded.manifest.statistics_result_fingerprint == (
        "81d5b28fe8495a2621b42198836b2dd123d9ff772522df1fc28edf8306e11e2f"
    )
    assert canonical_sha(case[11].to_dict()) == "7ebbf54b4e76e90aa4bc41f7add7ff17f453736d3c22a98b204afa2aa38b91bc"
    assert canonical_sha(loaded.summary.to_dict()) == (
        "49bf8a817f6b1d9f49b3250e3a9ca786079af5c9f5091d2e6e074c7adebbfe60"
    )
    assert canonical_sha(loaded.manifest.to_dict()) == (
        "9422558832ccb6b4e651e40392d23b01cd2e3931ff09750e484af07c45909251"
    )
