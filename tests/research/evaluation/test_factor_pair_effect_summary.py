from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, getcontext, localcontext

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research import (
    OnlyJsonResearchSummaryStatisticsResultStore,
    OnlyResearchFactorPairEffectSummaryExecution,
    OnlyResearchFactorPairEffectSummaryPlan,
    OnlyResearchFactorPairStatisticRow,
    OnlyResearchFactorPairStatisticsMethod,
    OnlyResearchFactorPairStatisticStatus,
    OnlyResearchStatisticsDisposition,
    OnlyResearchStatisticsResultStoreError,
    OnlyResearchSummaryScalarStatus,
    only_compute_research_factor_pair_effect_summary,
)
from onlyalpha.research.evaluation.errors import OnlyResearchEvaluationError
from tests.research.evaluation.support import factor_pair_effect_case, summary_case


def _source_with_values(case, values: tuple[Decimal | None, ...]):
    source = case[10].load_verified(case[9].statistics_fingerprint)
    rows = tuple(
        OnlyResearchFactorPairStatisticRow(
            index,
            value,
            3 if value is not None else 1,
            (
                OnlyResearchFactorPairStatisticStatus.VALID
                if value is not None
                else OnlyResearchFactorPairStatisticStatus.INSUFFICIENT_OBSERVATIONS
            ),
        )
        for index, value in enumerate(values)
    )
    return replace(source, rows=rows)


@pytest.mark.parametrize(
    ("values", "mean", "mean_status", "stddev", "stddev_status"),
    (
        (
            (Decimal("0.2"), Decimal("0.4"), Decimal("0.6")),
            Decimal("0.400000000000"),
            OnlyResearchSummaryScalarStatus.VALID,
            Decimal("0.200000000000"),
            OnlyResearchSummaryScalarStatus.VALID,
        ),
        (
            (Decimal("0.2"), None, Decimal("0.6")),
            Decimal("0.400000000000"),
            OnlyResearchSummaryScalarStatus.VALID,
            Decimal("0.282842712475"),
            OnlyResearchSummaryScalarStatus.VALID,
        ),
        (
            (None, None),
            None,
            OnlyResearchSummaryScalarStatus.NO_VALID_OBSERVATIONS,
            None,
            OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS,
        ),
        (
            (Decimal("0.8"),),
            Decimal("0.800000000000"),
            OnlyResearchSummaryScalarStatus.VALID,
            None,
            OnlyResearchSummaryScalarStatus.INSUFFICIENT_OBSERVATIONS,
        ),
        (
            (Decimal("0.8"), Decimal("0.8"), Decimal("0.8")),
            Decimal("0.800000000000"),
            OnlyResearchSummaryScalarStatus.VALID,
            Decimal("0.000000000000"),
            OnlyResearchSummaryScalarStatus.VALID,
        ),
    ),
)
def test_factor_pair_effect_valid_only_mean_and_sample_stddev(
    tmp_path, values, mean, mean_status, stddev, stddev_status
) -> None:
    case = factor_pair_effect_case(tmp_path)
    summary = only_compute_research_factor_pair_effect_summary(_source_with_values(case, values), case[13])
    assert (summary.mean.decimal_value, summary.mean.status) == (mean, mean_status)
    assert (summary.stddev_sample.decimal_value, summary.stddev_sample.status) == (stddev, stddev_status)


def test_factor_pair_effect_decimal_context_poisoning_is_irrelevant(tmp_path) -> None:
    case = factor_pair_effect_case(tmp_path)
    source = _source_with_values(case, (Decimal("0.2"), Decimal("0.4"), Decimal("0.6")))
    expected = only_compute_research_factor_pair_effect_summary(source, case[13])
    caller = getcontext()
    flags_before = dict(caller.flags)
    with localcontext() as poisoned:
        poisoned.prec = 3
        poisoned.rounding = "ROUND_UP"
        poisoned.Emin = -9
        poisoned.Emax = 9
        for signal in poisoned.traps:
            poisoned.traps[signal] = False
        actual = only_compute_research_factor_pair_effect_summary(source, case[13])
    assert actual == expected
    assert dict(caller.flags) == flags_before


def test_factor_pair_rank_correlation_uses_exact_rank_metric_namespace(tmp_path) -> None:
    case = factor_pair_effect_case(tmp_path, OnlyResearchFactorPairStatisticsMethod.FACTOR_RANK_CORRELATION)
    result = case[14].commit(
        OnlyResearchFactorPairEffectSummaryExecution(
            case[13],
            only_compute_research_factor_pair_effect_summary(
                case[10].load_verified(case[9].statistics_fingerprint), case[13]
            ),
        )
    )
    assert result.summary.mean.metric_id == "research.factor_pair.rank_correlation.mean@1"
    assert result.summary.stddev_sample.metric_id == "research.factor_pair.rank_correlation.stddev_sample@1"


