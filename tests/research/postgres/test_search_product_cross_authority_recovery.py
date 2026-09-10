from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest

from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
)
from onlyalpha.application.search_product import (
    OnlySearchProductCommandServiceV1,
    OnlySearchProductSemanticFactCorrupt,
    OnlySubmitParameterSearchExperimentV2,
    only_load_search_research_run_exact,
    only_search_experiment_work_id,
)
from onlyalpha.persistence.postgres import (
    OnlyPostgresProductCommandAuthority,
    OnlyPostgresResearchRunStore,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.research.command import (
    OnlyDerivedResearchSubmitCommandV2,
    OnlyResearchCommandService,
    OnlyResearchRunQueryService,
    OnlyResearchSubmissionConflictError,
    only_derived_research_run_id,
)
from onlyalpha.research.experiment import (
    OnlySearchBudgetV1,
    OnlySearchDecisionEngineBindingV1,
    OnlySearchDecisionMode,
    OnlySearchHypothesisV1,
    OnlySearchWorkflowBindingV1,
)
from onlyalpha.research.run import (
    OnlyResearchRunAdmissionService,
    OnlyResearchRunId,
    OnlyResearchRunNotFoundError,
)
from onlyalpha.research.search.parameter import (
    OnlyParameterFactorSearchSpaceV1,
    OnlyParameterObjectiveDirection,
    OnlyParameterResearchEvidenceReader,
    OnlyParameterSearchContextResolver,
    OnlyParameterSearchPolicyV1,
    OnlyParameterSearchProductAdapterV1,
    OnlyParameterTieBreakerV1,
    decide_parameter_search_v1,
    materialize_parameter_proposals,
    only_deterministic_coarse_to_fine_implementation,
)
from onlyalpha.research.search.symbolic import (
    OnlySymbolicResearchEvaluationContractV1,
    OnlySymbolicSearchProductAdapterV1,
)
from onlyalpha.research.specification.model import (
    OnlyResearchScientificEvidenceSpec,
    OnlyResearchSeriesSelector,
    OnlyResearchSignalEvidenceSpec,
    OnlyResearchSpecification,
)
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from tests.research.calculation.support import snapshot
from tests.research.search.parameter.test_search_product_adapter import _ExactTestGenerationExecution
from tests.research.search.symbolic.support import catalog
from tests.research.search.symbolic.test_search_product_adapter import _case
from tests.research.specification.support import registry as research_registry
from tests.research.specification.support import specification
from tests.research.sweep.support import definition
from tests.runtime_generation_support import OnlyTestRuntimeGenerationAuthority

from .test_parameter_search_recovery import (
    _PRIMARY,
    _TIE,
    _commands,
    _ExactRuntimeAdmissionResolver,
    _runtime_generations,
    _stores,
    _topology,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.external,
    pytest.mark.requires_network,
    pytest.mark.postgres,
]

_NOW = datetime(2026, 9, 8, tzinfo=UTC)


def test_derived_binding_crash_before_real_postgres_commit_recovers_exact_run(
    postgres_dsn: str,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    _layout, datasets, _calculations, _statistics, _summaries, _reader, _results = _stores(tmp_path)
    candidate, partitions = snapshot()
    dataset = datasets.commit(candidate, partitions)
    exact_specification = specification(dataset.snapshot_fingerprint)
    durable_store = OnlyPostgresResearchRunStore(postgres_dsn)
    product_authority = OnlyPostgresProductCommandAuthority(postgres_dsn)
    runtime_generations = _runtime_generations(tmp_path)
    generation = runtime_generations.projection().active_for_new_work
    assert generation is not None
    parent = only_search_experiment_work_id("d" * 64)
    runtime_generations.bind_work_exact(parent, generation, actor="search", occurred_at=_NOW)

    class _CrashBeforePostgresCommit:
        def find_product_command_receipt(self, command_id):  # type: ignore[no-untyped-def]
            return durable_store.find_product_command_receipt(command_id)

        def create_queued_with_receipt(self, run, receipt):  # type: ignore[no-untyped-def]
            del run, receipt
            raise RuntimeError("injected crash before Research PostgreSQL commit")

    admission = OnlyResearchRunAdmissionService(
        resolver=OnlyResearchSpecificationResolver(research_registry()),
        dataset_store=datasets,
        run_store=durable_store,
        now_utc=lambda: _NOW,
    )
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-0000000000e1")
    crashing = OnlyResearchCommandService(
        admission=admission,
        store=_CrashBeforePostgresCommit(),  # type: ignore[arg-type]
        now_utc=lambda: _NOW,
        runtime_generations=runtime_generations,
        command_admissions=product_authority,
        runtime_generation_resolver=_ExactRuntimeAdmissionResolver(runtime_generations),
    )
    with pytest.raises(RuntimeError, match="injected crash"):
        crashing.submit_research_run(
            command_id,
            exact_specification,
            parent_runtime_work_id=parent,
        )

    expected_run_id = only_derived_research_run_id(command_id)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_run").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM product_command_receipt").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM product_command_admission").fetchone() == (1,)
    assert set(runtime_generations.projection().work_bindings) == {parent, expected_run_id.value}

    restarted = OnlyResearchCommandService(
        admission=admission,
        store=durable_store,
        now_utc=lambda: _NOW,
        runtime_generations=runtime_generations,
        command_admissions=OnlyPostgresProductCommandAuthority(postgres_dsn),
        runtime_generation_resolver=_ExactRuntimeAdmissionResolver(runtime_generations),
    )
    recovered = restarted.submit_research_run(
        command_id,
        exact_specification,
        parent_runtime_work_id=parent,
    )
    assert recovered.run.run_id == expected_run_id
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_run").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM product_command_receipt").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM product_command_admission").fetchone() == (1,)
    assert set(runtime_generations.projection().work_bindings) == {parent, expected_run_id.value}


