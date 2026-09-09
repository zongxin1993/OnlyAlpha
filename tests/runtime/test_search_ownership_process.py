from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.application.search_generation_execution import (
    OnlyHistoricalGenerationWorkerUnavailable,
    OnlySearchGenerationOperationV1,
)
from onlyalpha.application.search_product import (
    OnlyAdvanceSearchExperimentV1,
    OnlyGetSearchIterationLedgerV1,
    OnlySearchBoundedOperationV1,
    OnlySearchMethodV1,
    OnlySearchProductCommandServiceV1,
    OnlySearchProductQueryServiceV1,
    OnlySearchProductReceiptCorrupt,
    OnlySearchRuntimeGenerationUnavailable,
    OnlySubmitParameterSearchExperimentV2,
    OnlySubmitSymbolicSearchExperimentV2,
    only_search_experiment_work_id,
)
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.research.command import OnlyResearchCommandService, OnlyResearchRunQueryService
from onlyalpha.research.command.model import only_derived_research_run_id
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.experiment import (
    OnlyJsonSearchProvenanceStore,
    OnlySearchBudgetV1,
    OnlySearchDecisionEngineBindingV1,
    OnlySearchDecisionMode,
    OnlySearchHypothesisV1,
    OnlySearchWorkflowBindingV1,
)
from onlyalpha.research.run.admission import OnlyResearchRunAdmissionService
from onlyalpha.research.run.generation import OnlyResearchHostedRuntimeGenerationResolver
from onlyalpha.research.run.model import OnlyResearchRunState
from onlyalpha.research.search.parameter.context import OnlyParameterSearchContextResolver
from onlyalpha.research.search.parameter.evidence import OnlyParameterResearchEvidenceReader
from onlyalpha.research.search.parameter.execution import OnlyHostedParameterGenerationExecutionV1
from onlyalpha.research.search.parameter.integration import parameter_submission_key
from onlyalpha.research.search.parameter.model import OnlyParameterFactorSearchSpaceV1
from onlyalpha.research.search.parameter.product import OnlyParameterSearchProductAdapterV1
from onlyalpha.research.search.parameter.store import OnlyJsonParameterSearchStore
from onlyalpha.research.search.symbolic.context import OnlySymbolicSearchContextResolver
from onlyalpha.research.search.symbolic.controller import symbolic_submission_key
from onlyalpha.research.search.symbolic.evaluation import OnlySymbolicResearchEvaluationContractV1
from onlyalpha.research.search.symbolic.execution import OnlyHostedSymbolicGenerationExecutionV1
from onlyalpha.research.search.symbolic.product import (
    OnlySymbolicResearchCommandGatewayV1,
    OnlySymbolicSearchProductAdapterV1,
)
from onlyalpha.research.search.symbolic.store import OnlyJsonSymbolicSearchStore
from tests.research.calculation.support import snapshot
from tests.research.command.test_service import _Store
from tests.research.search.parameter.test_adaptive_parameter_search_v1 import _policy
from tests.research.search.symbolic.support import space
from tests.research.search.symbolic.test_research_and_provenance_integration import _scientific_template
from tests.research.search.symbolic.test_search_product_adapter import _ProductAuthority
from tests.research.sweep.support import definition
from tests.runtime.search_ownership_support import NOW, ExactSearchProcesses, build_exact_search_processes


class _ParentCannotExecute:
    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, *args: object, **kwargs: object) -> Any:
        del args, kwargs
        self.calls += 1
        raise AssertionError("PARENT_CANNOT_EXECUTE_HISTORICAL_G1")

    def generation(self, fingerprint: str) -> Any:
        return self.resolve(fingerprint)

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"PARENT_CANNOT_EXECUTE_HISTORICAL_G1:{name}")


class _UnavailableResults:
    def load_verified(self, fingerprint: str) -> Any:
        raise AssertionError(f"Queued Run has no Research result: {fingerprint}")


@pytest.fixture(scope="module")
def exact_processes(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ExactSearchProcesses]:
    processes = build_exact_search_processes(tmp_path_factory.mktemp("historical-search-process"))
    try:
        yield processes
    finally:
        processes.host.close()


