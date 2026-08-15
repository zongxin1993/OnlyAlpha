from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import cast

import pyarrow as pa  # type: ignore[import-untyped]
import pytest

from onlyalpha.calculation import OnlyNumericDefinition
from onlyalpha.research.calculation.errors import OnlyResearchCalculationResultStoreError
from onlyalpha.research.calculation.execution import OnlyResearchCalculationNodeOutput
from onlyalpha.research.calculation.result import OnlyResearchCalculationResult
from onlyalpha.research.evaluation import (
    OnlyResearchAlignedObservation,
    OnlyResearchFeatureSeriesReference,
    OnlyResearchPairingPolicy,
    OnlyResearchRankTieMethod,
    OnlyResearchStatisticRow,
    OnlyResearchStatisticsDefinition,
    OnlyResearchStatisticsDisposition,
    OnlyResearchStatisticsMethod,
    OnlyResearchStatisticsOutcome,
    OnlyResearchStatisticsPlan,
    OnlyResearchStatisticStatus,
    OnlyResearchTargetSeriesReference,
    OnlyResearchUniversePolicy,
    OnlyResearchWeighting,
    only_align_research_series,
    only_compute_research_statistics,
)
from onlyalpha.research.evaluation.errors import (
    OnlyResearchEvaluationError,
    OnlyResearchStatisticsResultStoreError,
)
from onlyalpha.research.evaluation.execution import _validate_upstream
from tests.research.evaluation.support import statistics_case


def _plan() -> OnlyResearchStatisticsPlan:
    return OnlyResearchStatisticsPlan(
        OnlyResearchFeatureSeriesReference("a" * 64, "b" * 64, "factor_value"),
        OnlyResearchTargetSeriesReference("c" * 64, "d" * 64, "target_value"),
        OnlyResearchStatisticsDefinition(OnlyResearchStatisticsMethod.IC),
    )


@pytest.mark.parametrize(
    "change",
    (
        {"schema_version": 2},
        {"method": cast(OnlyResearchStatisticsMethod, "IC")},
        {"minimum_observations": True},
        {"minimum_observations": cast(int, "2")},
        {"pairing_policy": cast(OnlyResearchPairingPolicy, "PAIRWISE_COMPLETE")},
        {"universe_policy": cast(OnlyResearchUniversePolicy, "OBSERVED_PAIRWISE")},
        {"rank_tie_method": cast(OnlyResearchRankTieMethod, "AVERAGE")},
        {"weighting": cast(OnlyResearchWeighting, "EQUAL")},
        {"numeric": OnlyNumericDefinition()},
    ),
)
def test_statistics_definition_direct_validation(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        replace(OnlyResearchStatisticsDefinition(OnlyResearchStatisticsMethod.IC), **change)


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("unknown",), True),
        (("numeric",), []),
        (("numeric", "unknown"), True),
        (("method",), 1),
        (("minimum_observations",), "2"),
        (("schema_version",), "1"),
    ),
)
def test_statistics_definition_reader_is_exact(path: tuple[str, ...], value: object) -> None:
    payload = _plan().definition.to_dict()
    if path == ("unknown",):
        payload["unknown"] = value
    elif len(path) == 1:
        payload[path[0]] = value
    else:
        cast(dict[str, object], payload[path[0]])[path[1]] = value
    with pytest.raises((TypeError, ValueError)):
        OnlyResearchStatisticsDefinition.from_dict(payload)


@pytest.mark.parametrize(
    "change",
    (
        {"schema_version": 2},
        {"feature": cast(OnlyResearchFeatureSeriesReference, object())},
        {"target": cast(OnlyResearchTargetSeriesReference, object())},
        {"definition": cast(OnlyResearchStatisticsDefinition, object())},
    ),
)
def test_statistics_plan_direct_validation(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        replace(_plan(), **change)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("unknown", True),
        ("schema_version", True),
        ("feature", []),
        ("target", {1: "bad"}),
        ("definition", None),
    ),
)
def test_statistics_plan_reader_is_exact(field: str, value: object) -> None:
    payload = _plan().to_dict()
    payload[field] = value
    with pytest.raises((TypeError, ValueError)):
        OnlyResearchStatisticsPlan.from_dict(payload)


