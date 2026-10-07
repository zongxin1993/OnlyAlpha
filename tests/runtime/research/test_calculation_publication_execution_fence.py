from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendResolver
from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.job import OnlyResearchJobExecutor, OnlyResearchJobPlan
from onlyalpha.research.runtime_errors import OnlyResearchRuntimeError, OnlyResearchRuntimePhase
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from onlyalpha.research.workload import OnlyResearchWorkloadPlan
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.factory import OnlyRuntimeBuildRequest
from onlyalpha.runtime.research import (
    OnlyResearchRuntime,
    OnlyResearchRuntimeEnvironmentIdentity,
    OnlyResearchRuntimeFactory,
    OnlyResearchRuntimePlan,
    only_research_runtime_plan,
)
from onlyalpha.runtime.research import factory as research_factory
from tests.research.job.support import readiness_job_case
from tests.research.specification.support import registry, scientific_specification, specification
from tests.research.specification.test_calculation_publication import publication_registry, publication_specification

_UNSUPPORTED = "RESEARCH_CALCULATION_PUBLICATION_EXECUTION_UNSUPPORTED"


def _publication_workload(dataset: str = "a" * 64, period: int = 3) -> OnlyResearchWorkloadPlan:
    workload = (
        OnlyResearchSpecificationResolver(publication_registry())
        .resolve(publication_specification(dataset, period))
        .workload
    )
    assert workload.direct_jobs[0].schema_version == 2
    assert workload.result_plan.schema_version == 4
    assert workload.sweeps == workload.statistics_plans == ()
    assert workload.result_plan.publication == publication_specification(dataset, period).publication
    return workload


def _legacy_calculation_workload(workload: OnlyResearchWorkloadPlan) -> OnlyResearchWorkloadPlan:
    job = workload.direct_jobs[0]
    return OnlyResearchWorkloadPlan(
        (OnlyResearchJobPlan(job.dataset_snapshot_fingerprint, job.calculation_graph),),
        (),
        (),
        replace(workload.result_plan, schema_version=3, publication=None),
    )


def _assert_unsupported(operation: Callable[[], object]) -> None:
    with pytest.raises(OnlyResearchRuntimeError) as raised:
        operation()
    assert raised.value.phase is OnlyResearchRuntimePhase.PLAN_VALIDATION
    assert raised.value.code == _UNSUPPORTED


@pytest.mark.parametrize(
    "version,plan_fingerprint,environment_fingerprint,profile",
    (
        (
            1,
            "d20c70c21017d7eb4295952f3f4c8598890bcf7b9e51021f783472de576fead4",
            "93091efa50b6df9023068a959de73a94e4988b0f7a96c15af5d742f55daad132",
            "RESEARCH_STATISTICS_V1",
        ),
        (
            2,
            "0180b932cb7eaa39bac7dd9de40884e27b4655596d8afdea1bb87db9f0bdc401",
            "ec796429995a8b060e19bef8071e5885f11e0b8f7679936dbf622b4c326c33b3",
            "RESEARCH_SCIENTIFIC_V2",
        ),
        (
            3,
            "fafb257acf615d17ea93a6e3ac42bb2d1a86776cf4c83a2870584627136f5fdc",
            "49809d8cda6d5a5d0e6a74ebcc734e88b874dacb1ec9c10f9bdf66b88611f1f6",
            "RESEARCH_STATISTICS_V1",
        ),
    ),
)
def test_legacy_runtime_environment_exact_payload_and_fingerprint_are_unchanged(
    version: int, plan_fingerprint: str, environment_fingerprint: str, profile: str
) -> None:
    workload = (
        _legacy_calculation_workload(_publication_workload())
        if version == 3
        else OnlyResearchSpecificationResolver(registry())
        .resolve(specification() if version == 1 else scientific_specification())
        .workload
    )
    plan = only_research_runtime_plan(workload)
    assert asdict(plan.environment) == {
        "dataset_snapshot_fingerprint": "a" * 64,
        "calculation_fingerprints": (
            ("22e7186aebc38a468726fc2865f2c5bc484aa7077b8ad7e6c8e48253f3421533",)
            if version == 3
            else (
                "459eed3db853864c0e4d67723b05ebd870e9d7a9a0fd6a8eb30d0e6da59808d8",
                "5de1baddaad18393b750f597391d3dc37231df5bdc5b653b5852d4175bbe93e6",
            )
        ),
        "statistics_fingerprints": (
            () if version == 3 else ("205ed872052f0917c2a21b81ff86ae74262366297b2dcf47845693b7fe440030",)
        ),
        "research_result_plan_fingerprint": plan_fingerprint,
        "artifact_profile": profile,
        "runtime_type": "RESEARCH",
    }
    assert plan.environment.fingerprint == environment_fingerprint
    assert str(plan.runtime_id) == f"research-{environment_fingerprint[:16]}"


@pytest.mark.parametrize("dataset,period", (("a" * 64, 1), ("b" * 64, 3)))
@pytest.mark.parametrize("entry", (OnlyResearchRuntimeEnvironmentIdentity.from_workload, only_research_runtime_plan))
def test_result_plan_v4_cannot_form_legacy_runtime_identity(
    dataset: str, period: int, entry: Callable[[OnlyResearchWorkloadPlan], object]
) -> None:
    workload = _publication_workload(dataset, period)
    before = workload.result_plan.to_dict()
    _assert_unsupported(lambda: entry(workload))
    assert workload.result_plan.to_dict() == before


