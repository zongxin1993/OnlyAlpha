from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from onlyalpha.research import (
    RESEARCH_SCIENTIFIC_ARTIFACT_V3_PROFILE,
    RESEARCH_SCIENTIFIC_ARTIFACT_V3_SCHEMA_VERSION,
    RESEARCH_SCIENTIFIC_ARTIFACT_V3_SECTION_PATHS,
    OnlyJsonResearchResultStore,
    OnlyParquetResearchScientificArtifactStoreV3,
    OnlyResearchArtifactDisposition,
    OnlyResearchArtifactStoreError,
    OnlyResearchParameterNeighborhoodSummaryExecutor,
    OnlyResearchResultAssembler,
    OnlyResearchResultCalculationPlan,
    OnlyResearchResultCandidatePlan,
    OnlyResearchResultPlan,
    OnlyResearchScientificArtifactMaterializerV3,
    OnlyResearchScientificLegacySeriesCatalogEntryV3,
    OnlyResearchScientificSection,
    OnlyResearchScientificStatisticsShapeV3,
    OnlyResearchScientificSummaryCatalogEntryV3,
    OnlyResearchStatisticsResultReader,
    only_research_scientific_artifact_v3_content_fingerprint,
    only_research_scientific_catalog_entry_v3_from_dict,
    only_research_scientific_v3_section_fingerprint,
)
from onlyalpha.research.artifact.scientific_v3_store import _semantic
from tests.research.artifact.support import (
    scientific_artifact_v3_case,
    scientific_artifact_v3_target,
)
from tests.research.evaluation.support import (
    coverage_case,
    factor_pair_effect_case,
    stability_case,
    summary_case,
)
from tests.research.evaluation.test_parameter_neighborhood_summary import _effect_sources


def test_scientific_v3_contract_round_trip_and_offline_load(tmp_path) -> None:
    _, candidate, store = scientific_artifact_v3_case(tmp_path)
    outcome = store.commit(candidate)
    assert outcome.disposition is OnlyResearchArtifactDisposition.EXECUTED
    loaded = store.load_verified(candidate.result.manifest.research_result_fingerprint)

    assert loaded.manifest.profile == RESEARCH_SCIENTIFIC_ARTIFACT_V3_PROFILE
    assert loaded.manifest.schema_version == RESEARCH_SCIENTIFIC_ARTIFACT_V3_SCHEMA_VERSION
    assert loaded.manifest.research_result_schema_version == 2
    assert tuple(x.relative_path for x in loaded.manifest.sections) == RESEARCH_SCIENTIFIC_ARTIFACT_V3_SECTION_PATHS
    assert all(isinstance(x, OnlyResearchScientificLegacySeriesCatalogEntryV3) for x in loaded.statistics_catalog)
    assert all(x.payload_shape is OnlyResearchScientificStatisticsShapeV3.SERIES for x in loaded.statistics_catalog)
    assert not loaded.statistics_summaries
    assert store.commit(candidate).disposition is OnlyResearchArtifactDisposition.REUSED
    for entry in loaded.statistics_catalog:
        assert only_research_scientific_catalog_entry_v3_from_dict(entry.to_dict()) == entry


def test_scientific_v3_namespace_and_encoding_independent_identity(tmp_path) -> None:
    _, candidate, store = scientific_artifact_v3_case(tmp_path)
    identity = candidate.result.manifest.research_result_fingerprint
    first = store.commit(candidate)
    assert "research-scientific-v3" in str(store._target(identity))

    other = type(store)(tmp_path / "other", compression="gzip", row_group_size=1)
    second = other.commit(candidate)
    assert first.artifact_content_fingerprint == second.artifact_content_fingerprint
    first_loaded = store.load_verified(identity)
    second_loaded = other.load_verified(identity)
    assert any(
        left.byte_sha256 != right.byte_sha256
        for left, right in zip(first_loaded.manifest.sections, second_loaded.manifest.sections, strict=True)
        if left.relative_path.endswith(".parquet")
    )


