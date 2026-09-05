from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from onlyalpha.research import (
    OnlyResearchFactorPairOperand,
    OnlyResearchFactorPairStatisticsDisposition,
    OnlyResearchFactorPairStatisticsExecution,
    OnlyResearchFactorPairStatisticsPlan,
    OnlyResearchFactorPairStatisticStatus,
    OnlyResearchFeatureSeriesReference,
    OnlyResearchStatisticsFamily,
    OnlyResearchStatisticsResultReader,
    only_research_statistics_family,
)
from onlyalpha.research.evaluation.errors import (
    OnlyResearchEvaluationError,
    OnlyResearchStatisticsResultStoreError,
)
from tests.research.evaluation.support import factor_pair_case, summary_case


def _target(root: Path, fingerprint: str) -> Path:
    return root / "statistics-results" / "sha256" / fingerprint[:2] / fingerprint


def test_factor_pair_end_to_end_reuse_symmetry_manifest_and_parquet(tmp_path) -> None:
    case = factor_pair_case(tmp_path)
    plan, store, executor, first = case[9], case[10], case[11], case[12]
    assert first.disposition is OnlyResearchFactorPairStatisticsDisposition.EXECUTED
    swapped = OnlyResearchFactorPairStatisticsPlan(
        plan.dataset_snapshot_fingerprint,
        plan.second_operand,
        plan.first_operand,
        plan.definition,
    )
    assert swapped.to_dict() == plan.to_dict()
    second = executor.execute(swapped)
    assert second.disposition is OnlyResearchFactorPairStatisticsDisposition.REUSED
    assert second.statistics_result_fingerprint == first.statistics_result_fingerprint
    result = store.load_verified(plan.statistics_fingerprint)
    assert type(result.manifest).from_dict(result.manifest.to_dict()) == result.manifest
    assert result.table.schema.names == ["ts_event_ns", "statistic_value", "sample_count", "status"]
    assert result.table.schema.field("statistic_value").type == pa.decimal128(38, 12)
    assert store.verify(plan.statistics_fingerprint).valid


def test_factor_pair_exact_dataset_and_factor_only_validation(tmp_path) -> None:
    case = factor_pair_case(tmp_path)
    plan, executor = case[9], case[11]
    with pytest.raises(OnlyResearchEvaluationError, match="FACTOR_PAIR_DATASET_MISMATCH"):
        executor.execute(replace(plan, dataset_snapshot_fingerprint="f" * 64))

    target_outcome = case[3].execute(case[5])
    target_node = case[5].calculation_graph.ordered_nodes[0]
    target_operand = OnlyResearchFactorPairOperand(
        "f" * 64,
        OnlyResearchFeatureSeriesReference(
            target_outcome.calculation_fingerprint, target_node.fingerprint, "target_value"
        ),
    )
    with pytest.raises(OnlyResearchEvaluationError, match="not a Factor"):
        executor.execute(replace(plan, second_operand=target_operand))

    factor_result = case[2].load_verified(plan.first_operand.series.calculation_fingerprint)
    indicator_node = next(
        node
        for node in factor_result.manifest.calculation_graph.ordered_nodes
        if node.definition.kind.value == "INDICATOR"
    )
    indicator_operand = OnlyResearchFactorPairOperand(
        "e" * 64,
        OnlyResearchFeatureSeriesReference(
            factor_result.manifest.calculation_fingerprint,
            indicator_node.fingerprint,
            indicator_node.definition.outputs[0].name,
        ),
    )
    with pytest.raises(OnlyResearchEvaluationError, match="not a Factor"):
        executor.execute(replace(plan, second_operand=indicator_operand))
    with pytest.raises(OnlyResearchEvaluationError, match="not a Factor"):
        executor.execute(
            replace(
                plan,
                second_operand=replace(
                    plan.second_operand, series=replace(plan.second_operand.series, node_fingerprint="f" * 64)
                ),
            )
        )
    with pytest.raises(OnlyResearchEvaluationError, match="value/score"):
        executor.execute(
            replace(
                plan,
                second_operand=replace(
                    plan.second_operand, series=replace(plan.second_operand.series, output_name="missing")
                ),
            )
        )