def _id(number: int) -> OnlyProductCommandId:
    return OnlyProductCommandId(str(UUID(int=number, version=4)))


def _case(
    root: Path,
    processes: ExactSearchProcesses,
    method: str,
    index: int,
    product_authority: _ProductAuthority | None = None,
    run_store: _Store | None = None,
) -> Any:
    contexts: Any
    adapter: Any
    search_space: Any
    submit: Any
    dataset_root = OnlyUserDataLayout(root).research_dataset_root
    datasets = OnlyParquetResearchDatasetSnapshotStore(dataset_root)
    candidate, partitions = snapshot()
    dataset = datasets.commit(candidate, partitions)
    parent = _ParentCannotExecute()
    authority = product_authority or _ProductAuthority()
    runs = run_store or _Store()
    # One Receipt Authority: the Research store's atomic Run+Receipt commit is
    # visible to Product's receipt reader, never copied into a second truth.
    runs.receipts = authority.receipts
    admission = OnlyResearchRunAdmissionService(
        resolver=cast(Any, parent),
        dataset_store=datasets,
        run_store=cast(Any, runs),
        now_utc=lambda: NOW,
    )
    generation_resolver = OnlyResearchHostedRuntimeGenerationResolver(
        execution=processes.host,
        dataset_store_root=str(dataset_root),
    )
    commands = OnlyResearchCommandService(
        admission=admission,
        store=runs,
        now_utc=lambda: NOW,
        runtime_generations=processes.authority,
        command_admissions=authority,
        runtime_generation_resolver=generation_resolver,
    )
    symbolic = OnlyJsonSymbolicSearchStore(root / "search")
    evaluation = OnlySymbolicResearchEvaluationContractV1.from_specification(
        _scientific_template(dataset.snapshot_fingerprint), "feature"
    )
    common: dict[str, Any] = dict(
        command_id=_id(index * 100 + 1),
        hypothesis=OnlySearchHypothesisV1(f"exact process {method} {index}"),
        evaluation_contract=evaluation,
        search_budget=OnlySearchBudgetV1(3, 3, 1),
        workflow_binding=OnlySearchWorkflowBindingV1(f"{method}.factor.search", "1"),
        decision_engine_binding=OnlySearchDecisionEngineBindingV1(OnlySearchDecisionMode.DETERMINISTIC),
        catalog_generation_fingerprint=(
            processes.variant_catalog if index == 2 else processes.catalog.generation_fingerprint
        ),
        dataset_snapshot_fingerprint=dataset.snapshot_fingerprint,
        runtime_generation_fingerprint=(
            processes.variant_generation if index == 2 else processes.generations[index % 2]
        ),
    )
    if method == "symbolic":
        _, search_space = space(max_nodes=1)
        if index == 2:
            components = tuple(
                replace(item, type_reference=replace(item.type_reference, semantic_version="2"))
                if item.type_reference.type_id == "example.factor.momentum"
                else item
                for item in search_space.component_instances
            )
            bridge = next(item for item in components if item.type_reference.type_id == "example.factor.momentum")
            search_space = replace(
                search_space,
                catalog_generation_fingerprint=processes.variant_catalog,
                component_instances=components,
                candidate_output_contract=replace(
                    search_space.candidate_output_contract,
                    component_instance_fingerprint=bridge.component_instance_fingerprint,
                ),
            )
        contexts = OnlySymbolicSearchContextResolver(
            symbolic_store=symbolic,
            catalogs=cast(Any, parent),
            datasets=datasets,
            research_calculation_registry=cast(Any, parent),
        )
        provenance = OnlyJsonSearchProvenanceStore(
            root / "search",
            catalogs=cast(Any, parent),
            datasets=datasets,
            search_contexts=contexts,
        )
        adapter = OnlySymbolicSearchProductAdapterV1(
            symbolic_store=symbolic,
            provenance=provenance,
            contexts=contexts,
            resolver=cast(Any, parent),
            research_commands=OnlySymbolicResearchCommandGatewayV1(cast(Any, commands), _UnavailableResults()),
            generation_execution=OnlyHostedSymbolicGenerationExecutionV1(processes.host, dataset_root),
            product_receipts=authority,
            research_runs=OnlyResearchRunQueryService(runs),
        )
        submit = OnlySubmitSymbolicSearchExperimentV2(
            search_space=search_space,
            algorithm_manifest=processes.symbolic_algorithm,
            **common,
        )
    else:
        parameter = OnlyJsonParameterSearchStore(root / "search")
        search_space = OnlyParameterFactorSearchSpaceV1.from_sweep(
            catalog_generation_fingerprint=processes.catalog.generation_fingerprint,
            sweep_definition=definition(dataset.snapshot_fingerprint, candidates=(1, 3, 5)),
            candidate_template_node_id="momentum",
            candidate_output_name="factor_value",
            calculation_registry=processes.catalog.calculation_registry(),
        )
        if index == 2:
            template = search_space.sweep_definition.graph_template
            template = replace(
                template,
                nodes=tuple(
                    replace(node, type_reference=replace(node.type_reference, semantic_version="2"))
                    if node.type_reference.type_id == "example.factor.momentum"
                    else node
                    for node in template.nodes
                ),
            )
            search_space = replace(
                search_space,
                catalog_generation_fingerprint=processes.variant_catalog,
                sweep_definition=replace(search_space.sweep_definition, graph_template=template),
            )
        contexts = OnlyParameterSearchContextResolver(
            parameter_store=parameter,
            evaluations=symbolic,
            catalogs=cast(Any, parent),
            datasets=datasets,
            research_calculation_registry=cast(Any, parent),
        )
        provenance = OnlyJsonSearchProvenanceStore(
            root / "search",
            catalogs=cast(Any, parent),
            datasets=datasets,
            search_contexts=contexts,
        )
        evidence = OnlyParameterResearchEvidenceReader(
            iteration_results=provenance,
            iteration_plans=provenance,
            research_results=_UnavailableResults(),
            statistics_results=cast(Any, _UnavailableResults()),
        )
        adapter = OnlyParameterSearchProductAdapterV1(
            parameter_store=parameter,
            evaluation_store=symbolic,
            provenance=provenance,
            contexts=contexts,
            calculation_registry=cast(Any, parent),
            evidence_reader=evidence,
            resolver=cast(Any, parent),
            research_commands=cast(Any, commands),
            generation_execution=OnlyHostedParameterGenerationExecutionV1(processes.host, dataset_root),
            product_receipts=authority,
            research_runs=OnlyResearchRunQueryService(runs),
        )
        submit = OnlySubmitParameterSearchExperimentV2(
            search_space=search_space,
            search_policy=_policy(batch_size=1),
            algorithm_manifest=processes.parameter_algorithm,
            **common,
        )
    service = OnlySearchProductCommandServiceV1(
        command_admissions=authority,
        command_receipts=authority,
        runtime_generations=processes.authority,
        adapters=(adapter,),
        now_utc=lambda: NOW,
    )
    return service, OnlySearchProductQueryServiceV1((adapter,)), submit, runs, parent, generation_resolver