def test_real_postgres_wrong_derived_receipt_identity_fails_closed_without_repair(
    postgres_dsn: str,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    _layout, datasets, _calculations, _statistics, _summaries, _reader, _results = _stores(tmp_path)
    candidate, partitions = snapshot()
    dataset = datasets.commit(candidate, partitions)
    exact_specification = specification(dataset.snapshot_fingerprint)
    durable_store = OnlyPostgresResearchRunStore(postgres_dsn)
    product_authority = OnlyPostgresProductCommandAuthority(postgres_dsn)
    runtime_generations = _runtime_generations(tmp_path)
    generation = runtime_generations.projection().active_for_new_work
    assert generation is not None
    parent = only_search_experiment_work_id("e" * 64)
    runtime_generations.bind_work_exact(parent, generation, actor="search", occurred_at=_NOW)
    admission = OnlyResearchRunAdmissionService(
        resolver=OnlyResearchSpecificationResolver(research_registry()),
        dataset_store=datasets,
        run_store=durable_store,
        now_utc=lambda: _NOW,
    )
    wrong_run_id = OnlyResearchRunId("00000000-0000-4000-8000-0000000000e2")
    wrong_run = admission.prepare(exact_specification, exact_run_id=wrong_run_id)
    durable_store.create_queued(wrong_run)
    runtime_generations.bind_derived_work(
        parent,
        wrong_run_id.value,
        actor="corrupt-fixture",
        occurred_at=_NOW,
    )
    command_id = OnlyProductCommandId("00000000-0000-4000-8000-0000000000e3")
    command = OnlyDerivedResearchSubmitCommandV2(command_id, exact_specification, parent)
    product_authority.admit_exact(
        OnlyProductCommandAdmissionV1(
            command_id,
            OnlyProductCommandKind.CREATE_RESEARCH_RUN,
            command.command_fingerprint,
        )
    )
    wrong_receipt = OnlyProductCommandReceipt(
        command_id,
        OnlyProductCommandKind.CREATE_RESEARCH_RUN,
        command.command_fingerprint,
        OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.RESEARCH_RUN, wrong_run_id.value),
        _NOW,
    )
    product_authority.put_verified_receipt(wrong_receipt)
    expected_run_id = only_derived_research_run_id(command_id)
    bindings_before = dict(runtime_generations.projection().work_bindings)

    service = OnlyResearchCommandService(
        admission=admission,
        store=durable_store,
        now_utc=lambda: _NOW,
        runtime_generations=runtime_generations,
        command_admissions=product_authority,
    )
    with pytest.raises(OnlyResearchSubmissionConflictError):
        service.submit_research_run(
            command_id,
            exact_specification,
            parent_runtime_work_id=parent,
        )

    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT run_id::text FROM research_run ORDER BY run_id").fetchall() == [
            (wrong_run_id.value,)
        ]
        assert connection.execute("SELECT count(*) FROM product_command_admission").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM product_command_receipt").fetchone() == (1,)
    assert product_authority.load_verified_receipt(command_id) == wrong_receipt
    assert dict(runtime_generations.projection().work_bindings) == bindings_before
    with pytest.raises(OnlyResearchRunNotFoundError):
        durable_store.load(expected_run_id)


