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
)
from onlyalpha.application.search_product import (
    OnlySearchProductCommandServiceV1,
    OnlySearchProductSemanticFactCorrupt,
    OnlySubmitParameterSearchExperimentV2,
    only_load_search_research_run_exact,
)
from onlyalpha.persistence.postgres import (
    OnlyPostgresProductCommandAuthority,
    OnlyPostgresResearchRunStore,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.research.command.query import OnlyResearchRunQueryService
from onlyalpha.research.experiment import (
    OnlySearchBudgetV1,
    OnlySearchDecisionEngineBindingV1,
    OnlySearchDecisionMode,
    OnlySearchHypothesisV1,
    OnlySearchWorkflowBindingV1,
)
from onlyalpha.research.search.parameter import (
    OnlyParameterFactorSearchSpaceV1,
    OnlyParameterObjectiveDirection,
    OnlyParameterResearchEvidenceReader,
    OnlyParameterSearchPolicyV1,
    OnlyParameterSearchProductAdapterV1,
    OnlyParameterTieBreakerV1,
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
    _stores,
    _topology,
)

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]

_NOW = datetime(2026, 9, 8, tzinfo=UTC)


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