@pytest.mark.parametrize("method", ("symbolic", "parameter"))
@pytest.mark.parametrize("index", (0, 1, 2))
@pytest.mark.parametrize("lost_response", (None, "search", "admission"))
def test_real_product_search_and_research_admission_without_parent_execution(
    tmp_path: Path,
    exact_processes: ExactSearchProcesses,
    method: str,
    index: int,
    lost_response: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _exercise(tmp_path, exact_processes, method, index, lost_response, monkeypatch)


def _exercise(
    tmp_path: Path,
    exact_processes: ExactSearchProcesses,
    method: str,
    index: int,
    lost_response: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    service, query, submit, runs, parent, resolver = _case(tmp_path, exact_processes, method, index)
    current = exact_processes.authority.projection().active_for_new_work
    if current != submit.runtime_generation_fingerprint:
        exact_processes.authority.activate_for_new_work(
            expected_current=current,
            target=submit.runtime_generation_fingerprint,
            actor="test-operator",
            occurred_at=NOW,
        )
    created = service.submit(submit)
    experiment = created.experiment.experiment_fingerprint
    generation = submit.runtime_generation_fingerprint
    assert (
        exact_processes.authority.require_work_binding(
            only_search_experiment_work_id(experiment)
        ).runtime_generation_fingerprint
        == generation
    )
    # Activation changes before any executable Search/Research operation.
    exact_processes.authority.activate_for_new_work(
        expected_current=generation,
        target=exact_processes.generations[1 - index % 2],
        actor="test-operator",
        occurred_at=NOW,
    )
    initial = query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment))
    symbolic = method == "symbolic"
    advance = OnlyAdvanceSearchExperimentV1(
        _id(index * 100 + 2),
        OnlySearchMethodV1.SYMBOLIC if symbolic else OnlySearchMethodV1.PARAMETER,
        (
            OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE
            if symbolic
            else OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION
        ),
        initial.expected_state,
    )
    responses: list[object] = []
    actual_execute = exact_processes.host.execute

    def lose_after_real_response(request: Any) -> Any:
        response = actual_execute(request)
        targeted = (
            request.operation_kind is OnlySearchGenerationOperationV1.RESOLVE_RESEARCH_ADMISSION
            if lost_response == "admission"
            else request.operation_kind
            in {
                OnlySearchGenerationOperationV1.DERIVE_SYMBOLIC_ENUMERATION,
                OnlySearchGenerationOperationV1.DERIVE_PARAMETER_DECISION,
            }
        )
        if targeted:
            responses.append(response.to_dict())
            if len(responses) == 1:
                raise OnlyHistoricalGenerationWorkerUnavailable("injected response loss after exact worker computation")
        return response

    if lost_response is not None:
        monkeypatch.setattr(exact_processes.host, "execute", lose_after_real_response)
    if lost_response == "search":
        with pytest.raises(OnlySearchRuntimeGenerationUnavailable):
            service.advance(advance)
        assert query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment)).plans == ()
        assert runs.runs == {}
    advanced = service.advance(advance)
    assert len(advanced.ledger.plans) == 1
    plan = advanced.ledger.plans[0]
    reconcile = OnlyAdvanceSearchExperimentV1(
        _id(index * 100 + 3),
        advance.method,
        (
            OnlySearchBoundedOperationV1.RECONCILE_ONE_SYMBOLIC_OCCURRENCE
            if symbolic
            else OnlySearchBoundedOperationV1.RECONCILE_OPEN_PARAMETER_BATCH
        ),
        (
            replace(advanced.ledger.expected_state, target_plan_fingerprint=plan.iteration_plan_fingerprint)
            if symbolic
            else advanced.ledger.expected_state
        ),
    )
    if lost_response == "admission":
        with pytest.raises(OnlySearchRuntimeGenerationUnavailable):
            service.advance(reconcile)
        assert runs.runs == {}
    service.advance(reconcile)
    assert len(runs.runs) == 1
    key = symbolic_submission_key(plan) if symbolic else parameter_submission_key(plan)
    run = runs.runs[only_derived_research_run_id(key)]
    assert run.state is OnlyResearchRunState.QUEUED
    assert exact_processes.authority.require_work_binding(run.run_id.value).runtime_generation_fingerprint == generation
    assert parent.calls == 0
    if lost_response is not None:
        assert len(responses) >= 2
        assert responses[0] == responses[1]
        monkeypatch.setattr(exact_processes.host, "execute", actual_execute)
    evidence = resolver.resolve(generation, run.specification)
    assert evidence.fingerprint == run.admission_resolution_fingerprint
    worker = exact_processes.host.acquire(generation)
    worker.process.kill()
    worker.process.wait(timeout=5)
    restarted_evidence = resolver.resolve(generation, run.specification)
    assert restarted_evidence.to_dict() == evidence.to_dict()
    assert exact_processes.host.acquire(generation).process.pid != worker.process.pid
    assert service.advance(reconcile).replayed
    assert len(runs.runs) == 1
    assert exact_processes.host.acquire(generation).process.pid is not None
    execution_result = None
    if lost_response is None:
        execution_result = _execute_research(tmp_path, exact_processes, generation, run)
    return run, execution_result