def test_factor_pair_put_once_conflict_and_fresh_process_swapped_reuse(tmp_path) -> None:
    case = factor_pair_case(tmp_path)
    plan, store = case[9], case[10]
    result = store.load_verified(plan.statistics_fingerprint)
    manifest = result.manifest
    execution = OnlyResearchFactorPairStatisticsExecution(
        plan,
        manifest.first_calculation_result_fingerprint,
        manifest.second_calculation_result_fingerprint,
        manifest.dataset_snapshot_fingerprint,
        result.rows,
    )
    assert store.commit(execution).manifest.statistics_result_fingerprint == manifest.statistics_result_fingerprint
    changed = list(result.rows)
    index = next(
        index for index, row in enumerate(changed) if row.status is OnlyResearchFactorPairStatisticStatus.VALID
    )
    changed[index] = replace(changed[index], statistic_value=-changed[index].statistic_value)  # type: ignore[operator]
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as captured:
        store.commit(replace(execution, rows=tuple(changed)))
    assert captured.value.code == "DETERMINISTIC_RESULT_CONFLICT"

    plan_path = tmp_path / "pair-plan.json"
    plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
    script = """
import json, sys
from pathlib import Path
from onlyalpha.research import *
root = Path(sys.argv[1])
canonical = OnlyResearchFactorPairStatisticsPlan.from_dict(json.loads((root / 'pair-plan.json').read_text()))
plan = OnlyResearchFactorPairStatisticsPlan(
    canonical.dataset_snapshot_fingerprint, canonical.second_operand, canonical.first_operand, canonical.definition
)
datasets = OnlyParquetResearchDatasetSnapshotStore(root / 'datasets')
calculations = OnlyParquetResearchCalculationResultStore(root / 'calculation-results', datasets)
store = OnlyParquetResearchFactorPairStatisticsResultStore(root / 'statistics-results', calculations)
outcome = OnlyResearchFactorPairStatisticsExecutor(calculations, store).execute(plan)
print(outcome.disposition.value, outcome.statistics_fingerprint, outcome.statistics_result_fingerprint)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert completed.stdout.strip() == (
        f"REUSED {plan.statistics_fingerprint} {manifest.statistics_result_fingerprint}"
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "manifest_unknown",
        "manifest_domain",
        "manifest_schema",
        "manifest_statistics",
        "manifest_operands",
        "manifest_noncanonical_order",
        "manifest_dataset",
        "manifest_first_result",
        "manifest_second_result",
        "manifest_content",
        "manifest_result",
        "manifest_row_count",
        "manifest_arrow_schema",
        "manifest_data_sha",
        "data_timestamp",
        "data_duplicate_timestamp",
        "data_value",
        "data_sample_count",
        "data_status",
        "missing_file",
        "unexpected_file",
        "symlink",
    ),
)
def test_factor_pair_corruption_matrix_is_fail_closed(tmp_path, mutation: str) -> None:
    case = factor_pair_case(tmp_path)
    plan, store = case[9], case[10]
    root = _target(tmp_path, plan.statistics_fingerprint)
    manifest_path = root / "manifest.json"
    data_path = root / "data.parquet"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mutation.startswith("manifest_"):
        if mutation == "manifest_unknown":
            payload["unknown"] = True
        elif mutation == "manifest_domain":
            payload["domain"] = "OTHER"
        elif mutation == "manifest_schema":
            payload["schema_version"] = 2
        elif mutation == "manifest_statistics":
            payload["statistics_fingerprint"] = "1" * 64
        elif mutation == "manifest_operands":
            payload["plan"]["first_operand"]["candidate_fingerprint"] = "2" * 64
        elif mutation == "manifest_noncanonical_order":
            raw_plan = payload["plan"]
            raw_plan["first_operand"], raw_plan["second_operand"] = (
                raw_plan["second_operand"],
                raw_plan["first_operand"],
            )
        elif mutation == "manifest_dataset":
            payload["dataset_snapshot_fingerprint"] = "3" * 64
        elif mutation == "manifest_first_result":
            payload["first_calculation_result_fingerprint"] = "4" * 64
        elif mutation == "manifest_second_result":
            payload["second_calculation_result_fingerprint"] = "5" * 64
        elif mutation == "manifest_content":
            payload["result_content_fingerprint"] = "6" * 64
        elif mutation == "manifest_result":
            payload["statistics_result_fingerprint"] = "7" * 64
        elif mutation == "manifest_row_count":
            payload["row_count"] += 1
        elif mutation == "manifest_arrow_schema":
            payload["arrow_schema"][0]["nullable"] = True
        else:
            payload["data_byte_sha256"] = "8" * 64
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    elif mutation.startswith("data_"):
        table = pq.read_table(data_path)
        values = {name: table.column(name).to_pylist() for name in table.schema.names}
        if mutation == "data_timestamp":
            values["ts_event_ns"][0] += 1
        elif mutation == "data_duplicate_timestamp":
            values["ts_event_ns"][1] = values["ts_event_ns"][0]
        elif mutation == "data_value":
            index = next(index for index, value in enumerate(values["statistic_value"]) if value is not None)
            values["statistic_value"][index] = Decimal("0.123000000000")
        elif mutation == "data_sample_count":
            values["sample_count"][0] += 1
        else:
            values["status"][0] = "UNKNOWN"
        changed = pa.Table.from_arrays(
            [pa.array(values[field.name], type=field.type) for field in table.schema], schema=table.schema
        )
        pq.write_table(changed, data_path)
        payload["data_byte_sha256"] = sha256(data_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    elif mutation == "missing_file":
        data_path.unlink()
    elif mutation == "unexpected_file":
        (root / "unexpected").write_text("x", encoding="utf-8")
    else:
        original = root / "original.parquet"
        data_path.rename(original)
        data_path.symlink_to(original.name)
    assert store.exists(plan.statistics_fingerprint)
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as captured:
        store.load_verified(plan.statistics_fingerprint)
    assert captured.value.code == "FACTOR_PAIR_STATISTICS_RESULT_CORRUPT"


def test_generic_reader_exact_dispatches_legacy_pair_and_summary(tmp_path) -> None:
    summary = summary_case(tmp_path)
    summary_outcome = summary[13].execute(summary[11])
    pair = factor_pair_case(tmp_path)
    reader = OnlyResearchStatisticsResultReader(tmp_path / "statistics-results", summary[8], summary[12], pair[10])
    legacy = reader.load_verified(summary[6].statistics_fingerprint)
    summary_result = reader.load_verified(summary_outcome.statistics_fingerprint)
    pair_result = reader.load_verified(pair[9].statistics_fingerprint)
    assert only_research_statistics_family(legacy.manifest.to_dict()) is (
        OnlyResearchStatisticsFamily.FEATURE_TARGET_CORRELATION_SERIES_V1
    )
    assert only_research_statistics_family(summary_result.manifest.to_dict()) is (
        OnlyResearchStatisticsFamily.SUMMARY_STATISTICS_V1
    )
    assert only_research_statistics_family(pair_result.manifest.to_dict()) is (
        OnlyResearchStatisticsFamily.FACTOR_PAIR_CORRELATION_SERIES_V1
    )
    reader_without_pair = OnlyResearchStatisticsResultReader(tmp_path / "statistics-results", summary[8], summary[12])
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as captured:
        reader_without_pair.load_verified(pair[9].statistics_fingerprint)
    assert captured.value.code == "STATISTICS_RESULT_READER_NOT_CONFIGURED"
