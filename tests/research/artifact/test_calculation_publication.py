from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.research import (
    OnlyJsonResearchResultStore,
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyParquetResearchScientificArtifactStore,
    OnlyParquetResearchStatisticsResultStore,
    OnlyResearchArtifactStoreError,
    OnlyResearchQueryService,
    OnlyResearchScientificArtifactMaterializer,
    OnlyResearchScientificSeriesQuery,
)
from onlyalpha.research.artifact.reader import OnlyResearchArtifactProfileReader
from onlyalpha.research.artifact.scientific_model import (
    RESEARCH_CALCULATION_ARTIFACT_PROFILE,
    only_research_scientific_artifact_content_fingerprint,
    only_research_scientific_section_fingerprint,
)
from onlyalpha.research.artifact.scientific_store import OnlyParquetResearchCalculationArtifactStore
from tests.support.research_calculation_publication import calculation_workload_case


def _published(root: Path):  # type: ignore[no-untyped-def]
    engine, workload = calculation_workload_case(root)
    runtime_id = engine.add_research_workload(workload)
    engine.initialize()
    engine.start()
    outcome = engine.run_runtime(runtime_id)
    engine.stop()
    assert outcome.status.value == "COMPLETED"
    layout = OnlyUserDataLayout(root)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    calculations = OnlyParquetResearchCalculationResultStore(layout.research_calculation_result_root, datasets)
    statistics = OnlyParquetResearchStatisticsResultStore(layout.research_statistics_result_root, calculations)
    results = OnlyJsonResearchResultStore(layout.research_result_root, statistics, calculations)
    materializer = OnlyResearchScientificArtifactMaterializer(results, datasets, calculations, statistics)
    store = OnlyParquetResearchCalculationArtifactStore(
        layout.research_artifact_root,
        audit_time=lambda: datasets.load_verified_table(workload.dataset_snapshot_fingerprint).snapshot.created_at,
    )
    return layout, workload, outcome, materializer, store


def test_calculation_artifact_is_portable_and_query_projects_exact_decimal_zero(tmp_path: Path) -> None:
    layout, workload, outcome, _, store = _published(tmp_path)
    artifact = store.load_verified(outcome.research_result_fingerprint)
    assert artifact.manifest.profile == RESEARCH_CALCULATION_ARTIFACT_PROFILE
    assert artifact.manifest.schema_version == 1
    assert artifact.manifest.research_result_schema_version == 3
    reader = OnlyResearchArtifactProfileReader(layout.research_artifact_root)
    assert reader.load_verified(outcome.research_result_fingerprint).manifest == artifact.manifest
    query = OnlyResearchQueryService(reader)
    member = workload.result_plan.published_series[0]
    request = OnlyResearchScientificSeriesQuery(
        outcome.research_result_fingerprint,
        instrument_id="A.XNAS",
        calculation_fingerprint=member.calculation_fingerprint,
        node_fingerprint=member.node_fingerprint,
        output_name=member.output_name,
    )
    before = query.get_variable_series(request)
    assert len(before.points) == 4
    assert before.points[0].decimal_value == "0.000000000000"
    assert query.list_candidates(outcome.research_result_fingerprint).candidates == ()
    for root in (
        layout.research_dataset_root,
        layout.research_calculation_result_root,
        layout.research_statistics_result_root,
        layout.research_result_root,
    ):
        shutil.rmtree(root, ignore_errors=True)
    assert query.get_variable_series(request) == before


def test_calculation_artifact_refuses_self_consistent_forged_numeric_candidate(tmp_path: Path) -> None:
    layout, workload, _, materializer, _ = _published(tmp_path)
    candidate = materializer.materialize(workload.result_plan.fingerprint)
    variables = (replace(candidate.variable_rows[0], decimal_value="123.000000000000"), *candidate.variable_rows[1:])
    sections = tuple(
        replace(
            item,
            logical_fingerprint=only_research_scientific_section_fingerprint(
                "variables", [row.to_dict() for row in variables]
            ),
        )
        if item.relative_path == "variables.parquet"
        else item
        for item in candidate.sections
    )
    forged = replace(
        candidate,
        variable_rows=variables,
        sections=sections,
        artifact_content_fingerprint=only_research_scientific_artifact_content_fingerprint(
            candidate.result.manifest.research_result_fingerprint,
            sections,
            profile=RESEARCH_CALCULATION_ARTIFACT_PROFILE,
        ),
    )
    target = tmp_path / "forged-artifacts"
    store = OnlyParquetResearchCalculationArtifactStore(target)
    with pytest.raises(OnlyResearchArtifactStoreError, match="ARTIFACT_CANONICAL_PUBLICATION_REQUIRED"):
        store.commit(forged)
    assert not target.exists()
    with pytest.raises(OnlyResearchArtifactStoreError):
        OnlyParquetResearchScientificArtifactStore(layout.research_artifact_root).commit(candidate)


@pytest.mark.parametrize("section", ("market.parquet", "variables.parquet", "graphs.json", "statistics.parquet"))
def test_calculation_artifact_physical_corruption_blocks_query_and_reentry(tmp_path: Path, section: str) -> None:
    layout, workload, outcome, materializer, store = _published(tmp_path)
    path = (
        layout.research_artifact_root
        / "research-calculation-v1"
        / "sha256"
        / outcome.research_result_fingerprint[:2]
        / outcome.research_result_fingerprint
        / section
    )
    path.write_bytes(b"corrupt")
    with pytest.raises(OnlyResearchArtifactStoreError, match="ARTIFACT_CORRUPT"):
        OnlyResearchArtifactProfileReader(layout.research_artifact_root).load_verified(
            outcome.research_result_fingerprint
        )
    with pytest.raises(OnlyResearchArtifactStoreError, match="ARTIFACT_CORRUPT"):
        store.publish_calculation(workload.result_plan.fingerprint, materializer)
    assert path.read_bytes() == b"corrupt"


@pytest.mark.parametrize("kind", ("file", "dangling-symlink"))
def test_existing_malformed_calculation_artifact_root_is_not_missing_or_replaced(tmp_path: Path, kind: str) -> None:
    _, workload, outcome, materializer, _ = _published(tmp_path)
    root = tmp_path / "malformed-artifacts"
    target = (
        root
        / "research-calculation-v1"
        / "sha256"
        / outcome.research_result_fingerprint[:2]
        / outcome.research_result_fingerprint
    )
    target.parent.mkdir(parents=True)
    if kind == "file":
        target.write_bytes(b"existing-corruption")
    else:
        target.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    store = OnlyParquetResearchCalculationArtifactStore(root)
    with pytest.raises(OnlyResearchArtifactStoreError, match="ARTIFACT_CORRUPT"):
        OnlyResearchArtifactProfileReader(root).load_verified(outcome.research_result_fingerprint)
    with pytest.raises(OnlyResearchArtifactStoreError, match="ARTIFACT_CORRUPT"):
        store.publish_calculation(workload.result_plan.fingerprint, materializer)
    assert target.is_symlink() if kind == "dangling-symlink" else target.read_bytes() == b"existing-corruption"
