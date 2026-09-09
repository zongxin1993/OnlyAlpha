from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from onlyalpha.application.search_generation_execution import (
    OnlyHistoricalGenerationCapabilityUnsupported,
    OnlyHistoricalGenerationExecutionMismatch,
    OnlyHistoricalGenerationWorkerUnavailable,
    OnlySearchGenerationExecutionResponseV1,
    OnlySearchGenerationOperationV1,
)
from onlyalpha.application.search_product import only_search_experiment_work_id
from onlyalpha.research.command import OnlyResearchCommandService, only_derived_research_run_id
from onlyalpha.research.run import OnlyResearchRunAdmissionError, OnlyResearchRunAdmissionService
from onlyalpha.research.run.evidence import OnlyResearchAdmissionResolutionEvidence
from onlyalpha.research.run.generation import OnlyResearchHostedRuntimeGenerationResolver
from onlyalpha.research.specification import OnlyResearchSpecificationResolver
from tests.research.command.test_service import KEY, NOW, _DatasetStore, _ProductAdmissions, _provenance, _Store
from tests.research.specification.support import registry, specification

G = "a" * 64
PARENT = only_search_experiment_work_id("b" * 64)


class _Bindings:
    def __init__(self) -> None:
        self.work = {PARENT: G}

    def require_work_binding(self, work):  # type: ignore[no-untyped-def]
        return SimpleNamespace(runtime_generation_fingerprint=self.work[work], active=True)

    def bind_derived_work(self, parent, child, **_):  # type: ignore[no-untyped-def]
        self.work[child] = self.work[parent]


class _ParentTrap:
    calls = 0

    def resolve(self, _):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise RuntimeError("PARENT_CANNOT_EXECUTE_HISTORICAL_G1")


class _Execution:
    def __init__(self) -> None:
        self.requests = []
        self.failure = None
        self.generation = G
        self.specification_fingerprint = None
        self.operation = None

    def execute(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        evidence = OnlyResearchAdmissionResolutionEvidence.from_resolution(
            OnlyResearchSpecificationResolver(registry()).resolve(specification())
        ).to_dict()
        if self.specification_fingerprint is not None:
            evidence["specification_fingerprint"] = self.specification_fingerprint
        return OnlySearchGenerationExecutionResponseV1(
            self.generation, self.operation or request.operation_kind, {"admission_evidence": evidence}
        )


def _system(*, execution=None, dataset=None, store=None, authoring=None, bindings=None):  # type: ignore[no-untyped-def]
    trap = _ParentTrap()
    bindings = bindings or _Bindings()
    store = store or _Store()
    dataset = dataset or _DatasetStore()
    admissions = _ProductAdmissions()
    admission = OnlyResearchRunAdmissionService(
        resolver=trap,
        dataset_store=dataset,
        run_store=store,
        now_utc=lambda: NOW,
        authoring_generation_resolver=authoring,
    )
    resolver = (
        None
        if execution is None
        else OnlyResearchHostedRuntimeGenerationResolver(
            execution=execution,
            dataset_store_root="/exact-dataset-store",
        )
    )
    service = OnlyResearchCommandService(
        admission=admission,
        store=store,
        now_utc=lambda: NOW,
        runtime_generations=bindings,
        command_admissions=admissions,
        runtime_generation_resolver=resolver,
    )
    return service, trap, bindings, store, admissions, dataset


def test_real_command_and_admission_use_exact_evidence_without_parent_resolution() -> None:
    execution = _Execution()
    service, trap, bindings, store, admissions, dataset = _system(execution=execution)
    outcome = service.submit_research_run(KEY, specification(), parent_runtime_work_id=PARENT)
    assert trap.calls == 0
    assert outcome.run.run_id == only_derived_research_run_id(KEY)
    assert bindings.work[outcome.run.run_id.value] == G
    assert execution.requests[0].runtime_generation_fingerprint == G
    assert dataset.loads == 1
    assert outcome.run.admission_resolution_fingerprint == (
        OnlyResearchAdmissionResolutionEvidence.from_resolution(
            OnlyResearchSpecificationResolver(registry()).resolve(specification())
        ).fingerprint
    )
    execution.failure = OnlyHistoricalGenerationWorkerUnavailable()
    assert service.submit_research_run(KEY, specification(), parent_runtime_work_id=PARENT).run == outcome.run
    assert len(execution.requests) == len(store.runs) == len(admissions.values) == 1


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "unavailable",
        "unsupported",
        "wrong_operation",
        "wrong_generation",
        "wrong_specification",
        "dataset",
    ],
)
def test_failed_resolution_never_calls_parent_or_strands_child_binding(failure: str) -> None:
    execution = _Execution()
    if failure == "unavailable":
        execution.failure = OnlyHistoricalGenerationWorkerUnavailable()
    elif failure == "unsupported":
        execution.failure = OnlyHistoricalGenerationCapabilityUnsupported()
    elif failure == "wrong_operation":
        execution.operation = OnlySearchGenerationOperationV1.RESOLVE_SYMBOLIC_RESEARCH
    elif failure == "wrong_generation":
        execution.generation = "c" * 64
    elif failure == "wrong_specification":
        execution.specification_fingerprint = "d" * 64
    service, trap, bindings, store, admissions, _ = _system(
        execution=None if failure == "missing" else execution,
        dataset=_DatasetStore(fail=failure == "dataset"),
    )
    with pytest.raises(
        (
            OnlyResearchRunAdmissionError,
            OnlyHistoricalGenerationWorkerUnavailable,
            OnlyHistoricalGenerationExecutionMismatch,
            OnlyHistoricalGenerationCapabilityUnsupported,
        )
    ):
        service.submit_research_run(KEY, specification(), parent_runtime_work_id=PARENT)
    assert trap.calls == 0
    assert bindings.work == {PARENT: G}
    assert not store.runs and not store.receipts
    assert KEY in admissions.values