def test_scientific_v3_offline_only_fresh_process_load(tmp_path) -> None:
    _, candidate, store = scientific_artifact_v3_case(tmp_path)
    store.commit(candidate)
    identity = candidate.result.manifest.research_result_fingerprint
    script = """
import sys
from pathlib import Path
from onlyalpha.research import OnlyParquetResearchScientificArtifactStoreV3
loaded = OnlyParquetResearchScientificArtifactStoreV3(Path(sys.argv[1])).load_verified(sys.argv[2])
print(loaded.manifest.artifact_content_fingerprint)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "scientific-artifacts"), identity],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == candidate.artifact_content_fingerprint


def test_scientific_v3_different_semantics_under_same_locator_conflict(tmp_path) -> None:
    _, candidate, store = scientific_artifact_v3_case(tmp_path)
    store.commit(candidate)
    first = candidate.market_rows[0]
    changed = replace(candidate, market_rows=(replace(first, close="999"), *candidate.market_rows[1:]))
    semantic = _semantic(changed)
    sections = tuple(
        OnlyResearchScientificSection(
            path,
            len(rows),
            only_research_scientific_v3_section_fingerprint(path.rsplit(".", 1)[0], rows),
            "0" * 64,
        )
        for path, rows in semantic.items()
    )
    changed = replace(
        changed,
        sections=sections,
        artifact_content_fingerprint=only_research_scientific_artifact_v3_content_fingerprint(
            candidate.result.manifest.research_result_fingerprint, sections
        ),
    )
    with pytest.raises(OnlyResearchArtifactStoreError) as raised:
        store.commit(changed)
    assert raised.value.code == "DETERMINISTIC_ARTIFACT_CONFLICT"


@pytest.mark.parametrize("factory", (summary_case, coverage_case, stability_case))
def test_scientific_v3_typed_summary_projects_and_verifies_offline(tmp_path, factory) -> None:  # type: ignore[no-untyped-def]
    case = factory(tmp_path)
    summary_plan, summary_store, executor = case[11], case[12], case[13]
    executor.execute(summary_plan)
    calculation = case[2].load_verified(summary_plan.subject.calculation_fingerprint).manifest
    member = OnlyResearchResultCalculationPlan(
        summary_plan.subject.calculation_fingerprint, calculation.calculation_graph_fingerprint
    )
    candidate_plan = OnlyResearchResultCandidatePlan(
        summary_plan.subject_candidate_fingerprint,
        "factor",
        (),
        member.calculation_fingerprint,
        member.graph_fingerprint,
        (summary_plan.statistics_fingerprint,),
    )
    result_plan = OnlyResearchResultPlan(
        (summary_plan.source_statistics_fingerprint, summary_plan.statistics_fingerprint),
        2,
        summary_plan.dataset_snapshot_fingerprint,
        (member,),
        (candidate_plan,),
    )
    reader = OnlyResearchStatisticsResultReader(tmp_path / "statistics-results", case[8], summary_store)
    result = OnlyResearchResultAssembler(
        reader,
        calculation_result_store=case[2],
        audit_time=lambda: datetime(2026, 9, 6, tzinfo=UTC),
    ).assemble(result_plan)
    results = OnlyJsonResearchResultStore(tmp_path / "research-results", reader, case[2])
    results.commit(result)
    artifact_candidate = OnlyResearchScientificArtifactMaterializerV3(results, case[7], case[2], reader).materialize(
        result_plan.fingerprint
    )
    store = OnlyParquetResearchScientificArtifactStoreV3(tmp_path / "artifacts")
    store.commit(artifact_candidate)
    loaded = store.load_verified(result.manifest.research_result_fingerprint)

    summaries = [x for x in loaded.statistics_catalog if isinstance(x, OnlyResearchScientificSummaryCatalogEntryV3)]
    assert len(summaries) == 1
    assert (
        loaded.statistics_summaries[0].summary.to_dict()
        == summary_store.load_verified(summary_plan.statistics_fingerprint).summary.to_dict()
    )
    assert not any(
        row.statistics_fingerprint == summary_plan.statistics_fingerprint for row in loaded.statistics_series_rows
    )
    _corrupt_summary_scalar_and_assert(store, result.manifest.research_result_fingerprint)


def test_scientific_v3_factor_pair_series_and_effect_verify_both_operands_offline(tmp_path) -> None:
    case = factor_pair_effect_case(tmp_path)
    pair_plan, pair_store = case[9], case[10]
    effect_plan, summary_store, executor = case[13], case[14], case[15]
    executor.execute(effect_plan)
    members = tuple(
        sorted(
            OnlyResearchResultCalculationPlan(
                operand.series.calculation_fingerprint,
                case[2].load_verified(operand.series.calculation_fingerprint).manifest.calculation_graph_fingerprint,
            )
            for operand in (pair_plan.first_operand, pair_plan.second_operand)
        )
    )
    by_calculation = {x.calculation_fingerprint: x for x in members}
    candidates = tuple(
        sorted(
            OnlyResearchResultCandidatePlan(
                operand.candidate_fingerprint,
                "factor",
                (),
                operand.series.calculation_fingerprint,
                by_calculation[operand.series.calculation_fingerprint].graph_fingerprint,
                (pair_plan.statistics_fingerprint, effect_plan.statistics_fingerprint),
            )
            for operand in (pair_plan.first_operand, pair_plan.second_operand)
        )
    )
    plan = OnlyResearchResultPlan(
        (pair_plan.statistics_fingerprint, effect_plan.statistics_fingerprint),
        2,
        pair_plan.dataset_snapshot_fingerprint,
        members,
        candidates,
    )
    reader = OnlyResearchStatisticsResultReader(tmp_path / "statistics-results", case[8], summary_store, pair_store)
    result = OnlyResearchResultAssembler(
        reader,
        calculation_result_store=case[2],
        audit_time=lambda: datetime(2026, 9, 6, tzinfo=UTC),
    ).assemble(plan)
    results = OnlyJsonResearchResultStore(tmp_path / "research-results", reader, case[2])
    results.commit(result)
    candidate = OnlyResearchScientificArtifactMaterializerV3(results, case[7], case[2], reader).materialize(
        plan.fingerprint
    )
    store = OnlyParquetResearchScientificArtifactStoreV3(tmp_path / "artifacts")
    store.commit(candidate)
    loaded = store.load_verified(result.manifest.research_result_fingerprint)

    assert {x.statistics_fingerprint for x in loaded.statistics_catalog} == {
        pair_plan.statistics_fingerprint,
        effect_plan.statistics_fingerprint,
    }
    assert (
        loaded.statistics_summaries[0].summary.to_dict()
        == summary_store.load_verified(effect_plan.statistics_fingerprint).summary.to_dict()
    )
    _corrupt_summary_scalar_and_assert(store, result.manifest.research_result_fingerprint)


def test_scientific_v3_parameter_neighborhood_preserves_assignments_and_dependencies(tmp_path) -> None:
    case, effects, bindings, neighborhood_plan = _effect_sources(tmp_path, 3)
    OnlyResearchParameterNeighborhoodSummaryExecutor(case[12]).execute(neighborhood_plan)
    calculation = case[2].load_verified(case[6].feature.calculation_fingerprint).manifest
    member = OnlyResearchResultCalculationPlan(
        case[6].feature.calculation_fingerprint, calculation.calculation_graph_fingerprint
    )
    effect_fingerprints = tuple(x.manifest.statistics_fingerprint for x in effects)
    candidates = tuple(
        sorted(
            OnlyResearchResultCandidatePlan(
                binding.candidate_fingerprint,
                "factor",
                tuple(sorted(binding.assignment.items())),
                member.calculation_fingerprint,
                member.graph_fingerprint,
                (
                    (effect_fingerprints[index], neighborhood_plan.statistics_fingerprint)
                    if index == 0
                    else (effect_fingerprints[index],)
                ),
            )
            for index, binding in enumerate(bindings)
        )
    )
    plan = OnlyResearchResultPlan(
        (case[6].statistics_fingerprint, *effect_fingerprints, neighborhood_plan.statistics_fingerprint),
        2,
        neighborhood_plan.dataset_snapshot_fingerprint,
        (member,),
        candidates,
    )
    reader = OnlyResearchStatisticsResultReader(tmp_path / "statistics-results", case[8], case[12])
    result = OnlyResearchResultAssembler(
        reader,
        calculation_result_store=case[2],
        audit_time=lambda: datetime(2026, 9, 6, tzinfo=UTC),
    ).assemble(plan)
    results = OnlyJsonResearchResultStore(tmp_path / "research-results", reader, case[2])
    results.commit(result)
    artifact_candidate = OnlyResearchScientificArtifactMaterializerV3(results, case[7], case[2], reader).materialize(
        plan.fingerprint
    )
    store = OnlyParquetResearchScientificArtifactStoreV3(tmp_path / "artifacts")
    store.commit(artifact_candidate)
    loaded = store.load_verified(result.manifest.research_result_fingerprint)
    neighborhood = next(
        x for x in loaded.statistics_catalog if x.statistics_fingerprint == neighborhood_plan.statistics_fingerprint
    )
    assert neighborhood.plan.to_dict() == neighborhood_plan.to_dict()
    summary = next(
        x for x in loaded.statistics_summaries if x.statistics_fingerprint == neighborhood_plan.statistics_fingerprint
    )
    assert (
        summary.summary.to_dict() == case[12].load_verified(neighborhood_plan.statistics_fingerprint).summary.to_dict()
    )
    _corrupt_summary_scalar_and_assert(store, result.manifest.research_result_fingerprint)


@pytest.mark.parametrize(
    "name",
    ("missing", "extra", "symlink", "byte", "logical", "artifact_identity", "statistics_identity"),
)
def test_scientific_v3_corruption_fails_closed(tmp_path, name: str) -> None:
    _, candidate, store = scientific_artifact_v3_case(tmp_path)
    store.commit(candidate)
    identity = candidate.result.manifest.research_result_fingerprint
    root = scientific_artifact_v3_target(tmp_path, identity)
    manifest_path = root / "artifact_manifest.json"
    if name == "missing":
        (root / "statistics_summaries.json").unlink()
    elif name == "extra":
        (root / "extra").write_text("x", encoding="utf-8")
    elif name == "symlink":
        path = root / "statistics_catalog.json"
        copy = root.parent / "catalog-copy.json"
        copy.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(copy)
    elif name == "byte":
        path = root / "market.parquet"
        path.write_bytes(path.read_bytes() + b"x")
    elif name == "logical":
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["sections"][0]["logical_fingerprint"] = "e" * 64
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    elif name == "artifact_identity":
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["artifact_content_fingerprint"] = "e" * 64
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        path = root / "statistics_catalog.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload[0]["result_content_fingerprint"] = "e" * 64
        path.write_text(json.dumps(payload), encoding="utf-8")
        _repair_section_envelope(root, path.name, payload)

    with pytest.raises(OnlyResearchArtifactStoreError) as raised:
        store.load_verified(identity)
    assert raised.value.code == "ARTIFACT_CORRUPT"


def test_scientific_v3_series_semantic_tamper_fails_after_physical_envelope_repair(tmp_path) -> None:
    _, candidate, store = scientific_artifact_v3_case(tmp_path)
    store.commit(candidate)
    identity = candidate.result.manifest.research_result_fingerprint
    root = scientific_artifact_v3_target(tmp_path, identity)
    path = root / "statistics_series.parquet"
    table = pq.read_table(path)
    rows = table.to_pylist()
    rows[0]["sample_count"] += 1
    changed = pa.Table.from_pylist(rows, schema=table.schema)
    pq.write_table(changed, path)
    _repair_section_envelope(root, path.name, changed.to_pylist())

    with pytest.raises(OnlyResearchArtifactStoreError) as raised:
        store.load_verified(identity)
    assert raised.value.code == "ARTIFACT_CORRUPT"


def _repair_section_envelope(root, relative_path: str, semantic_rows) -> None:  # type: ignore[no-untyped-def]
    manifest_path = root / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    descriptor = next(x for x in manifest["sections"] if x["relative_path"] == relative_path)
    descriptor["row_count"] = len(semantic_rows)
    descriptor["logical_fingerprint"] = only_research_scientific_v3_section_fingerprint(
        relative_path.rsplit(".", 1)[0], semantic_rows
    )
    descriptor["byte_sha256"] = sha256((root / relative_path).read_bytes()).hexdigest()
    sections = tuple(OnlyResearchScientificSection.from_dict(x) for x in manifest["sections"])
    manifest["artifact_content_fingerprint"] = only_research_scientific_artifact_v3_content_fingerprint(
        manifest["research_result_fingerprint"], sections
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _corrupt_summary_scalar_and_assert(store, identity: str) -> None:  # type: ignore[no-untyped-def]
    root = store._target(identity)
    path = root / "statistics_summaries.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    def corrupt(value):  # type: ignore[no-untyped-def]
        if isinstance(value, dict):
            if value.get("status") == "VALID" and "metric_id" in value:
                value["status"] = "NOT_APPLICABLE"
                return True
            return any(corrupt(member) for member in value.values())
        if isinstance(value, list):
            return any(corrupt(member) for member in value)
        return False

    assert corrupt(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")
    _repair_section_envelope(root, path.name, payload)
    with pytest.raises(OnlyResearchArtifactStoreError) as raised:
        store.load_verified(identity)
    assert raised.value.code == "ARTIFACT_CORRUPT"