@pytest.mark.parametrize("method", ("symbolic", "parameter"))
def test_distinct_factor_semantics_remain_generation_owned_through_research_execution(
    tmp_path: Path,
    exact_processes: ExactSearchProcesses,
    method: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert exact_processes.variant_catalog != exact_processes.catalog.generation_fingerprint
    first, first_result = _exercise(tmp_path / "a", exact_processes, method, 0, None, monkeypatch)
    second, second_result = _exercise(tmp_path / "b", exact_processes, method, 2, None, monkeypatch)
    assert first.specification.specification_fingerprint != second.specification.specification_fingerprint
    assert first.admission_resolution_fingerprint != second.admission_resolution_fingerprint
    assert first_result != second_result


def _execute_research(root: Path, processes: ExactSearchProcesses, generation: str, run: Any) -> str:
    environment = processes.host._cache_root / generation
    configuration = root / "research-execution-input.json"
    values = {
        "root": str(root),
        "authority_root": str(processes.authority.root),
        "generation": generation,
        "run_id": run.run_id.value,
        "specification": run.specification.to_dict(),
        "admission_fingerprint": run.admission_resolution_fingerprint,
    }
    completed_result = ""
    for drift in ("none", "admission_corruption", "resolver_drift"):
        values["admission_fingerprint"] = (
            "0" * 64 if drift == "admission_corruption" else run.admission_resolution_fingerprint
        )
        values["resolver_drift"] = drift == "resolver_drift"
        configuration.write_text(json.dumps(values))
        completed = subprocess.run(
            [
                str(environment / "bin" / "python"),
                "-I",
                str(Path(__file__).with_name("search_research_execution.py")),
                str(configuration),
            ],
            cwd=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        result = json.loads(completed.stdout.splitlines()[-1])
        if drift != "none":
            assert result["kind"] == "FAILED"
            assert result["failure"] == "EXECUTION_SEMANTIC_DRIFT"
            assert result["result"] is None
            assert result["execution_calls"] == 0
            if drift == "resolver_drift":
                assert values["admission_fingerprint"] == run.admission_resolution_fingerprint
                assert result["resolution_fingerprint"] != run.admission_resolution_fingerprint
        else:
            assert result["kind"] == "COMPLETED", result
            assert result["result"] is not None
            assert result["execution_calls"] == 1
            completed_result = result["result"]
    assert completed_result
    return completed_result


@pytest.mark.parametrize("method", ("symbolic", "parameter"))
def test_real_worker_dies_after_request_flush_before_response_delivery(
    tmp_path: Path,
    exact_processes: ExactSearchProcesses,
    method: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, query, submit, runs, parent, _resolver = _case(tmp_path, exact_processes, method, 0)
    generation = submit.runtime_generation_fingerprint
    current = exact_processes.authority.projection().active_for_new_work
    if current != generation:
        exact_processes.authority.activate_for_new_work(
            expected_current=current, target=generation, actor="test-operator", occurred_at=NOW
        )
    created = service.submit(submit)
    experiment = created.experiment.experiment_fingerprint
    state = query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment)).expected_state
    worker = exact_processes.host.acquire(generation)
    command = OnlyAdvanceSearchExperimentV1(
        _id(42),
        OnlySearchMethodV1.SYMBOLIC if method == "symbolic" else OnlySearchMethodV1.PARAMETER,
        OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE
        if method == "symbolic"
        else OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION,
        state,
    )
    original_read = exact_processes.host._read_line
    reads = []

    def kill_before_response(process: Any) -> Any:
        assert process is worker.process
        reads.append(process.pid)
        process.kill()
        process.wait(timeout=5)
        raise OSError("fault after request flush and before response delivery")

    monkeypatch.setattr(exact_processes.host, "_read_line", kill_before_response)
    with pytest.raises(OnlySearchRuntimeGenerationUnavailable):
        service.advance(command)
    monkeypatch.setattr(exact_processes.host, "_read_line", original_read)
    assert reads == [worker.process.pid]
    assert query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment)).plans == ()
    assert runs.runs == {}
    accepted = service.advance(command)
    assert len(accepted.ledger.plans) == 1
    assert service.advance(command).replayed
    assert parent.calls == 0
    restarted = exact_processes.host.acquire(generation)
    assert restarted.process.pid != worker.process.pid
    assert restarted.handshake == worker.handshake