def test_symbolic_fresh_service_repairs_real_postgres_receipt_from_json_effect(
    postgres_dsn: str,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    authority = OnlyPostgresProductCommandAuthority(postgres_dsn)
    service, query, _memory_authority, commands, submit = _case(tmp_path)
    base = query._adapters[submit.method]  # type: ignore[attr-defined]
    runs = OnlyResearchRunQueryService(OnlyPostgresResearchRunStore(postgres_dsn))
    adapter = OnlySymbolicSearchProductAdapterV1(
        symbolic_store=base._store,  # type: ignore[attr-defined]
        provenance=base._provenance,  # type: ignore[attr-defined]
        contexts=base._contexts,  # type: ignore[attr-defined]
        resolver=base._resolver,  # type: ignore[attr-defined]
        research_commands=commands,
        generation_execution=base._controller._generation_execution,  # type: ignore[attr-defined]
        product_receipts=authority,
        research_runs=runs,
    )
    expected = adapter.derive_submit_experiment(submit)
    admission = OnlyProductCommandAdmissionV1(
        submit.command_id,
        OnlyProductCommandKind.CREATE_SYMBOLIC_SEARCH_EXPERIMENT,
        submit.command_fingerprint,
    )
    authority.admit_exact(admission)
    committed = adapter.commit_submit(submit, expected)
    assert authority.load_verified_receipt(submit.command_id) is None

    del adapter, base, query
    _service2, query2, _memory_authority2, commands2, _submit2 = _case(tmp_path)
    base2 = query2._adapters[submit.method]  # type: ignore[attr-defined]
    restarted_adapter = OnlySymbolicSearchProductAdapterV1(
        symbolic_store=base2._store,  # type: ignore[attr-defined]
        provenance=base2._provenance,  # type: ignore[attr-defined]
        contexts=base2._contexts,  # type: ignore[attr-defined]
        resolver=base2._resolver,  # type: ignore[attr-defined]
        research_commands=commands2,
        generation_execution=base2._controller._generation_execution,  # type: ignore[attr-defined]
        product_receipts=OnlyPostgresProductCommandAuthority(postgres_dsn),
        research_runs=OnlyResearchRunQueryService(OnlyPostgresResearchRunStore(postgres_dsn)),
    )
    restarted = OnlySearchProductCommandServiceV1(
        command_admissions=OnlyPostgresProductCommandAuthority(postgres_dsn),
        command_receipts=OnlyPostgresProductCommandAuthority(postgres_dsn),
        runtime_generations=service._runtime_generations,  # type: ignore[attr-defined]
        adapters=(restarted_adapter,),
        now_utc=lambda: _NOW,
    )
    repaired = restarted.submit(submit)
    assert repaired.experiment == committed
    assert repaired.ledger.plans == ()
    assert authority.load_verified_receipt(submit.command_id) == repaired.receipt


class _PostgresParameterExecution(_ExactTestGenerationExecution):
    """Explicit deterministic semantic fake; this test certifies PG recovery only."""

    def __init__(self) -> None:
        pass

    def derive_decision(self, generation, context, evidence, prior):  # type: ignore[no-untyped-def]
        assert generation == "f" * 64
        exact_catalog = catalog()
        calculation_registry = research_registry()
        OnlyParameterSearchContextResolver._verify_bindings(
            context.experiment,
            context.search_space,
            context.policy,
            context.historical_algorithm_manifest,
            context.evaluation_contract,
            exact_catalog,
            context.verified_dataset,
        )
        OnlyParameterSearchContextResolver._verify_candidate_authority(
            context.search_space,
            exact_catalog,
            calculation_registry,
        )
        evaluation = context.evaluation_contract
        OnlyResearchSpecificationResolver(calculation_registry).verify_deferred_calculation_template(
            dataset_snapshot_fingerprint=evaluation.dataset_snapshot_fingerprint,
            fixed_calculations=evaluation.fixed_calculations,
            statistics=evaluation.statistics,
            evidence=evaluation.evidence,
            deferred_calculation_id=evaluation.candidate_calculation_id,
        )
        proposals = materialize_parameter_proposals(context.search_space, calculation_registry)
        decision = decide_parameter_search_v1(
            experiment_fingerprint=context.experiment.experiment_fingerprint,
            proposals=proposals,
            policy=context.policy,
            algorithm_implementation_fingerprint=context.historical_algorithm_manifest.implementation_fingerprint,
            budget=context.experiment.search_budget,
            evidence=evidence,
            prior_decisions=prior,
        )
        return decision, proposals


def _parameter_adapter(root, dsn, authority):  # type: ignore[no-untyped-def]
    _layout, _datasets, statistics, research, parameters, evaluations, contexts, provenance = _topology(root)
    return OnlyParameterSearchProductAdapterV1(
        parameter_store=parameters,
        evaluation_store=evaluations,
        provenance=provenance,
        contexts=contexts,
        calculation_registry=research_registry(),
        evidence_reader=OnlyParameterResearchEvidenceReader(
            iteration_results=provenance,
            iteration_plans=provenance,
            research_results=research,
            statistics_results=statistics,
        ),
        resolver=OnlyResearchSpecificationResolver(research_registry()),
        research_commands=_commands(root, dsn),
        generation_execution=_PostgresParameterExecution(),
        product_receipts=authority,
        research_runs=OnlyResearchRunQueryService(OnlyPostgresResearchRunStore(dsn)),
    )


def test_parameter_fresh_service_repairs_real_postgres_receipt_from_json_effect(
    postgres_dsn: str,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    authority = OnlyPostgresProductCommandAuthority(postgres_dsn)
    _layout, datasets, _statistics, _research, _parameters, _evaluations, _contexts, _provenance = _topology(tmp_path)
    candidate, partitions = snapshot()
    dataset = datasets.commit(candidate, partitions)
    catalog_generation = catalog()
    search_space = OnlyParameterFactorSearchSpaceV1.from_sweep(
        catalog_generation_fingerprint=catalog_generation.generation_fingerprint,
        sweep_definition=definition(dataset.snapshot_fingerprint, candidates=(3, 4)),
        candidate_template_node_id="momentum",
        candidate_output_name="factor_value",
        calculation_registry=research_registry(),
    )
    policy = OnlyParameterSearchPolicyV1(
        primary_metric_selector=_PRIMARY,
        objective_direction=OnlyParameterObjectiveDirection.MAXIMIZE,
        required_constraints=(),
        ordered_tie_breakers=(OnlyParameterTieBreakerV1(_TIE, OnlyParameterObjectiveDirection.MAXIMIZE),),
        minimum_improvement=Decimal("0.010000000000"),
        max_no_improvement_decisions=2,
        batch_size=2,
        coarse_stride=1,
    )
    base = specification(dataset.snapshot_fingerprint)
    scientific = OnlyResearchSpecification(
        base.dataset_snapshot_fingerprint,
        base.calculations,
        base.statistics,
        OnlyResearchScientificEvidenceSpec(
            "feature",
            (OnlyResearchSeriesSelector("feature", "momentum", "factor_value"),),
            OnlyResearchSignalEvidenceSpec(),
        ),
        2,
    )
    evaluation = OnlySymbolicResearchEvaluationContractV1.from_specification(scientific, "feature")
    runtime_generations = OnlyTestRuntimeGenerationAuthority(
        generation_fingerprint="f" * 64,
        catalog_generation_fingerprint=catalog_generation.generation_fingerprint,
    )
    submit = OnlySubmitParameterSearchExperimentV2(
        OnlyProductCommandId(str(uuid4())),
        OnlySearchHypothesisV1("real durable Parameter Product recovery"),
        search_space,
        evaluation,
        policy,
        OnlySearchBudgetV1(2, 2, 1),
        only_deterministic_coarse_to_fine_implementation(),
        OnlySearchWorkflowBindingV1("parameter.factor.search", "1"),
        OnlySearchDecisionEngineBindingV1(OnlySearchDecisionMode.DETERMINISTIC),
        catalog_generation.generation_fingerprint,
        dataset.snapshot_fingerprint,
        runtime_generation_fingerprint=runtime_generations.generation_fingerprint,
    )
    adapter = _parameter_adapter(tmp_path, postgres_dsn, authority)
    expected = adapter.derive_submit_experiment(submit)
    authority.admit_exact(
        OnlyProductCommandAdmissionV1(
            submit.command_id,
            OnlyProductCommandKind.CREATE_PARAMETER_SEARCH_EXPERIMENT,
            submit.command_fingerprint,
        )
    )
    committed = adapter.commit_submit(submit, expected)
    assert authority.load_verified_receipt(submit.command_id) is None

    del adapter
    restarted_authority = OnlyPostgresProductCommandAuthority(postgres_dsn)
    restarted_adapter = _parameter_adapter(tmp_path, postgres_dsn, restarted_authority)
    restarted = OnlySearchProductCommandServiceV1(
        command_admissions=restarted_authority,
        command_receipts=restarted_authority,
        runtime_generations=runtime_generations,
        adapters=(restarted_adapter,),
        now_utc=lambda: _NOW,
    )
    repaired = restarted.submit(submit)
    assert repaired.experiment == committed
    assert repaired.ledger.plans == ()
    assert authority.load_verified_receipt(submit.command_id) == repaired.receipt


def test_real_research_receipt_exactly_dereferences_run_and_dangling_fails_closed(
    postgres_dsn: str,
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    _layout, datasets, _calculations, _statistics, _summaries, _reader, _results = _stores(tmp_path)
    candidate, partitions = snapshot()
    dataset = datasets.commit(candidate, partitions)
    exact_specification = specification(dataset.snapshot_fingerprint)
    commands = _commands(tmp_path, postgres_dsn).commands
    first_id = OnlyProductCommandId(str(uuid4()))
    first = commands.submit_research_run(first_id, exact_specification).run
    receipts = OnlyPostgresProductCommandAuthority(postgres_dsn)
    run_reader = OnlyResearchRunQueryService(OnlyPostgresResearchRunStore(postgres_dsn))

    assert (
        only_load_search_research_run_exact(
            command_id=first_id,
            receipts=receipts,
            runs=run_reader,
            expected_specification=exact_specification,
        )
        == first
    )

    second_id = OnlyProductCommandId(str(uuid4()))
    second = commands.submit_research_run(second_id, exact_specification).run

    class _MismatchedReader:
        def get_run(self, run_id):  # type: ignore[no-untyped-def]
            del run_id
            return run_reader.get_run(second.run_id)

    with pytest.raises(OnlySearchProductSemanticFactCorrupt):
        only_load_search_research_run_exact(
            command_id=first_id,
            receipts=receipts,
            runs=_MismatchedReader(),
            expected_specification=exact_specification,
        )

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("DELETE FROM research_run WHERE run_id = %s", (first.run_id.value,))
    with pytest.raises(OnlySearchProductSemanticFactCorrupt):
        only_load_search_research_run_exact(
            command_id=first_id,
            receipts=receipts,
            runs=run_reader,
            expected_specification=exact_specification,
        )