@pytest.mark.parametrize("entry", ("validate", "create"))
@pytest.mark.parametrize("complete_request", (False, True))
def test_manual_result_plan_v4_factory_rejects_before_composition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: str, complete_request: bool
) -> None:
    workload = _publication_workload()
    environment = OnlyResearchRuntimeEnvironmentIdentity.from_workload(_legacy_calculation_workload(workload))
    plan = OnlyResearchRuntimePlan(OnlyRuntimeId("manual-compile-only"), environment, workload)
    components = only_default_engine_services().assembler.components if complete_request else object()
    request = OnlyRuntimeBuildRequest(plan, components, tmp_path if complete_request else None)
    constructors = []
    for name in (
        "OnlyUserDataLayout",
        "OnlyParquetResearchDatasetSnapshotStore",
        "OnlyResearchCalculationExecutor",
        "OnlyParquetResearchCalculationResultStore",
        "OnlyResearchCalculationExecutionEvidenceStore",
        "OnlyResearchJobExecutor",
        "OnlyResearchSweepExecutor",
        "OnlyResearchStatisticsExecutor",
        "OnlyResearchResultAssembler",
        "OnlyJsonResearchResultStore",
        "OnlyResearchArtifactMaterializer",
        "OnlyParquetResearchArtifactStore",
        "OnlyResearchScientificArtifactMaterializer",
        "OnlyParquetResearchScientificArtifactStore",
        "OnlyParquetResearchCalculationArtifactStore",
        "OnlyResearchRuntime",
    ):
        spy = Mock(wraps=getattr(research_factory, name))
        monkeypatch.setattr(research_factory, name, spy)
        constructors.append(spy)
    outcome = getattr(OnlyResearchRuntimeFactory(), entry)(request)
    assert outcome.failure_code == _UNSUPPORTED
    assert outcome.runtime is None
    assert all(spy.mock_calls == [] for spy in constructors)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("entry", ("constructor", "initialize", "ready-initialize", "run", "async-run"))
@pytest.mark.parametrize("existing_publication", (False, True))
def test_direct_runtime_plan_v4_never_touches_functional_job_v2_authorities(
    tmp_path: Path, entry: str, existing_publication: bool
) -> None:
    fixture_plan, _, legacy, results, evidence = readiness_job_case(tmp_path)
    workload = _publication_workload(fixture_plan.dataset_snapshot_fingerprint, 2)
    datasets = Mock(wraps=OnlyParquetResearchDatasetSnapshotStore(tmp_path / "datasets"))
    calculation = Mock(
        wraps=OnlyResearchCalculationExecutor(datasets, OnlyResearchCalculationBackendResolver(publication_registry()))
    )
    results_spy, evidence_spy = Mock(wraps=results), Mock(wraps=evidence)
    legacy_spy, legacy_evidence_spy = Mock(wraps=legacy), Mock(wraps=legacy._test_execution_evidence_store)
    job = Mock(
        wraps=OnlyResearchJobExecutor(
            calculation,
            legacy_spy,
            legacy_evidence_spy,
            readiness_result_store=results_spy,
            readiness_execution_evidence_store=evidence_spy,
        )
    )
    # Prove these exact authorities can execute and publish; an unavailable V2
    # store or a backend stub must not be the reason the Runtime test passes.
    functional = job.execute(workload.direct_jobs[0])
    assert functional.disposition.value == "EXECUTED"
    assert results_spy.commit.call_count == evidence_spy._publish_verified.call_count == 1
    if not existing_publication:
        # Use a different, complete Calculation rather than deleting valid facts.
        workload = _publication_workload(fixture_plan.dataset_snapshot_fingerprint, 3)
    sweep, statistics, assembler, result_store, materializer, artifact_store = [Mock() for _ in range(6)]
    downstream = [sweep, statistics, assembler, result_store, materializer, artifact_store]
    authorities = [datasets, calculation, job, legacy_spy, legacy_evidence_spy, results_spy, evidence_spy, *downstream]
    for spy in authorities:
        spy.reset_mock()
    before = {str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    legacy_workload = _legacy_calculation_workload(workload)
    environment = OnlyResearchRuntimeEnvironmentIdentity.from_workload(legacy_workload)

    def construct(selected: OnlyResearchWorkloadPlan) -> OnlyResearchRuntime:
        return OnlyResearchRuntime(
            OnlyRuntimeId("direct-compile-only"),
            environment,
            selected,
            datasets,
            job,
            sweep,
            statistics,
            assembler,
            result_store,
            materializer,
            artifact_store,
        )

    if entry == "constructor":
        _assert_unsupported(lambda: construct(workload))
    else:
        runtime = construct(legacy_workload)
        if entry in {"ready-initialize", "run", "async-run"}:
            runtime.initialize()
        if entry in {"run", "async-run"}:
            runtime.start()
        runtime.workload = workload
        if entry in {"initialize", "ready-initialize"}:
            _assert_unsupported(runtime.initialize)
        else:
            control = Mock()
            outcome = runtime.run(control) if entry == "run" else asyncio.run(asyncio.to_thread(runtime.run, control))
            assert outcome.status.value == "FAILED"
            assert outcome.phase is OnlyResearchRuntimePhase.PLAN_VALIDATION
            assert outcome.code == _UNSUPPORTED
            assert outcome.direct_job_outcomes == ()
            assert outcome.calculation_execution_evidence_fingerprints == ()
            assert not outcome.research_result_fingerprint
            assert not outcome.artifact_content_fingerprint
            assert control.mock_calls == []
        runtime.close()
    assert all(spy.mock_calls == [] for spy in authorities)
    assert {
        str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    } == before