@pytest.mark.parametrize(
    "factory",
    (OnlyResearchFeatureSeriesReference, OnlyResearchTargetSeriesReference),
)
def test_series_reference_rejects_invalid_identity_name_and_payload(factory) -> None:
    with pytest.raises(ValueError, match="SHA256"):
        factory("bad", "b" * 64, "value")
    with pytest.raises(ValueError, match="output_name"):
        factory("a" * 64, "b" * 64, "bad name")
    with pytest.raises(ValueError, match="fields"):
        factory.from_dict({"calculation_fingerprint": "a" * 64})
    with pytest.raises(ValueError, match="strings"):
        factory.from_dict({"calculation_fingerprint": "a" * 64, "node_fingerprint": "b" * 64, "output_name": 1})


@pytest.mark.parametrize(
    "args",
    (
        (True, None, 1, OnlyResearchStatisticStatus.INSUFFICIENT_OBSERVATIONS),
        (1, None, -1, OnlyResearchStatisticStatus.INSUFFICIENT_OBSERVATIONS),
        (1, Decimal("NaN"), 1, OnlyResearchStatisticStatus.VALID),
        (1, None, 2, OnlyResearchStatisticStatus.VALID),
        (1, Decimal("2"), 2, OnlyResearchStatisticStatus.VALID),
        (1, Decimal("0"), 1, OnlyResearchStatisticStatus.ZERO_VARIANCE_FEATURE),
    ),
)
def test_statistic_row_rejects_invalid_semantic_state(args: tuple[object, ...]) -> None:
    with pytest.raises(ValueError):
        OnlyResearchStatisticRow(*args)  # type: ignore[arg-type]


def test_statistics_outcome_rejects_invalid_contract() -> None:
    with pytest.raises(ValueError):
        OnlyResearchStatisticsOutcome(cast(OnlyResearchStatisticsDisposition, "EXECUTED"), "a" * 64, "b" * 64)
    with pytest.raises(ValueError):
        OnlyResearchStatisticsOutcome(OnlyResearchStatisticsDisposition.EXECUTED, "bad", "b" * 64)
    with pytest.raises(ValueError):
        OnlyResearchStatisticsOutcome(OnlyResearchStatisticsDisposition.EXECUTED, "a" * 64, "bad")


def _result(_node: str, outputs: tuple[OnlyResearchCalculationNodeOutput, ...]) -> OnlyResearchCalculationResult:
    return OnlyResearchCalculationResult(cast(object, None), outputs)  # type: ignore[arg-type]


def _output(node: str, instrument: str, values: list[Decimal | None], timestamps: list[int] | None = None):
    timestamps = list(range(len(values))) if timestamps is None else timestamps
    return OnlyResearchCalculationNodeOutput(
        node,
        instrument,
        pa.table(
            {
                "ts_event_ns": pa.array(timestamps, type=pa.int64()),
                "value": pa.array(values, type=pa.decimal128(38, 12)),
            }
        ),
    )


def test_alignment_pairwise_null_filtering_is_exact() -> None:
    feature_node, target_node = "b" * 64, "d" * 64
    feature = _result(feature_node, (_output(feature_node, "A", [Decimal(1), None, Decimal(3)]),))
    target = _result(target_node, (_output(target_node, "A", [Decimal(2), Decimal(4), None]),))
    observations = only_align_research_series(
        feature,
        target,
        OnlyResearchFeatureSeriesReference("a" * 64, feature_node, "value"),
        OnlyResearchTargetSeriesReference("c" * 64, target_node, "value"),
    )
    assert tuple(len(item.pairs) for item in observations) == (1, 0, 0)


def test_alignment_rejects_missing_duplicate_and_mismatched_axes() -> None:
    feature_node, target_node = "b" * 64, "d" * 64
    feature_ref = OnlyResearchFeatureSeriesReference("a" * 64, feature_node, "value")
    target_ref = OnlyResearchTargetSeriesReference("c" * 64, target_node, "value")
    valid = _output(feature_node, "A", [Decimal(1)])
    with pytest.raises(OnlyResearchEvaluationError, match="node output"):
        only_align_research_series(_result(feature_node, ()), _result(target_node, ()), feature_ref, target_ref)
    duplicate = _result(feature_node, (valid, valid))
    with pytest.raises(OnlyResearchEvaluationError, match="duplicate"):
        only_align_research_series(
            duplicate, _result(target_node, (_output(target_node, "A", [Decimal(1)]),)), feature_ref, target_ref
        )
    with pytest.raises(OnlyResearchEvaluationError, match="instrument axes"):
        only_align_research_series(
            _result(feature_node, (valid,)),
            _result(target_node, (_output(target_node, "B", [Decimal(1)]),)),
            feature_ref,
            target_ref,
        )
    with pytest.raises(OnlyResearchEvaluationError, match="timestamp axis differs"):
        only_align_research_series(
            _result(feature_node, (valid,)),
            _result(target_node, (_output(target_node, "A", [Decimal(1)], [2]),)),
            feature_ref,
            target_ref,
        )