@pytest.mark.parametrize("method", ("symbolic", "parameter"))
@pytest.mark.parametrize("crash_point", ("before_search_commit", "before_receipt"))
def test_fresh_parent_composition_recovers_real_worker_effect_without_advancing_again(
    tmp_path: Path,
    exact_processes: ExactSearchProcesses,
    method: str,
    crash_point: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority, runs = _ProductAuthority(), _Store()
    service, query, submit, _, parent, _ = _case(tmp_path, exact_processes, method, 0, authority, runs)
    generation = submit.runtime_generation_fingerprint
    current = exact_processes.authority.projection().active_for_new_work
    if current != generation:
        exact_processes.authority.activate_for_new_work(
            expected_current=current, target=generation, actor="test-operator", occurred_at=NOW
        )
    created = service.submit(submit)
    experiment = created.experiment.experiment_fingerprint
    initial = query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment)).expected_state
    symbolic = method == "symbolic"
    command = OnlyAdvanceSearchExperimentV1(
        _id(43),
        OnlySearchMethodV1.SYMBOLIC if symbolic else OnlySearchMethodV1.PARAMETER,
        OnlySearchBoundedOperationV1.ADVANCE_ONE_SYMBOLIC_OCCURRENCE
        if symbolic
        else OnlySearchBoundedOperationV1.ADVANCE_ONE_PARAMETER_DECISION,
        initial,
    )
    responses = []
    actual_execute = exact_processes.host.execute

    def record(request: Any) -> Any:
        response = actual_execute(request)
        responses.append(response.to_dict())
        return response

    monkeypatch.setattr(exact_processes.host, "execute", record)
    if crash_point == "before_search_commit":
        store_class = OnlyJsonSymbolicSearchStore if symbolic else OnlyJsonParameterSearchStore
        method_name = "commit_enumeration_result" if symbolic else "commit_feedback_decision"
        actual_commit = getattr(store_class, method_name)

        def crash(*args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            assert responses
            raise RuntimeError("parent crash after worker evidence before Search commit")

        monkeypatch.setattr(store_class, method_name, crash)
    else:
        authority.fail_next_receipt = True
    expected_error = RuntimeError if crash_point == "before_search_commit" else OnlySearchProductReceiptCorrupt
    with pytest.raises(expected_error):
        service.advance(command)
    assert responses
    responses_before_recovery = len(responses)
    assert all(response == responses[0] for response in responses)
    assert authority.load_admission(command.command_id) is not None
    assert authority.load_verified_receipt(command.command_id) is None
    if crash_point == "before_search_commit":
        monkeypatch.setattr(store_class, method_name, actual_commit)
    before = query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment))
    assert len(responses) == responses_before_recovery
    assert len(before.plans) == (0 if crash_point == "before_search_commit" else 1)
    old_service = service
    service, query, _, _, fresh_parent, _ = _case(tmp_path, exact_processes, method, 0, authority, runs)
    assert service is not old_service
    recovered = service.advance(command)
    assert len(recovered.ledger.plans) == 1
    if crash_point == "before_search_commit":
        assert len(responses) >= 2
        assert responses[0] == responses[1]
    else:
        # Receipt repair creates the missing Receipt; only a later request is
        # classified as Receipt replay. It must not create a new Search effect.
        assert not recovered.replayed
        assert recovered.ledger.plans == before.plans
        assert len(responses) == responses_before_recovery
    assert service.advance(command).replayed
    if crash_point == "before_receipt":
        assert len(responses) == responses_before_recovery
    assert len(query.get_ledger(OnlyGetSearchIterationLedgerV1(experiment)).plans) == 1
    assert runs.runs == {}
    assert parent.calls == fresh_parent.calls == 0
