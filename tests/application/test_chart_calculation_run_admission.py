from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.run.errors import OnlyResearchRunIntegrityError
from onlyalpha.research.run.model import OnlyResearchOriginKind, OnlyResearchRun, OnlyResearchRunState
from tests.application.test_chart_calculation_admission import NOW
from tests.application.test_chart_calculation_compilation import compilation
from tests.support.chart_calculation_compilation import prepared_input


def chart_run(system):
    frozen = compilation(system)
    return OnlyResearchRun(
        system.operation.reserved_run_id,
        0,
        OnlyResearchRunState.QUEUED,
        frozen.specification,
        frozen.specification_fingerprint,
        only_canonical_json(frozen.specification.to_dict()),
        frozen.compilation_fingerprint,
        NOW,
        origin_kind=OnlyResearchOriginKind.CHART_CALCULATION,
    )


def admission_service(system, store):
    from onlyalpha.application.chart_calculation_run_admission import OnlyChartCalculationRunAdmissionService

    system.compilations.load_verified.return_value = compilation(system)
    return OnlyChartCalculationRunAdmissionService(
        preparations=system.preparations,
        compilations=system.compilations,
        datasets=system.dataset,
        materializations=system.dataset,
        runtime_generations=system.runtime,
        runs=store,
    )


def test_typed_origin_requires_publication_and_never_infers_general(tmp_path: Path) -> None:
    system = prepared_input(tmp_path)
    run = chart_run(system)
    assert run.run_id == system.operation.reserved_run_id
    assert run.state is OnlyResearchRunState.QUEUED and run.revision == 0
    assert run.admission_resolution_fingerprint == compilation(system).compilation_fingerprint
    with pytest.raises(OnlyResearchRunIntegrityError):
        replace(run, origin_kind=OnlyResearchOriginKind.GENERAL)
    with pytest.raises(OnlyResearchRunIntegrityError):
        run.transition(OnlyResearchRunState.RUNNING, at=NOW)
    assert run.transition(OnlyResearchRunState.CANCELLED, at=NOW).origin_kind is run.origin_kind


def test_admission_consumes_frozen_compilation_without_resolving_or_executing(tmp_path: Path) -> None:
    system = prepared_input(tmp_path)
    store = Mock()
    run = chart_run(system)
    store.load_verified.return_value = None
    store.commit_or_replay.return_value = run
    assert admission_service(system, store).admit(system.operation, queued_at=NOW) == run
    system.resolver.resolve_calculation_publication.assert_not_called()
    system.runtime.bind_new_work_exact.assert_not_called()
    system.runtime.release_work.assert_not_called()
    system.compilations.commit_or_replay.assert_not_called()


def test_historical_exact_replay_never_requests_new_work_permission(tmp_path: Path) -> None:
    system = prepared_input(tmp_path)
    store = Mock()
    run = chart_run(system)
    store.load_verified.return_value = run
    system.runtime.require_work_binding_evidence.return_value = replace(system.binding, active=False)
    system.runtime.require_new_work_generation.side_effect = AssertionError("historical replay requires no activation")
    assert admission_service(system, store).admit(system.operation, queued_at=NOW) == run
    store.commit_or_replay.assert_not_called()
    system.runtime.require_new_work_generation.assert_not_called()


@pytest.mark.parametrize("failure", ["inactive", "retired", "missing_compilation", "missing_binding", "input"])
def test_incomplete_or_ineligible_proof_never_admits(tmp_path: Path, failure: str) -> None:
    system = prepared_input(tmp_path)
    store = Mock()
    store.load_verified.return_value = None
    service = admission_service(system, store)
    if failure == "inactive":
        system.runtime.require_work_binding_evidence.return_value = replace(system.binding, active=False)
    elif failure == "retired":
        system.runtime.require_runtime_generation.side_effect = ValueError("RUNTIME_GENERATION_UNAVAILABLE")
    elif failure == "missing_compilation":
        system.compilations.load_verified.return_value = None
    elif failure == "missing_binding":
        system.runtime.require_work_binding_evidence.side_effect = ValueError("RUNTIME_WORK_GENERATION_UNBOUND")
    else:
        system.dataset.load_verified_table = Mock(side_effect=FileNotFoundError("input unavailable"))
    with pytest.raises(ValueError):
        service.admit(system.operation, queued_at=NOW)
    store.commit_or_replay.assert_not_called()
    system.runtime.release_work.assert_not_called()