def test_alignment_rejects_missing_output_wrong_type_and_noncanonical_axis() -> None:
    feature_node, target_node = "b" * 64, "d" * 64
    feature_ref = OnlyResearchFeatureSeriesReference("a" * 64, feature_node, "missing")
    target_ref = OnlyResearchTargetSeriesReference("c" * 64, target_node, "value")
    target = _result(target_node, (_output(target_node, "A", [Decimal(1), Decimal(2)]),))
    with pytest.raises(OnlyResearchEvaluationError, match="output is absent"):
        only_align_research_series(
            _result(feature_node, (_output(feature_node, "A", [Decimal(1), Decimal(2)]),)),
            target,
            feature_ref,
            target_ref,
        )
    wrong = OnlyResearchCalculationNodeOutput(
        feature_node,
        "A",
        pa.table({"ts_event_ns": [1, 2], "value": [1, 2]}),
    )
    with pytest.raises(OnlyResearchEvaluationError, match="series type"):
        only_align_research_series(
            _result(feature_node, (wrong,)), target, replace(feature_ref, output_name="value"), target_ref
        )
    noncanonical = _output(feature_node, "A", [Decimal(1), Decimal(2)], [2, 1])
    with pytest.raises(OnlyResearchEvaluationError, match="timestamp axis"):
        only_align_research_series(
            _result(feature_node, (noncanonical,)),
            target,
            replace(feature_ref, output_name="value"),
            target_ref,
        )


def test_compute_rejects_wrong_definition_and_noncanonical_observations() -> None:
    with pytest.raises(OnlyResearchEvaluationError, match="DEFINITION"):
        only_compute_research_statistics((), cast(OnlyResearchStatisticsDefinition, object()))
    observations = (OnlyResearchAlignedObservation(2, ()), OnlyResearchAlignedObservation(1, ()))
    with pytest.raises(OnlyResearchEvaluationError, match="timestamps"):
        only_compute_research_statistics(observations, _plan().definition)


def test_executor_and_store_reject_invalid_entry_contracts_and_audit_time(tmp_path) -> None:
    case = statistics_case(tmp_path)
    store, executor = case[8], case[9]
    with pytest.raises(OnlyResearchEvaluationError, match="PLAN_INVALID"):
        executor.execute(cast(OnlyResearchStatisticsPlan, object()))
    with pytest.raises(OnlyResearchStatisticsResultStoreError, match="execution contract"):
        store.commit(cast(object, None))  # type: ignore[arg-type]
    no_time = type(store)(tmp_path / "no-time", case[2])
    result = store.load_verified(case[6].statistics_fingerprint)
    manifest = result.manifest
    from onlyalpha.research.evaluation import OnlyResearchStatisticsExecution

    candidate = OnlyResearchStatisticsExecution(
        case[6],
        manifest.feature_calculation_result_fingerprint,
        manifest.target_calculation_result_fingerprint,
        manifest.dataset_snapshot_fingerprint,
        result.rows,
    )
    with pytest.raises(OnlyResearchStatisticsResultStoreError, match="audit time"):
        no_time.commit(candidate)
    naive = type(store)(tmp_path / "naive", case[2], audit_time=lambda: datetime(2026, 1, 1))
    with pytest.raises(OnlyResearchStatisticsResultStoreError, match="audit time"):
        naive.commit(candidate)


