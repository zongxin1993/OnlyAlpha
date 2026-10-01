from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.research import (
    OnlyJsonResearchResultStore,
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyParquetResearchStatisticsResultStore,
    OnlyResearchResultAssembler,
    OnlyResearchResultStoreError,
)
from onlyalpha.research.result.identity import (
    only_research_result_content_fingerprint,
    only_research_result_fingerprint,
)
from onlyalpha.research.result.plan import OnlyResearchResultPlan
from onlyalpha.research.result.result import OnlyResearchResult, OnlyResearchResultManifest
from tests.support.research_calculation_publication import calculation_workload_case


@pytest.mark.parametrize("version", (1, 2))
def test_existing_result_plans_still_require_statistics(version: int) -> None:
    with pytest.raises(ValueError, match="Statistics"):
        OnlyResearchResultPlan((), schema_version=version)


@pytest.mark.parametrize(
    "mutation",
    (
        "statistics",
        "candidate-owner",
        "no-series",
        "no-calculations",
        "duplicate",
        "unknown-calculation",
        "wrong-version",
    ),
)
def test_calculation_plan_rejects_incomplete_or_wrong_family(tmp_path: Path, mutation: str) -> None:
    _, workload = calculation_workload_case(tmp_path)
    plan = workload.result_plan
    changes: dict[str, object] = {
        "statistics": {"statistics_fingerprints": ("a" * 64,)},
        "candidate-owner": {"published_series": (replace(plan.published_series[0], candidate_fingerprint="a" * 64),)},
        "no-series": {"published_series": ()},
        "no-calculations": {"calculations": ()},
        "duplicate": {"calculations": plan.calculations * 2},
        "unknown-calculation": {
            "published_series": (replace(plan.published_series[0], calculation_fingerprint="a" * 64),)
        },
        "wrong-version": {"schema_version": 2},
    }[mutation]
    with pytest.raises(ValueError):
        replace(plan, **changes)


def test_calculation_plan_round_trip_and_workload_graph_closure(tmp_path: Path) -> None:
    _, workload = calculation_workload_case(tmp_path)
    plan = workload.result_plan
    assert OnlyResearchResultPlan.from_dict(plan.to_dict()) == plan
    with pytest.raises(ValueError, match="integer"):
        replace(plan, schema_version=3.0)  # type: ignore[arg-type]
    changed = replace(plan, calculations=(replace(plan.calculations[0], graph_fingerprint="a" * 64),))
    with pytest.raises(Exception, match="RESEARCH_WORKLOAD_RESULT_GRAPH_MISMATCH"):
        replace(workload, result_plan=changed)


@pytest.mark.parametrize(
    "field", ("dataset_snapshot_fingerprint", "calculations", "published_series", "statistics_fingerprints")
)
def test_calculation_plan_cannot_certify_missing_context_as_empty_publication(tmp_path: Path, field: str) -> None:
    _, workload = calculation_workload_case(tmp_path)
    payload = workload.result_plan.to_dict()
    del payload[field]
    with pytest.raises(ValueError, match="fields"):
        OnlyResearchResultPlan.from_dict(payload)


@pytest.mark.parametrize("mutation", ("dataset", "graph", "node", "output"))
def test_calculation_assembly_requires_complete_exact_upstream_relation(tmp_path: Path, mutation: str) -> None:
    engine, workload = calculation_workload_case(tmp_path)
    runtime_id = engine.add_research_workload(workload)
    engine.initialize()
    engine.start()
    outcome = engine.run_runtime(runtime_id)
    engine.stop()
    assert outcome.status.value == "COMPLETED"
    layout = OnlyUserDataLayout(tmp_path)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    calculations = OnlyParquetResearchCalculationResultStore(layout.research_calculation_result_root, datasets)
    statistics = OnlyParquetResearchStatisticsResultStore(layout.research_statistics_result_root, calculations)
    assembler = OnlyResearchResultAssembler(
        statistics,
        calculation_result_store=calculations,
        audit_time=lambda: datasets.load_verified_table(workload.dataset_snapshot_fingerprint).snapshot.created_at,
    )
    plan = workload.result_plan
    changes: dict[str, object] = {
        "dataset": {"dataset_snapshot_fingerprint": "a" * 64},
        "graph": {"calculations": (replace(plan.calculations[0], graph_fingerprint="a" * 64),)},
        "node": {"published_series": (replace(plan.published_series[0], node_fingerprint="a" * 64),)},
        "output": {"published_series": (replace(plan.published_series[0], output_name="not_an_output"),)},
    }[mutation]
    with pytest.raises(Exception, match="RESEARCH_RESULT_INVALID"):
        assembler.assemble(replace(plan, **changes))


