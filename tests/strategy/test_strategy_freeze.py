from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research import (
    OnlyJsonResearchResultStore,
    OnlyParquetResearchCalculationResultStore,
    OnlyParquetResearchStatisticsResultStore,
    OnlyResearchCalculationBackendResolver,
    OnlyResearchCalculationExecutionEvidenceStore,
    OnlyResearchCalculationExecutor,
    OnlyResearchDefinitionResolver,
    OnlyResearchJobExecutor,
    OnlyResearchResultAssembler,
    OnlyResearchStatisticsExecutor,
    OnlyResearchSweepExecutor,
)
from onlyalpha.research.run import (
    OnlyResearchRun,
    OnlyResearchRunId,
    OnlyResearchRunState,
    only_research_admission_resolution_fingerprint,
)
from onlyalpha.research.specification import OnlyResearchSpecificationResolver
from onlyalpha.strategy import OnlyStrategyTradingAdmissionService
from onlyalpha.strategy.errors import OnlyStrategyFreezeError
from onlyalpha.strategy.freeze import (
    OnlyInMemoryStrategyCatalog,
    OnlyStrategyFreezeDisposition,
    OnlyStrategyFreezeRequest,
    OnlyStrategyFreezeService,
)
from onlyalpha.strategy.store import _only_compose_frozen_strategy_authority
from tests.research.definition.support import definition
from tests.strategy.p9_support import _Datasets, p9_strategy_case

NOW = datetime(2026, 8, 24, tzinfo=UTC)


class _Runs:
    def __init__(self, run):
        self.run = run

    def load(self, run_id):
        assert run_id == self.run.run_id
        return self.run


class _BrokenVerifiedStore:
    def load_verified(self, fingerprint):
        del fingerprint
        raise ValueError("corrupt immutable authority")


class _BrokenDatasetStore:
    def load_verified_table(self, fingerprint):
        del fingerprint
        raise ValueError("corrupt Dataset authority")


def _freeze_case(tmp_path, *, semantic_root=None, values=None):
    case = p9_strategy_case(tmp_path / "base", values=values)
    semantic_root = tmp_path / "semantic" if semantic_root is None else semantic_root
    resolved_definition = OnlyResearchDefinitionResolver(
        case.registry,
        _Datasets(case.dataset_store, case.dataset_fingerprint),
    ).resolve(definition(case.dataset_store.load_verified_table(case.dataset_fingerprint).snapshot.definition))
    workload = resolved_definition.workload
    calculation_store = OnlyParquetResearchCalculationResultStore(
        tmp_path / "calculation-results", case.dataset_store, audit_time=lambda: NOW
    )
    calculation_executor = OnlyResearchCalculationExecutor(
        case.dataset_store, OnlyResearchCalculationBackendResolver(case.registry)
    )
    execution_evidence_store = OnlyResearchCalculationExecutionEvidenceStore(semantic_root)
    job = OnlyResearchJobExecutor(calculation_executor, calculation_store, execution_evidence_store)
    sweep = OnlyResearchSweepExecutor(job)
    evidence_fingerprints: set[str] = set()
    for plan in workload.direct_jobs:
        evidence_fingerprints.add(job.execute(plan).calculation_execution_evidence_fingerprint)
    for plan in workload.sweeps:
        evidence_fingerprints.update(
            item.calculation_execution_evidence_fingerprint for item in sweep.execute(plan).cells
        )
    statistics_store = OnlyParquetResearchStatisticsResultStore(
        tmp_path / "statistics-results", calculation_store, audit_time=lambda: NOW
    )
    statistics_executor = OnlyResearchStatisticsExecutor(calculation_store, statistics_store)
    for plan in workload.statistics_plans:
        statistics_executor.execute(plan)
    research_store = OnlyJsonResearchResultStore(tmp_path / "research-results", statistics_store, calculation_store)
    assembled = OnlyResearchResultAssembler(
        statistics_store,
        audit_time=lambda: NOW,
        calculation_result_store=calculation_store,
    ).assemble(workload.result_plan)
    result = research_store.commit(assembled)
    resolution = resolved_definition.specification_resolution
    queued = OnlyResearchRun.queued(
        run_id=OnlyResearchRunId("00000000-0000-4000-8000-000000000901"),
        specification=resolved_definition.specification,
        canonical_specification_payload=only_canonical_json(resolved_definition.specification.to_dict()),
        admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(resolution),
        queued_at=NOW,
    )
    run = queued.transition(OnlyResearchRunState.RUNNING, at=NOW + timedelta(seconds=1)).transition(
        OnlyResearchRunState.COMPLETED,
        at=NOW + timedelta(seconds=2),
        research_result_fingerprint=result.research_result_fingerprint,
        artifact_content_fingerprint="f" * 64,
        calculation_execution_evidence_fingerprints=tuple(sorted(evidence_fingerprints)),
    )
    store, publisher = _only_compose_frozen_strategy_authority(semantic_root)
    catalog = OnlyInMemoryStrategyCatalog()
    service = OnlyStrategyFreezeService(
        runs=_Runs(run),
        research_results=research_store,
        calculation_results=calculation_store,
        calculation_execution_evidence=execution_evidence_store,
        datasets=case.dataset_store,
        specification_resolver=OnlyResearchSpecificationResolver(case.registry),
        admission=OnlyStrategyTradingAdmissionService(case.registry, case.equivalence),
        strategies=store,
        strategy_publisher=publisher,
        catalog=catalog,
        audit_time=lambda: NOW,
    )
    candidate = next(item for item in resolution.candidates if item.calculation_id == "decision")
    return service, run, candidate, store, catalog


