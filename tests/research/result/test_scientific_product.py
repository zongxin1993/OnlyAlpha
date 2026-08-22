from __future__ import annotations

from dataclasses import replace

import pytest

from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.research import (
    OnlyJsonResearchResultStore,
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyParquetResearchStatisticsResultStore,
    OnlyResearchCalculationResultReference,
)
from tests.research.artifact.support import scientific_artifact_case


def test_scientific_result_is_verified_through_exact_product_authorities(tmp_path) -> None:
    resolved, candidate, _ = scientific_artifact_case(tmp_path)
    layout = OnlyUserDataLayout(tmp_path)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    calculations = OnlyParquetResearchCalculationResultStore(layout.research_calculation_result_root, datasets)
    statistics = OnlyParquetResearchStatisticsResultStore(layout.research_statistics_result_root, calculations)
    results = OnlyJsonResearchResultStore(layout.research_result_root, statistics, calculations)

    verified = results.load_verified(resolved.workload.result_plan.fingerprint)

    assert verified == candidate.result
    assert verified.manifest.plan == resolved.workload.result_plan
    assert verified.manifest.dataset_snapshot_fingerprint == resolved.workload.dataset_snapshot_fingerprint
    assert len(verified.manifest.calculation_results) == len(resolved.workload.result_plan.calculations)

    manifest = verified.manifest
    with pytest.raises(ValueError, match="fields"):
        OnlyResearchCalculationResultReference.from_dict({"calculation_fingerprint": "a" * 64})
    with pytest.raises(ValueError, match="unsupported"):
        replace(manifest, schema_version=99)
    with pytest.raises(ValueError, match="references are invalid"):
        replace(manifest, calculation_results=[])  # type: ignore[arg-type]
    assert len(manifest.calculation_results) > 1
    with pytest.raises(ValueError, match="not canonical"):
        replace(manifest, calculation_results=tuple(reversed(manifest.calculation_results)))
    mismatched = tuple(
        sorted(
            (
                replace(manifest.calculation_results[0], calculation_fingerprint="0" * 64),
                *manifest.calculation_results[1:],
            )
        )
    )
    with pytest.raises(ValueError, match="do not match Plan"):
        replace(manifest, calculation_results=mismatched)
    malformed = manifest.to_dict()
    malformed["calculation_results"] = {}
    with pytest.raises(ValueError, match="must be an array"):
        type(manifest).from_dict(malformed)