def test_response_loss_retries_exact_intent_run_generation_and_evidence() -> None:
    execution = _Execution()
    execution.failure = OnlyHistoricalGenerationWorkerUnavailable("response lost")
    service, trap, bindings, store, admissions, _ = _system(execution=execution)
    with pytest.raises(OnlyHistoricalGenerationWorkerUnavailable):
        service.submit_research_run(KEY, specification(), parent_runtime_work_id=PARENT)
    execution.failure = None
    outcome = service.submit_research_run(KEY, specification(), parent_runtime_work_id=PARENT)
    assert execution.requests[0].to_dict() == execution.requests[1].to_dict()
    assert outcome.run.run_id == only_derived_research_run_id(KEY)
    assert bindings.work[outcome.run.run_id.value] == G
    assert trap.calls == 0
    assert len(store.runs) == len(store.receipts) == len(admissions.values) == 1


def test_standalone_retains_parent_resolution_and_external_evidence_is_not_an_argument() -> None:
    service, trap, _, store, _, _ = _system(execution=_Execution())
    with pytest.raises(OnlyResearchRunAdmissionError):
        service.submit_research_run(KEY, specification())
    assert trap.calls == 1 and not store.runs
    with pytest.raises(TypeError):
        service.submit_research_run(KEY, specification(), exact_admission_evidence=object())


@pytest.mark.parametrize("drift", [False, True])
def test_derived_authoring_preserves_both_exact_bindings_without_parent_resolver(drift: bool) -> None:
    class Authoring:
        calls = 0

        def resolve(self, provenance, spec):  # type: ignore[no-untyped-def]
            self.calls += 1
            assert provenance == _provenance()
            resolution = OnlyResearchSpecificationResolver(registry()).resolve(spec)
            return replace(resolution, specification_fingerprint="f" * 64) if drift else resolution

    authoring = Authoring()
    service, trap, bindings, store, _, _ = _system(execution=_Execution(), authoring=authoring)
    if drift:
        with pytest.raises(OnlyResearchRunAdmissionError) as error:
            service.submit_research_run(KEY, specification(), _provenance(), parent_runtime_work_id=PARENT)
        assert error.value.code == "RESEARCH_EXECUTION_GENERATION_MISMATCH"
        assert bindings.work == {PARENT: G}
        assert not store.runs
    else:
        run = service.submit_research_run(KEY, specification(), _provenance(), parent_runtime_work_id=PARENT).run
        assert run.authoring_provenance == _provenance()
        assert bindings.work[run.run_id.value] == G
        assert (
            run.admission_resolution_fingerprint
            == OnlyResearchAdmissionResolutionEvidence.from_resolution(
                OnlyResearchSpecificationResolver(registry()).resolve(specification())
            ).fingerprint
        )
    assert trap.calls == 0
    assert authoring.calls == 1


@pytest.mark.parametrize("after_binding", [False, True])
def test_parent_crash_after_evidence_replays_identical_generation_and_run(after_binding: bool) -> None:
    class CrashOnceBindings(_Bindings):
        crash = True

        def bind_derived_work(self, parent, child, **kwargs):  # type: ignore[no-untyped-def]
            if after_binding:
                super().bind_derived_work(parent, child, **kwargs)
            if self.crash:
                self.crash = False
                raise RuntimeError("parent crash after admission evidence")
            super().bind_derived_work(parent, child, **kwargs)

    bindings = CrashOnceBindings()
    execution = _Execution()
    service, trap, _, store, admissions, dataset = _system(execution=execution, bindings=bindings)
    with pytest.raises(RuntimeError, match="parent crash"):
        service.submit_research_run(KEY, specification(), parent_runtime_work_id=PARENT)
    assert not store.runs and not store.receipts
    assert (only_derived_research_run_id(KEY).value in bindings.work) == after_binding
    run = service.submit_research_run(KEY, specification(), parent_runtime_work_id=PARENT).run
    assert run.run_id == only_derived_research_run_id(KEY)
    assert execution.requests[0].to_dict() == execution.requests[1].to_dict()
    assert bindings.work == {PARENT: G, run.run_id.value: G}
    assert len(store.runs) == len(store.receipts) == len(admissions.values) == 1
    assert dataset.loads == 2 and trap.calls == 0