def test_factor_pair_effect_store_execute_reuse_and_dependency_layering(tmp_path) -> None:
    case = factor_pair_effect_case(tmp_path)
    plan, store, executor = case[13], case[14], case[15]
    first = executor.execute(plan)
    second = executor.execute(
        OnlyResearchFactorPairEffectSummaryPlan(
            plan.dataset_snapshot_fingerprint,
            plan.second_operand,
            plan.first_operand,
            plan.source_statistics_fingerprint,
            plan.source_statistics_result_fingerprint,
            plan.definition,
        )
    )
    assert first.disposition is OnlyResearchStatisticsDisposition.EXECUTED
    assert second.disposition is OnlyResearchStatisticsDisposition.REUSED
    assert second.statistics_result_fingerprint == first.statistics_result_fingerprint
    changed_dependency = replace(plan, source_statistics_result_fingerprint="f" * 64)
    assert changed_dependency.statistics_fingerprint == plan.statistics_fingerprint
    loaded = store.load_verified(plan.statistics_fingerprint)
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as captured:
        store.commit(OnlyResearchFactorPairEffectSummaryExecution(changed_dependency, loaded.summary))
    assert captured.value.code == "DETERMINISTIC_RESULT_CONFLICT"


def test_factor_pair_effect_fresh_process_swapped_reuse(tmp_path) -> None:
    case = factor_pair_effect_case(tmp_path)
    plan, executor = case[13], case[15]
    first = executor.execute(plan)
    plan_path = tmp_path / "pair-effect-plan.json"
    plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
    script = r"""
import json, sys
from pathlib import Path
from onlyalpha.research import *
root = Path(sys.argv[1])
canonical = OnlyResearchFactorPairEffectSummaryPlan.from_dict(json.loads((root / "pair-effect-plan.json").read_text()))
plan = OnlyResearchFactorPairEffectSummaryPlan(
    canonical.dataset_snapshot_fingerprint, canonical.second_operand, canonical.first_operand,
    canonical.source_statistics_fingerprint, canonical.source_statistics_result_fingerprint, canonical.definition,
)
datasets = OnlyParquetResearchDatasetSnapshotStore(root / "datasets")
calculations = OnlyParquetResearchCalculationResultStore(root / "calculation-results", datasets)
legacy = OnlyParquetResearchStatisticsResultStore(root / "statistics-results", calculations)
pairs = OnlyParquetResearchFactorPairStatisticsResultStore(root / "statistics-results", calculations)
summaries = OnlyJsonResearchSummaryStatisticsResultStore(
    root / "statistics-results", legacy, factor_pair_source_store=pairs
)
outcome = OnlyResearchFactorPairEffectSummaryExecutor(pairs, summaries).execute(plan)
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


def test_factor_pair_effect_missing_pair_store_and_wrong_family_fail_closed(tmp_path) -> None:
    case = factor_pair_effect_case(tmp_path)
    plan = case[13]
    legacy_only = OnlyJsonResearchSummaryStatisticsResultStore(
        tmp_path / "other-statistics-results",
        case[8],
        audit_time=lambda: datetime(2026, 9, 5, tzinfo=UTC),
    )
    source = case[10].load_verified(plan.source_statistics_fingerprint)
    summary = only_compute_research_factor_pair_effect_summary(source, plan)
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as captured:
        legacy_only.commit(OnlyResearchFactorPairEffectSummaryExecution(plan, summary))
    assert captured.value.code == "SUMMARY_FACTOR_PAIR_SOURCE_STORE_NOT_CONFIGURED"
    case[15].execute(plan)
    configured_without_pair = OnlyJsonResearchSummaryStatisticsResultStore(tmp_path / "statistics-results", case[8])
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as load_error:
        configured_without_pair.load_verified(plan.statistics_fingerprint)
    assert load_error.value.code == "SUMMARY_FACTOR_PAIR_SOURCE_STORE_NOT_CONFIGURED"
    legacy = summary_case(tmp_path / "legacy")
    legacy_source = legacy[8].load_verified(legacy[6].statistics_fingerprint)
    with pytest.raises(OnlyResearchEvaluationError, match="SOURCE_SCHEMA_UNSUPPORTED"):
        only_compute_research_factor_pair_effect_summary(legacy_source, plan)  # type: ignore[arg-type]


def test_factor_pair_effect_exact_source_bindings_fail_closed(tmp_path) -> None:
    case = factor_pair_effect_case(tmp_path)
    source, plan = case[10].load_verified(case[9].statistics_fingerprint), case[13]
    for changed in (
        replace(plan, dataset_snapshot_fingerprint="1" * 64),
        replace(plan, source_statistics_fingerprint="2" * 64),
        replace(plan, source_statistics_result_fingerprint="3" * 64),
        replace(plan, first_operand=replace(plan.first_operand, candidate_fingerprint="4" * 64)),
        replace(plan, second_operand=replace(plan.second_operand, candidate_fingerprint="5" * 64)),
        replace(
            plan,
            definition=replace(
                plan.definition,
                source_method=OnlyResearchFactorPairStatisticsMethod.FACTOR_RANK_CORRELATION,
            ),
        ),
    ):
        with pytest.raises(OnlyResearchEvaluationError):
            only_compute_research_factor_pair_effect_summary(source, changed)


@pytest.mark.parametrize(
    "mutation",
    (
        "manifest_unknown",
        "manifest_kind",
        "plan_method",
        "plan_dataset",
        "plan_first_operand",
        "plan_second_operand",
        "source_logical",
        "source_result",
        "summary_hash",
        "summary_kind",
        "mean_metric",
        "mean_value_kind",
        "mean_value",
        "mean_status",
        "stddev_metric",
        "stddev_value_kind",
        "stddev_value",
        "stddev_status",
        "content",
        "result",
        "schema",
        "domain",
        "missing",
        "unexpected",
        "symlink",
    ),
)
def test_factor_pair_effect_corruption_matrix_fails_closed(tmp_path, mutation: str) -> None:
    case = factor_pair_effect_case(tmp_path)
    plan, store = case[13], case[14]
    case[15].execute(plan)
    authority = (
        tmp_path / "statistics-results" / "sha256" / plan.statistics_fingerprint[:2] / plan.statistics_fingerprint
    )
    manifest_path, summary_path = authority / "manifest.json", authority / "summary.json"
    manifest = json.loads(manifest_path.read_text())
    summary = json.loads(summary_path.read_text())
    if mutation == "manifest_unknown":
        manifest["unknown"] = True
    elif mutation == "manifest_kind":
        manifest["plan"]["definition"]["summary_kind"] = "EFFECT_SUMMARY"
    elif mutation == "plan_method":
        manifest["plan"]["definition"]["source_method"] = "FACTOR_RANK_CORRELATION"
    elif mutation == "plan_dataset":
        manifest["plan"]["dataset_snapshot_fingerprint"] = "1" * 64
    elif mutation == "plan_first_operand":
        manifest["plan"]["first_operand"]["candidate_fingerprint"] = "2" * 64
    elif mutation == "plan_second_operand":
        manifest["plan"]["second_operand"]["candidate_fingerprint"] = "3" * 64
    elif mutation == "source_logical":
        manifest["source_statistics_fingerprint"] = "4" * 64
    elif mutation == "source_result":
        manifest["source_statistics_result_fingerprint"] = "5" * 64
    elif mutation == "summary_hash":
        manifest["summary_byte_sha256"] = "6" * 64
    elif mutation == "summary_kind":
        summary["summary_kind"] = "EFFECT_SUMMARY"
    elif mutation == "mean_metric":
        summary["mean"]["metric_id"] = "research.factor_pair.correlation.stddev_sample@1"
    elif mutation == "mean_value_kind":
        summary["mean"]["value_kind"] = "INTEGER"
    elif mutation == "mean_value":
        summary["mean"]["decimal_value"] = "0.123000000000"
    elif mutation == "mean_status":
        summary["mean"] = {
            **summary["mean"],
            "status": "NO_VALID_OBSERVATIONS",
            "decimal_value": None,
        }
    elif mutation == "stddev_metric":
        summary["stddev_sample"]["metric_id"] = "research.factor_pair.correlation.mean@1"
    elif mutation == "stddev_value_kind":
        summary["stddev_sample"]["value_kind"] = "INTEGER"
    elif mutation == "stddev_value":
        summary["stddev_sample"]["decimal_value"] = "0.123000000000"
    elif mutation == "stddev_status":
        summary["stddev_sample"] = {
            **summary["stddev_sample"],
            "status": "INSUFFICIENT_OBSERVATIONS",
            "decimal_value": None,
        }
    elif mutation == "content":
        manifest["result_content_fingerprint"] = "7" * 64
    elif mutation == "result":
        manifest["statistics_result_fingerprint"] = "8" * 64
    elif mutation == "schema":
        manifest["schema_version"] = 2
    elif mutation == "domain":
        manifest["domain"] = "OTHER"
    elif mutation == "missing":
        summary_path.unlink()
    elif mutation == "unexpected":
        (authority / "unexpected").write_text("x")
    elif mutation == "symlink":
        original = authority / "original.json"
        summary_path.rename(original)
        summary_path.symlink_to(original.name)
    else:  # pragma: no cover
        raise AssertionError(mutation)
    if (
        mutation.startswith("manifest")
        or mutation.startswith("plan")
        or mutation
        in {
            "source_logical",
            "source_result",
            "summary_hash",
            "content",
            "result",
            "schema",
            "domain",
        }
    ):
        manifest_path.write_text(only_canonical_json(manifest))
    elif mutation not in {"missing", "unexpected", "symlink"}:
        summary_path.write_text(only_canonical_json(summary))
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as captured:
        store.load_verified(plan.statistics_fingerprint)
    assert captured.value.code == "SUMMARY_STATISTICS_RESULT_CORRUPT"
