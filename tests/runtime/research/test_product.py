from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from onlyalpha.core.errors import OnlyLifecycleError
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.research import (
    OnlyParquetResearchDatasetSnapshotStore,
    OnlyParquetResearchScientificArtifactStore,
    OnlyResearchArtifactStoreError,
    OnlyResearchDefinitionResolver,
    OnlyResearchQueryService,
    OnlyResearchScientificSeriesQuery,
    OnlyResearchSpecificationResolver,
    only_research_scientific_artifact_content_fingerprint,
)
from onlyalpha.runtime.research import OnlyResearchRuntimeState
from onlyalpha.runtime.result import OnlyRuntimeResultStatus
from tests.research.calculation.support import snapshot
from tests.research.definition.support import definition
from tests.research.evaluation.support import evaluation_registry
from tests.research.specification.support import registry, specification
from tests.runtime.research.support import sweep_only_workload_case, workload_case


def test_engine_runs_exact_research_workload_and_fresh_engine_reuses_authorities(tmp_path: Path) -> None:
    first_engine, workload = workload_case(tmp_path)
    runtime_id = first_engine.add_research_workload(workload)
    validation = first_engine.validate()
    assert validation.valid and validation.cluster_count == 0 and validation.runtime_group_count == 1
    first_engine.initialize()
    assert first_engine.snapshot().plugin_resources == ()
    first_engine.start()
    first = first_engine.run_runtime(runtime_id)
    assert first.status is OnlyRuntimeResultStatus.COMPLETED
    assert first.direct_job_outcomes[0].disposition.value == "EXECUTED"
    assert first_engine.runtime_sessions[0].bound_cluster_ids == ()
    assert first.to_dict()["failure"] is None
    first_engine.stop()
    first_engine.close()

    second_engine, repeated = workload_case(tmp_path)
    repeated_id = second_engine.add_research_workload(repeated)
    second_engine.initialize()
    second_engine.start()
    second = second_engine.run_runtime(repeated_id)
    assert all(item.disposition.value == "REUSED" for item in second.direct_job_outcomes)
    assert all(item.disposition.value == "REUSED" for item in second.statistics_outcomes)
    assert second.research_result_fingerprint == first.research_result_fingerprint
    assert second.artifact_content_fingerprint == first.artifact_content_fingerprint
    assert second.determinism_fingerprint == first.determinism_fingerprint
    second_engine.stop()


def test_research_runtime_lifecycle_is_finite_and_run_once(tmp_path: Path) -> None:
    engine, workload = workload_case(tmp_path)
    runtime_id = engine.add_research_workload(workload)
    engine.initialize()
    runtime = engine.runtime_sessions[0].runtime
    assert runtime.state is OnlyResearchRuntimeState.READY
    runtime.initialize()
    engine.start()
    assert engine.run_runtime(runtime_id).status is OnlyRuntimeResultStatus.COMPLETED
    with pytest.raises(OnlyLifecycleError, match="cannot run from"):
        engine.run_runtime(runtime_id)
    engine.stop()
    assert runtime.state is OnlyResearchRuntimeState.CLOSED
    runtime.close()
    with pytest.raises(OnlyLifecycleError, match="cannot initialize"):
        runtime.initialize()


def test_research_runtime_rejects_start_before_initialize(tmp_path: Path) -> None:
    engine, workload = workload_case(tmp_path)
    runtime_id = engine.add_research_workload(workload)
    plan = engine._research_plans[str(runtime_id)]  # type: ignore[attr-defined]
    build = engine._require_services().assembler.build(plan, tmp_path)  # type: ignore[attr-defined]
    assert build.runtime is not None
    with pytest.raises(OnlyLifecycleError, match="cannot start"):
        build.runtime.start()
    build.runtime.close()


def test_unknown_runtime_and_wait_capabilities_fail_formally(tmp_path: Path) -> None:
    engine, workload = workload_case(tmp_path)
    engine.add_research_workload(workload)
    engine.initialize()
    engine.start()
    with pytest.raises(OnlyLifecycleError, match="RUNTIME_NOT_FOUND"):
        engine.run_runtime("unknown")
    with pytest.raises(OnlyLifecycleError, match="finite and cannot wait"):
        engine.wait(0)
    engine.stop()