def test_upstream_reference_node_output_and_result_identity_validation(tmp_path) -> None:
    case = statistics_case(tmp_path)
    plan, calculation_store = case[6], case[2]
    feature = calculation_store.load_verified(plan.feature.calculation_fingerprint)
    target = calculation_store.load_verified(plan.target.calculation_fingerprint)
    with pytest.raises(OnlyResearchEvaluationError, match="feature Calculation"):
        _validate_upstream(
            replace(plan, feature=replace(plan.feature, calculation_fingerprint="f" * 64)), feature, target
        )
    with pytest.raises(OnlyResearchEvaluationError, match="target Calculation"):
        _validate_upstream(
            replace(plan, target=replace(plan.target, calculation_fingerprint="f" * 64)), feature, target
        )
    with pytest.raises(OnlyResearchEvaluationError, match="node semantic kind"):
        _validate_upstream(replace(plan, feature=replace(plan.feature, node_fingerprint="f" * 64)), feature, target)
    with pytest.raises(OnlyResearchEvaluationError, match="output semantic type"):
        _validate_upstream(replace(plan, feature=replace(plan.feature, output_name="missing")), feature, target)


def test_statistics_executor_does_not_hide_store_or_upstream_failures() -> None:
    from onlyalpha.research.evaluation import OnlyResearchStatisticsExecutor

    class CorruptStatistics:
        def load_verified(self, fingerprint):
            raise OnlyResearchStatisticsResultStoreError("STATISTICS_RESULT_CORRUPT", fingerprint)

        def commit(self, execution):  # pragma: no cover - load fails first
            raise AssertionError

    class MissingStatistics:
        def load_verified(self, fingerprint):
            raise OnlyResearchStatisticsResultStoreError("STATISTICS_RESULT_NOT_FOUND", fingerprint)

        def commit(self, execution):  # pragma: no cover - upstream fails first
            raise AssertionError

    class CalculationFailure:
        def __init__(self, error: Exception) -> None:
            self.error = error

        def load_verified(self, fingerprint):
            raise self.error

    with pytest.raises(OnlyResearchStatisticsResultStoreError, match="CORRUPT"):
        OnlyResearchStatisticsExecutor(CalculationFailure(ValueError()), CorruptStatistics()).execute(_plan())
    with pytest.raises(OnlyResearchEvaluationError, match="RESULT_CORRUPT"):
        OnlyResearchStatisticsExecutor(
            CalculationFailure(OnlyResearchCalculationResultStoreError("RESULT_CORRUPT", "bad")),
            MissingStatistics(),
        ).execute(_plan())
    with pytest.raises(OnlyResearchEvaluationError, match="UPSTREAM_INVALID"):
        OnlyResearchStatisticsExecutor(CalculationFailure(ValueError("bad")), MissingStatistics()).execute(_plan())


def test_statistics_manifest_reader_rejects_schema_counts_types_and_time(tmp_path) -> None:
    case = statistics_case(tmp_path)
    result = case[8].load_verified(case[6].statistics_fingerprint)
    manifest_type = type(result.manifest)
    baseline = result.manifest.to_dict()
    mutations = (
        ("schema_version", 2),
        ("row_count", -1),
        ("row_count", "4"),
        ("arrow_schema", {}),
        ("created_at", "not-time"),
        ("created_at", "2026-01-01T00:00:00"),
        ("data_byte_sha256", "bad"),
        ("plan", []),
    )
    for field, value in mutations:
        payload = dict(baseline)
        payload[field] = value
        with pytest.raises((TypeError, ValueError)):
            manifest_type.from_dict(payload)


def test_statistics_store_admission_rejects_linkage_rows_and_timestamp_order(tmp_path) -> None:
    from onlyalpha.research.evaluation import OnlyResearchStatisticsExecution

    case = statistics_case(tmp_path)
    plan, store = case[6], case[8]
    result = store.load_verified(plan.statistics_fingerprint)
    manifest = result.manifest
    execution = OnlyResearchStatisticsExecution(
        plan,
        manifest.feature_calculation_result_fingerprint,
        manifest.target_calculation_result_fingerprint,
        manifest.dataset_snapshot_fingerprint,
        result.rows,
    )
    for changed in (
        replace(execution, dataset_snapshot_fingerprint="f" * 64),
        replace(execution, feature_calculation_result_fingerprint="f" * 64),
        replace(execution, target_calculation_result_fingerprint="f" * 64),
        replace(execution, rows=cast(tuple[OnlyResearchStatisticRow, ...], (object(),))),
        replace(execution, rows=tuple(reversed(execution.rows))),
    ):
        with pytest.raises(OnlyResearchStatisticsResultStoreError) as raised:
            store.commit(changed)
        assert raised.value.code == "STATISTICS_RESULT_INVALID"