def test_calculation_manifest_and_store_reject_rehashed_wrong_result_reference(tmp_path: Path) -> None:
    engine, workload = calculation_workload_case(tmp_path)
    runtime_id = engine.add_research_workload(workload)
    engine.initialize()
    engine.start()
    outcome = engine.run_runtime(runtime_id)
    engine.stop()
    assert outcome.status.value == "COMPLETED"
    layout = OnlyUserDataLayout(tmp_path)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    calculations = OnlyParquetResearchCalculationResultStore(layout.research_calculation_result_root, datasets)
    statistics = OnlyParquetResearchStatisticsResultStore(layout.research_statistics_result_root, calculations)
    results = OnlyJsonResearchResultStore(layout.research_result_root, statistics, calculations)
    manifest = results.load_verified(workload.result_plan.fingerprint).manifest
    assert OnlyResearchResultManifest.from_dict(manifest.to_dict()) == manifest
    assert manifest.statistics_results == ()
    with pytest.raises(ValueError, match="Dataset"):
        replace(manifest, dataset_snapshot_fingerprint="a" * 64)
    references = (replace(manifest.calculation_results[0], calculation_result_fingerprint="a" * 64),)
    content = only_research_result_content_fingerprint(
        (), tuple(item.to_dict() for item in references), schema_version=3
    )
    forged = replace(
        manifest,
        calculation_results=references,
        research_result_content_fingerprint=content,
        research_result_fingerprint=only_research_result_fingerprint(
            manifest.plan.fingerprint, content, schema_version=3
        ),
    )
    with pytest.raises(OnlyResearchResultStoreError, match="RESEARCH_RESULT_INVALID"):
        results.commit(OnlyResearchResult(forged))
    target = (
        layout.research_result_root
        / "sha256"
        / manifest.plan.fingerprint[:2]
        / manifest.plan.fingerprint
        / "manifest.json"
    )
    target.write_text(json.dumps(forged.to_dict()), encoding="utf-8")
    with pytest.raises(OnlyResearchResultStoreError, match="RESEARCH_RESULT_CORRUPT"):
        results.load_verified(manifest.plan.fingerprint)


@pytest.mark.parametrize("kind", ("file", "dangling-symlink"))
def test_existing_malformed_calculation_result_root_is_not_missing_or_replaced(tmp_path: Path, kind: str) -> None:
    engine, workload = calculation_workload_case(tmp_path)
    runtime_id = engine.add_research_workload(workload)
    engine.initialize()
    engine.start()
    completed = engine.run_runtime(runtime_id)
    engine.stop()
    assert completed.status.value == "COMPLETED"
    layout = OnlyUserDataLayout(tmp_path)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    calculations = OnlyParquetResearchCalculationResultStore(layout.research_calculation_result_root, datasets)
    statistics = OnlyParquetResearchStatisticsResultStore(layout.research_statistics_result_root, calculations)
    original = OnlyJsonResearchResultStore(layout.research_result_root, statistics, calculations).load_verified(
        workload.result_plan.fingerprint
    )
    root = tmp_path / "malformed-results"
    target = root / "sha256" / workload.result_plan.fingerprint[:2] / workload.result_plan.fingerprint
    target.parent.mkdir(parents=True)
    if kind == "file":
        target.write_bytes(b"existing-corruption")
    else:
        target.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    store = OnlyJsonResearchResultStore(root, statistics, calculations)
    with pytest.raises(OnlyResearchResultStoreError, match="RESEARCH_RESULT_CORRUPT"):
        store.load_verified(workload.result_plan.fingerprint)
    with pytest.raises(OnlyResearchResultStoreError, match="RESEARCH_RESULT_CORRUPT"):
        store.commit(original)
    assert target.is_symlink() if kind == "dangling-symlink" else target.read_bytes() == b"existing-corruption"