def test_fresh_process_reentry_preserves_semantic_and_determinism_identity(tmp_path: Path) -> None:
    program = (
        "import json,sys; from pathlib import Path; "
        "from tests.runtime.research.support import workload_case; "
        "e,w=workload_case(Path(sys.argv[1])); r=e.add_research_workload(w); "
        "e.initialize(); e.start(); o=e.run_runtime(r); e.stop(); "
        "print(json.dumps({'result':o.research_result_fingerprint,'artifact':o.artifact_content_fingerprint,"
        "'determinism':o.determinism_fingerprint,'dispositions':[x.disposition.value for x in o.direct_job_outcomes]}))"
    )
    first = json.loads(subprocess.check_output([sys.executable, "-c", program, str(tmp_path)], text=True))
    second = json.loads(subprocess.check_output([sys.executable, "-c", program, str(tmp_path)], text=True))
    assert first["dispositions"] == ["EXECUTED", "EXECUTED"]
    assert second["dispositions"] == ["REUSED", "REUSED"]
    assert {key: first[key] for key in ("result", "artifact", "determinism")} == {
        key: second[key] for key in ("result", "artifact", "determinism")
    }


def test_sweep_only_workload_preserves_sweep_execution_outcome(tmp_path: Path) -> None:
    engine, workload = sweep_only_workload_case(tmp_path)
    runtime_id = engine.add_research_workload(workload)
    engine.initialize()
    engine.start()
    result = engine.run_runtime(runtime_id)
    assert result.status is OnlyRuntimeResultStatus.COMPLETED
    assert result.direct_job_outcomes == ()
    assert len(result.sweep_outcomes) == 2
    assert all(item.total_cells == 1 and item.cells[0].ordinal == 0 for item in result.sweep_outcomes)
    assert result.to_dict()["sweep_outcomes"][0]["executed_count"] == 1  # type: ignore[index]
    engine.stop()


def test_specification_resolved_and_manual_workloads_have_full_runtime_equivalence(tmp_path: Path) -> None:
    manual_engine, manual_workload = workload_case(tmp_path)
    manual_id = manual_engine.add_research_workload(manual_workload)
    manual_engine.initialize()
    manual_engine.start()
    manual = manual_engine.run_runtime(manual_id)
    manual_engine.stop()

    resolved_engine, repeated = workload_case(tmp_path)
    resolved = OnlyResearchSpecificationResolver(registry()).resolve(
        specification(repeated.dataset_snapshot_fingerprint)
    )
    resolved_id = resolved_engine.add_research_workload(resolved.workload)
    resolved_engine.initialize()
    resolved_engine.start()
    result = resolved_engine.run_runtime(resolved_id)
    resolved_engine.stop()

    assert [item.calculation_fingerprint for item in result.direct_job_outcomes] == [
        item.calculation_fingerprint for item in manual.direct_job_outcomes
    ]
    assert [item.statistics_fingerprint for item in result.statistics_outcomes] == [
        item.statistics_fingerprint for item in manual.statistics_outcomes
    ]
    assert result.research_result_fingerprint == manual.research_result_fingerprint
    assert result.artifact_content_fingerprint == manual.artifact_content_fingerprint
    assert result.determinism_fingerprint == manual.determinism_fingerprint


