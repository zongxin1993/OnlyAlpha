from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from onlyalpha.research import (
    OnlyResearchFeatureSeriesReference,
    OnlyResearchResultPlan,
    OnlyResearchSweepCell,
    OnlyResearchSweepPlan,
    OnlyResearchTargetSeriesReference,
)
from onlyalpha.runtime.research import OnlyResearchRuntimeError, OnlyResearchWorkloadPlan
from tests.runtime.research.support import workload_case


def _workload(tmp_path: Path) -> OnlyResearchWorkloadPlan:
    return workload_case(tmp_path)[1]


def _fails(code: str, operation: Callable[[], object]) -> None:
    with pytest.raises(OnlyResearchRuntimeError) as raised:
        operation()
    assert raised.value.code == code
    assert raised.value.phase.value == "PLAN_VALIDATION"


def test_plan_rejects_empty_calculation_workload(tmp_path: Path) -> None:
    baseline = _workload(tmp_path)
    _fails(
        "RESEARCH_WORKLOAD_EMPTY",
        lambda: OnlyResearchWorkloadPlan((), (), baseline.statistics_plans, baseline.result_plan),
    )


def test_plan_rejects_duplicate_and_direct_sweep_calculation_ownership(tmp_path: Path) -> None:
    baseline = _workload(tmp_path)
    _fails(
        "RESEARCH_WORKLOAD_DUPLICATE_CALCULATION",
        lambda: replace(baseline, direct_jobs=(baseline.direct_jobs[0],) * 2),
    )
    cell = OnlyResearchSweepCell(0, (), baseline.direct_jobs[0].calculation_graph, baseline.direct_jobs[0])
    _fails(
        "RESEARCH_WORKLOAD_DUPLICATE_CALCULATION",
        lambda: replace(baseline, sweeps=(OnlyResearchSweepPlan((cell,)),)),
    )


def test_plan_rejects_unknown_feature_and_target_calculation(tmp_path: Path) -> None:
    baseline = _workload(tmp_path)
    statistics = baseline.statistics_plans[0]
    unknown_feature = replace(
        statistics,
        feature=OnlyResearchFeatureSeriesReference(
            "a" * 64, statistics.feature.node_fingerprint, statistics.feature.output_name
        ),
    )
    _fails(
        "RESEARCH_WORKLOAD_UNKNOWN_FEATURE",
        lambda: replace(
            baseline,
            statistics_plans=(unknown_feature,),
            result_plan=OnlyResearchResultPlan((unknown_feature.statistics_fingerprint,)),
        ),
    )
    unknown_target = replace(
        statistics,
        target=OnlyResearchTargetSeriesReference(
            "b" * 64, statistics.target.node_fingerprint, statistics.target.output_name
        ),
    )
    _fails(
        "RESEARCH_WORKLOAD_UNKNOWN_TARGET",
        lambda: replace(
            baseline,
            statistics_plans=(unknown_target,),
            result_plan=OnlyResearchResultPlan((unknown_target.statistics_fingerprint,)),
        ),
    )


def test_plan_rejects_duplicate_statistics_and_result_set_mismatch(tmp_path: Path) -> None:
    baseline = _workload(tmp_path)
    _fails(
        "RESEARCH_WORKLOAD_DUPLICATE_STATISTICS",
        lambda: replace(baseline, statistics_plans=baseline.statistics_plans * 2),
    )
    _fails(
        "RESEARCH_WORKLOAD_RESULT_STATISTICS_MISMATCH",
        lambda: replace(baseline, result_plan=OnlyResearchResultPlan(("c" * 64,))),
    )


def test_plan_rejects_cross_dataset_composition(tmp_path: Path) -> None:
    baseline = _workload(tmp_path)
    changed = replace(baseline.direct_jobs[1], dataset_snapshot_fingerprint="d" * 64)
    _fails(
        "RESEARCH_WORKLOAD_DATASET_MISMATCH",
        lambda: replace(baseline, direct_jobs=(baseline.direct_jobs[0], changed)),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("direct_jobs", []),
        ("sweeps", []),
        ("statistics_plans", []),
        ("result_plan", object()),
    ),
)
def test_plan_rejects_invalid_composition_contract_types(tmp_path: Path, field: str, value: object) -> None:
    baseline = _workload(tmp_path)
    _fails("RESEARCH_WORKLOAD_INVALID", lambda: replace(baseline, **{field: value}))
