from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from onlyalpha.research import (
    OnlyResearchStatisticsExecution,
    OnlyResearchStatisticStatus,
)
from onlyalpha.research.evaluation.errors import OnlyResearchStatisticsResultStoreError
from tests.research.evaluation.support import statistics_case


def _target(root: Path, fingerprint: str) -> Path:
    return root / "statistics-results" / "sha256" / fingerprint[:2] / fingerprint


def test_commit_verify_idempotency_and_deterministic_conflict(tmp_path) -> None:
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
    assert store.commit(execution).manifest.statistics_result_fingerprint == manifest.statistics_result_fingerprint
    verification = store.verify(plan.statistics_fingerprint)
    assert verification.valid and verification.row_count == len(result.rows)
    index = next(index for index, row in enumerate(result.rows) if row.status is OnlyResearchStatisticStatus.VALID)
    changed = list(result.rows)
    changed[index] = replace(changed[index], statistic_value=-changed[index].statistic_value)  # type: ignore[operator]
    conflict = replace(execution, rows=tuple(changed))
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as raised:
        store.commit(conflict)
    assert raised.value.code == "DETERMINISTIC_RESULT_CONFLICT"


@pytest.mark.parametrize(
    "mutation",
    (
        "manifest_unknown",
        "manifest_content",
        "manifest_result",
        "manifest_statistics",
        "manifest_dataset",
        "manifest_feature_result",
        "manifest_target_result",
        "manifest_byte_hash",
        "manifest_schema",
        "manifest_row_count",
        "data_bytes",
        "unexpected_file",
        "missing_data",
    ),
)
def test_corruption_is_never_treated_as_missing(tmp_path, mutation: str) -> None:
    case = statistics_case(tmp_path)
    plan, store = case[6], case[8]
    root = _target(tmp_path, plan.statistics_fingerprint)
    manifest_path = root / "manifest.json"
    data_path = root / "data.parquet"
    if mutation.startswith("manifest_"):
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if mutation == "manifest_unknown":
            payload["unknown"] = True
        elif mutation == "manifest_content":
            payload["result_content_fingerprint"] = "1" * 64
        elif mutation == "manifest_result":
            payload["statistics_result_fingerprint"] = "2" * 64
        elif mutation == "manifest_statistics":
            payload["statistics_fingerprint"] = "3" * 64
        elif mutation == "manifest_dataset":
            payload["dataset_snapshot_fingerprint"] = "4" * 64
        elif mutation == "manifest_feature_result":
            payload["feature_calculation_result_fingerprint"] = "5" * 64
        elif mutation == "manifest_target_result":
            payload["target_calculation_result_fingerprint"] = "6" * 64
        elif mutation == "manifest_schema":
            payload["arrow_schema"] = []
        elif mutation == "manifest_row_count":
            payload["row_count"] += 1
        else:
            payload["data_byte_sha256"] = "7" * 64
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    elif mutation == "data_bytes":
        data_path.write_bytes(data_path.read_bytes() + b"corrupt")
    elif mutation == "unexpected_file":
        (root / "unexpected").write_text("x", encoding="utf-8")
    else:
        data_path.unlink()
    assert store.exists(plan.statistics_fingerprint)
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as raised:
        store.load_verified(plan.statistics_fingerprint)
    assert raised.value.code == "STATISTICS_RESULT_CORRUPT"


def test_manifest_and_plan_serialization_round_trip_and_fresh_process_reuse(tmp_path) -> None:
    case = statistics_case(tmp_path)
    plan, result_store = case[6], case[8]
    result = result_store.load_verified(plan.statistics_fingerprint)
    assert type(result.manifest).from_dict(result.manifest.to_dict()) == result.manifest
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
    script = """
import json, sys
from pathlib import Path
from onlyalpha.research import *
root = Path(sys.argv[1])
plan = OnlyResearchStatisticsPlan.from_dict(json.loads((root / 'plan.json').read_text()))
dataset = OnlyParquetResearchDatasetSnapshotStore(root / 'datasets')
calculations = OnlyParquetResearchCalculationResultStore(root / 'calculation-results', dataset)
statistics = OnlyParquetResearchStatisticsResultStore(root / 'statistics-results', calculations)
outcome = OnlyResearchStatisticsExecutor(calculations, statistics).execute(plan)
print(outcome.disposition.value, outcome.statistics_result_fingerprint)
"""
    environment = os.environ.copy()
    result_process = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result_process.stdout.strip() == (f"REUSED {result.manifest.statistics_result_fingerprint}")


def test_logical_data_tamper_with_recomputed_byte_hash_still_fails_closed(tmp_path) -> None:
    case = statistics_case(tmp_path)
    plan, store = case[6], case[8]
    root = _target(tmp_path, plan.statistics_fingerprint)
    data_path = root / "data.parquet"
    manifest_path = root / "manifest.json"
    table = pq.read_table(data_path)
    values = table.column("statistic_value").to_pylist()
    index = next(index for index, value in enumerate(values) if value is not None)
    values[index] = -values[index]
    changed = table.set_column(
        table.schema.get_field_index("statistic_value"),
        table.schema.field("statistic_value"),
        pa.array(values, type=table.schema.field("statistic_value").type),
    )
    pq.write_table(changed, data_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["data_byte_sha256"] = sha256(data_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(OnlyResearchStatisticsResultStoreError) as raised:
        store.load_verified(plan.statistics_fingerprint)
    assert raised.value.code == "STATISTICS_RESULT_CORRUPT"
    assert "content fingerprint" in raised.value.detail


def test_invalid_identity_and_missing_result_have_exact_missing_code(tmp_path) -> None:
    case = statistics_case(tmp_path)
    store = case[8]
    for fingerprint in ("bad", "f" * 64):
        with pytest.raises(OnlyResearchStatisticsResultStoreError) as raised:
            store.load_verified(fingerprint)
        assert raised.value.code == "STATISTICS_RESULT_NOT_FOUND"