def test_definition_v2_runs_in_fresh_runtime_and_publishes_self_contained_scientific_artifact(tmp_path: Path) -> None:
    layout = OnlyUserDataLayout(tmp_path)
    datasets = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
    candidate, partitions = snapshot()
    committed = datasets.commit(candidate, partitions)

    class Resolver:
        def resolve_verified(self, expected):  # type: ignore[no-untyped-def]
            value = datasets.load_verified_table(committed.snapshot_fingerprint)
            if value.snapshot.definition != expected:
                raise ValueError("Dataset mismatch")
            return value

    resolved = OnlyResearchDefinitionResolver(evaluation_registry(), Resolver()).resolve(
        definition(committed.definition)
    )
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("scientific-v2"), tmp_path))
    runtime_id = engine.add_research_workload(resolved.workload)
    engine.initialize()
    engine.start()
    outcome = engine.run_runtime(runtime_id)
    engine.stop()
    assert outcome.status is OnlyRuntimeResultStatus.COMPLETED
    assert outcome.research_result_fingerprint is not None
    store = OnlyParquetResearchScientificArtifactStore(layout.research_artifact_root)
    artifact = store.load_verified(outcome.research_result_fingerprint)
    assert artifact.manifest.profile == "RESEARCH_SCIENTIFIC_V2"
    assert artifact.variable_rows and artifact.signal_rows and artifact.market_rows and artifact.graphs
    assert any(row.value is None for row in artifact.signal_rows)
    physically_distinct = tuple(replace(item, byte_sha256="f" * 64) for item in artifact.manifest.sections)
    assert (
        only_research_scientific_artifact_content_fingerprint(outcome.research_result_fingerprint, physically_distinct)
        == artifact.manifest.artifact_content_fingerprint
    )
    artifact_root = (
        layout.research_artifact_root
        / "research-scientific-v2"
        / "sha256"
        / outcome.research_result_fingerprint[:2]
        / outcome.research_result_fingerprint
    )
    variable_path = artifact_root / "variables.parquet"
    original_variables = variable_path.read_bytes()
    variable_path.write_bytes(b"corrupt")
    with pytest.raises(OnlyResearchArtifactStoreError) as corrupt:
        store.load_verified(outcome.research_result_fingerprint)
    assert corrupt.value.code == "ARTIFACT_CORRUPT"
    variable_path.write_bytes(original_variables)
    extra = artifact_root / "unexpected"
    extra.write_text("forbidden", encoding="utf-8")
    with pytest.raises(OnlyResearchArtifactStoreError):
        store.load_verified(outcome.research_result_fingerprint)
    extra.unlink()
    query = OnlyResearchQueryService(store)
    candidates = query.list_candidates(outcome.research_result_fingerprint)
    variables = query.list_published_series(outcome.research_result_fingerprint)
    instrument = artifact.market_rows[0].instrument_id
    market = query.get_market_series(
        OnlyResearchScientificSeriesQuery(outcome.research_result_fingerprint, instrument_id=instrument, limit=2)
    )
    variable = variables.series[0]
    variable_page = query.get_variable_series(
        OnlyResearchScientificSeriesQuery(
            outcome.research_result_fingerprint,
            instrument_id=instrument,
            candidate_fingerprint=variable.candidate_fingerprint,
            calculation_fingerprint=variable.calculation_fingerprint,
            node_fingerprint=variable.node_fingerprint,
            output_name=variable.output_name,
            limit=2,
        )
    )
    null_signal = next(row for row in artifact.signal_rows if row.value is None and row.instrument_id == instrument)
    signal = next(
        item
        for item in artifact.manifest.plan.signals
        if item.candidate_fingerprint == null_signal.candidate_fingerprint and item.role == null_signal.role
    )
    signal_page = query.get_signal_series(
        OnlyResearchScientificSeriesQuery(
            outcome.research_result_fingerprint,
            instrument_id=instrument,
            candidate_fingerprint=signal.candidate_fingerprint,
            role=signal.role,
            limit=100,
        )
    )
    graph = query.get_candidate_graph(
        outcome.research_result_fingerprint, candidates.candidates[0].candidate_fingerprint
    )
    assert market.points and variable_page.points and signal_page.points
    assert any(point.value is None for point in signal_page.points)
    assert graph.graph.fingerprint == candidates.candidates[0].graph_fingerprint
    shutil.rmtree(layout.research_dataset_root)
    shutil.rmtree(layout.research_calculation_result_root)
    shutil.rmtree(layout.research_statistics_result_root)
    shutil.rmtree(layout.research_result_root)
    assert store.load_verified(outcome.research_result_fingerprint).manifest == artifact.manifest
    assert query.list_candidates(outcome.research_result_fingerprint) == candidates