def test_freeze_reconstructs_and_idempotently_commits_exact_strategy(tmp_path) -> None:
    service, run, candidate, store, catalog = _freeze_case(tmp_path)
    request = OnlyStrategyFreezeRequest(run.run_id, candidate.candidate_fingerprint, "certifier")

    created = service.freeze(request)
    reused = service.freeze(request)

    assert created.disposition is OnlyStrategyFreezeDisposition.CREATED
    assert reused.disposition is OnlyStrategyFreezeDisposition.REUSED
    assert reused.strategy_fingerprint == created.strategy_fingerprint
    assert store.load_verified(created.strategy_fingerprint).strategy_fingerprint.value == created.strategy_fingerprint
    assert len(catalog.freeze_records) == 1
    assert created.freeze_record.equivalence_evidence_fingerprints
    assert created.freeze_record.research_execution_evidence_fingerprints
    assert created.freeze_record.admission_evidence_fingerprint


def test_freeze_recomputes_candidate_and_rejects_unverified_identity(tmp_path) -> None:
    service, run, _, _, _ = _freeze_case(tmp_path)

    with pytest.raises(OnlyStrategyFreezeError) as error:
        service.freeze(OnlyStrategyFreezeRequest(run.run_id, "e" * 64, "certifier"))
    assert error.value.code == "CANDIDATE_NOT_FOUND"


def test_freeze_rejects_non_completed_run(tmp_path) -> None:
    service, run, candidate, _, _ = _freeze_case(tmp_path)
    service._runs = _Runs(  # type: ignore[attr-defined]
        OnlyResearchRun.queued(
            run_id=run.run_id,
            specification=run.specification,
            canonical_specification_payload=run.canonical_specification_payload,
            admission_resolution_fingerprint=run.admission_resolution_fingerprint,
            queued_at=NOW,
        )
    )

    with pytest.raises(OnlyStrategyFreezeError) as error:
        service.freeze(OnlyStrategyFreezeRequest(run.run_id, candidate.candidate_fingerprint, "certifier"))
    assert error.value.code == "CANDIDATE_NOT_FOUND"


def test_legacy_completed_run_without_execution_provenance_cannot_freeze(tmp_path) -> None:
    service, run, candidate, _, _ = _freeze_case(tmp_path)
    service._runs = _Runs(  # type: ignore[attr-defined]
        replace(run, calculation_execution_evidence_fingerprints=())
    )

    with pytest.raises(OnlyStrategyFreezeError) as error:
        service.freeze(OnlyStrategyFreezeRequest(run.run_id, candidate.candidate_fingerprint, "certifier"))
    assert error.value.code == "RESEARCH_EXECUTION_PROVENANCE_UNAVAILABLE"


@pytest.mark.parametrize(
    ("attribute", "replacement", "code"),
    (
        ("_research_results", _BrokenVerifiedStore(), "RESEARCH_RESULT_CORRUPT"),
        ("_calculation_results", _BrokenVerifiedStore(), "CALCULATION_RESULT_CORRUPT"),
        ("_datasets", _BrokenDatasetStore(), "RESEARCH_RESULT_CORRUPT"),
    ),
)
def test_freeze_verified_authority_failure_has_stable_code_and_no_publication(
    tmp_path,
    attribute,
    replacement,
    code,
) -> None:
    service, run, candidate, _, catalog = _freeze_case(tmp_path)
    setattr(service, attribute, replacement)

    with pytest.raises(OnlyStrategyFreezeError) as error:
        service.freeze(OnlyStrategyFreezeRequest(run.run_id, candidate.candidate_fingerprint, "certifier"))

    assert error.value.code == code
    assert not catalog.strategies
    assert not (tmp_path / "semantic" / "strategy" / "frozen-revisions").exists()
