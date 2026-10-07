from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from onlyalpha.application.chart_calculation_compilation import (
    OnlyChartCalculationCompilationV1,
    only_chart_calculation_specification_v3,
)
from onlyalpha.application.product_command_authority import OnlyProductCommandAuthorityUnavailableError
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.persistence.postgres.chart_calculation_compilation_store import (
    OnlyPostgresChartCalculationCompilationStore,
)
from onlyalpha.persistence.postgres.chart_calculation_preparation_store import (
    OnlyPostgresChartCalculationPreparationStore,
)
from onlyalpha.persistence.postgres.chart_calculation_store import OnlyPostgresChartCalculationAdmissionStore
from onlyalpha.runtime.research.control import (
    OnlyResearchRuntimeCancellationRequested,
    OnlyResearchRuntimeOwnershipLost,
)
from tests.research.postgres.test_chart_calculation_preparation import prepare, prepared_system
from tests.support.chart_calculation_compilation import resolve_publication

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]


@pytest.fixture
def compilation_system(postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    ready = prepare(system)
    operation = system.operation
    specification = only_chart_calculation_specification_v3(operation, ready)
    # Canonical registered compiler fixture only; hosted provenance is proved separately.
    resolution = resolve_publication(ready.runtime_generation_fingerprint, specification)
    compilation = OnlyChartCalculationCompilationV1(
        operation.operation_id,
        operation.intent_fingerprint,
        operation.catalog_witness.fingerprint,
        ready.revision,
        ready.fence,
        ready.input_selection_fingerprint,
        ready.dataset_snapshot_fingerprint,
        ready.dataset_materialization_id,
        ready.runtime_generation_fingerprint,
        ready.runtime_work_id,
        ready.runtime_binding_reference,
        operation.catalog_witness.capability.implementation_fingerprint,
        specification,
        resolution,
    )
    compilation.verify_operation_preparation(operation, ready)
    return SimpleNamespace(
        system=system,
        operation=operation,
        preparation=ready,
        compilation=compilation,
        dataset_root=tmp_path / "dataset",
        store=OnlyPostgresChartCalculationCompilationStore(postgres_dsn),
    )


def test_compilation_insert_and_exact_restart_replay(compilation_system, postgres_dsn: str) -> None:
    fixture = compilation_system
    assert fixture.store.load_verified(fixture.operation) is None
    assert (
        fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
        == fixture.compilation
    )
    restarted = OnlyPostgresChartCalculationCompilationStore(postgres_dsn)
    assert restarted.load_verified(fixture.operation) == fixture.compilation
    assert (
        restarted.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation) == fixture.compilation
    )
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM chart_calculation_compilation").fetchone()[0] == 1


def different_compilation(compilation):
    """Complete different DTO, not a claim that a host derived both graphs."""
    spec = compilation.specification
    calculation = spec.calculations[0]
    template = calculation.graph_template
    node = template.nodes[0]
    other_spec = replace(
        spec,
        calculations=(
            replace(
                calculation,
                graph_template=replace(
                    template,
                    nodes=(replace(node, parameters={**node.parameters, "period": node.parameters["period"] + 1}),),
                ),
            ),
        ),
    )
    other_resolution = resolve_publication(compilation.runtime_generation_fingerprint, other_spec)
    # Parameter normalization is hosted proof, deliberately not DTO-reader compilation.
    other_resolution = replace(
        other_resolution, specification=spec, specification_fingerprint=spec.specification_fingerprint
    )
    return replace(compilation, resolution=other_resolution)


@pytest.mark.parametrize("different", (False, True))
def test_parallel_compilations_converge_or_conflict_without_overwrite(
    compilation_system, postgres_dsn: str, different: bool
) -> None:
    fixture = compilation_system
    candidates = (fixture.compilation, different_compilation(fixture.compilation) if different else fixture.compilation)
    for candidate in candidates:
        candidate.verify_operation_preparation(fixture.operation, fixture.preparation)
    barrier = Barrier(2)

    def commit(candidate):
        barrier.wait()
        try:
            return fixture.store.commit_or_replay(fixture.operation, fixture.preparation, candidate)
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(commit, candidates))
    existing = fixture.store.load_verified(fixture.operation)
    if different:
        assert outcomes.count("CHART_SPECIFICATION_COMPILATION_CONFLICT") == 1
        assert sum(isinstance(value, OnlyChartCalculationCompilationV1) for value in outcomes) == 1
        assert existing in candidates and existing in outcomes
    else:
        assert outcomes == candidates and existing == fixture.compilation
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM chart_calculation_compilation").fetchone()[0] == 1


def test_complete_different_replay_conflicts_without_overwrite(compilation_system) -> None:
    fixture = compilation_system
    fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    alternative = different_compilation(fixture.compilation)
    alternative.verify_operation_preparation(fixture.operation, fixture.preparation)
    with pytest.raises(ValueError, match="CHART_SPECIFICATION_COMPILATION_CONFLICT"):
        fixture.store.commit_or_replay(fixture.operation, fixture.preparation, alternative)
    assert fixture.store.load_verified(fixture.operation) == fixture.compilation


def authority_facts(dsn):
    with psycopg.connect(dsn) as connection:
        return {
            table: connection.execute(
                sql.SQL("SELECT row_to_json(t)::text FROM {} t ORDER BY row_to_json(t)::text").format(
                    sql.Identifier(table)
                )
            ).fetchall()
            for table in (
                "chart_calculation_operation",
                "chart_calculation_preparation_fact",
                "product_command_admission",
                "product_command_receipt",
                "research_run_id_reservation",
                "research_run",
                "research_run_attempt",
            )
        }


def test_store_replay_needs_no_current_host_and_preserves_all_prerequisites(
    compilation_system, postgres_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = compilation_system
    before = authority_facts(postgres_dsn)
    dataset_before = {
        path.relative_to(fixture.dataset_root): path.read_bytes()
        for path in fixture.dataset_root.rglob("*")
        if path.is_file()
    }
    for method in ("require_runtime_generation", "require_new_work_generation", "bind_new_work_exact", "release_work"):
        monkeypatch.setattr(
            fixture.system.runtime, method, lambda *args, **kwargs: pytest.fail("store used Runtime host")
        )
    fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    assert fixture.store.load_verified(fixture.operation) == fixture.compilation
    assert (
        fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
        == fixture.compilation
    )
    assert authority_facts(postgres_dsn) == before
    assert before["research_run"] == before["research_run_attempt"] == []
    assert {
        path.relative_to(fixture.dataset_root): path.read_bytes()
        for path in fixture.dataset_root.rglob("*")
        if path.is_file()
    } == dataset_before


@pytest.mark.parametrize("committed", (False, True))
def test_storage_error_recovers_only_exact_committed_relation(
    compilation_system, postgres_dsn: str, monkeypatch: pytest.MonkeyPatch, committed: bool
) -> None:
    fixture = compilation_system
    before = authority_facts(postgres_dsn)
    connect = psycopg.connect
    lost = []

    class LostAcknowledgement:
        def __init__(self, connection):
            self.connection = connection
            self.wrote = False

        def execute(self, query, *args):
            if "INSERT INTO chart_calculation_compilation" in str(query):
                self.wrote = True
            return self.connection.execute(query, *args)

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            if self.wrote and args[0] is None and not lost:
                lost.append(True)
                if not committed:
                    self.connection.rollback()
                self.connection.__exit__(*args)
                raise psycopg.OperationalError("injected lost commit acknowledgement")
            return self.connection.__exit__(*args)

    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: LostAcknowledgement(connect(*args, **kwargs)))
    if committed:
        assert (
            fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
            == fixture.compilation
        )
    else:
        with pytest.raises(OnlyProductCommandAuthorityUnavailableError):
            fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    assert lost == [True]
    assert fixture.store.load_verified(fixture.operation) == (fixture.compilation if committed else None)
    assert authority_facts(postgres_dsn) == before


@pytest.mark.parametrize(
    "field",
    [
        "intent_fingerprint",
        "catalog_witness_fingerprint",
        "input_preparation_revision",
        "input_preparation_fence",
        "input_selection_fingerprint",
        "dataset_snapshot_fingerprint",
        "dataset_materialization_id",
        "runtime_work_id",
        "runtime_generation_fingerprint",
        "runtime_binding_reference",
        "catalog_implementation_fingerprint",
        "operation_id",
    ],
)
def test_candidate_context_mutations_never_insert(compilation_system, field: str) -> None:
    fixture = compilation_system
    candidate = fixture.compilation
    value = getattr(candidate, field)
    if field in {"input_preparation_revision", "input_preparation_fence"}:
        value += 1
    elif field == "operation_id":
        from onlyalpha.application.product_command_receipt import OnlyProductCommandId

        value = OnlyProductCommandId("00000000-0000-4000-8000-000000000799")
    elif field == "runtime_generation_fingerprint":
        value = "f" * 64
        candidate = replace(
            candidate,
            runtime_generation_fingerprint=value,
            runtime_binding_reference=replace(
                candidate.runtime_binding_reference, runtime_generation_fingerprint=value
            ),
            resolution=replace(candidate.resolution, runtime_generation_fingerprint=value),
        )
    elif field == "runtime_work_id":
        value = "00000000-0000-4000-8000-000000000799"
        candidate = replace(
            candidate,
            runtime_work_id=value,
            runtime_binding_reference=replace(candidate.runtime_binding_reference, work_id=value),
        )
    elif field == "runtime_binding_reference":
        value = replace(value, binding_event_fingerprint="f" * 64)
    elif field == "dataset_materialization_id":
        value = "dataset-materialization:" + "f" * 64
    elif field == "dataset_snapshot_fingerprint":
        value = "f" * 64
        spec = replace(candidate.specification, dataset_snapshot_fingerprint=value)
        candidate = replace(
            candidate,
            dataset_snapshot_fingerprint=value,
            specification=spec,
            resolution=resolve_publication(candidate.runtime_generation_fingerprint, spec),
        )
    elif field == "catalog_implementation_fingerprint":
        from onlyalpha.research.calculation.execution import OnlyResearchCalculationImplementationBinding

        manifest = replace(candidate.resolution.implementation_manifest, entrypoint_identity="other:entrypoint")
        value = manifest.implementation_fingerprint
        candidate = replace(
            candidate,
            catalog_implementation_fingerprint=value,
            resolution=replace(
                candidate.resolution,
                implementation_manifest=manifest,
                research_implementation_bindings=(
                    OnlyResearchCalculationImplementationBinding(
                        candidate.resolution.calculation_graph.nodes[0].fingerprint, value
                    ),
                ),
            ),
        )
    else:
        value = "f" * 64
    candidate = replace(candidate, **{field: value})
    with pytest.raises(ValueError, match="CHART_SPECIFICATION_COMPILATION_CONFLICT|CHART_COMPILATION_RELATION_CORRUPT"):
        fixture.store.commit_or_replay(fixture.operation, fixture.preparation, candidate)
    assert fixture.store.load_verified(fixture.operation) is None


def test_stale_preparation_is_not_an_insert_permit(compilation_system) -> None:
    fixture = compilation_system
    stale = replace(fixture.preparation, revision=fixture.preparation.revision + 1)
    candidate = replace(fixture.compilation, input_preparation_revision=stale.revision)
    candidate.verify_operation_preparation(fixture.operation, stale)
    with pytest.raises(ValueError, match="CHART_SPECIFICATION_COMPILATION_CONFLICT"):
        fixture.store.commit_or_replay(fixture.operation, stale, candidate)
    assert fixture.store.load_verified(fixture.operation) is None


def test_caller_operation_must_equal_whole_admitted_operation(compilation_system) -> None:
    fixture = compilation_system
    alternative = replace(fixture.operation, accepted_at=fixture.operation.accepted_at + timedelta(seconds=1))
    fixture.compilation.verify_operation_preparation(alternative, fixture.preparation)
    with pytest.raises(ValueError, match="CHART_OPERATION_RELATION_CORRUPT"):
        fixture.store.load_verified(alternative)
    with pytest.raises(ValueError, match="CHART_OPERATION_RELATION_CORRUPT"):
        fixture.store.commit_or_replay(alternative, fixture.preparation, fixture.compilation)
    assert fixture.store.load_verified(fixture.operation) is None


def test_untyped_candidate_is_never_an_insert_permit(compilation_system) -> None:
    fixture = compilation_system
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation.to_dict())
    assert fixture.store.load_verified(fixture.operation) is None


@pytest.mark.parametrize(
    "column,value",
    [
        ("input_preparation_revision", 99),
        ("input_preparation_fence", 2),
        ("input_selection_fingerprint", "f" * 64),
        ("dataset_snapshot_fingerprint", "f" * 64),
        ("dataset_materialization_id", "dataset-materialization:" + "f" * 64),
        ("runtime_generation_fingerprint", "f" * 64),
        ("runtime_work_id", "00000000-0000-4000-8000-000000000799"),
        ("runtime_binding_event_fingerprint", "f" * 64),
        ("catalog_witness_fingerprint", "f" * 64),
        ("catalog_implementation_fingerprint", "f" * 64),
        ("specification_fingerprint", "f" * 64),
        ("result_plan_fingerprint", "f" * 64),
        ("graph_fingerprint", "f" * 64),
        ("calculation_fingerprint", "f" * 64),
        ("implementation_fingerprint", "f" * 64),
        ("compilation_fingerprint", "f" * 64),
    ],
)
def test_every_redundant_column_is_verified(compilation_system, postgres_dsn: str, column: str, value: object) -> None:
    fixture = compilation_system
    fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "ALTER TABLE chart_calculation_compilation DISABLE TRIGGER chart_calculation_compilation_immutable"
        )
        connection.execute(
            sql.SQL("UPDATE chart_calculation_compilation SET {} = %s").format(sql.Identifier(column)), (value,)
        )
        connection.execute(
            "ALTER TABLE chart_calculation_compilation ENABLE TRIGGER chart_calculation_compilation_immutable"
        )
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        fixture.store.load_verified(fixture.operation)
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)


@pytest.mark.parametrize(
    "mutation",
    [
        "empty",
        "unknown",
        "owner",
        "missing_resolution",
        "missing_binding",
        "duplicate_binding",
        "wrong_family",
        "wrong_specification",
        "unknown_schema",
        "boolean_schema",
        "noncanonical",
        "duplicate_json_key",
    ],
)
def test_strict_stored_relation_mutations_fail_closed(compilation_system, postgres_dsn: str, mutation: str) -> None:
    fixture = compilation_system
    fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    raw = fixture.compilation.to_dict()
    if mutation == "empty":
        raw = {}
    elif mutation == "unknown":
        raw["unknown"] = None
    elif mutation == "owner":
        raw["operation_id"] = "00000000-0000-4000-8000-000000000799"
    elif mutation == "missing_resolution":
        del raw["resolution"]
    elif mutation == "missing_binding":
        del raw["runtime_binding_reference"]
    elif mutation == "duplicate_binding":
        raw["resolution"]["research_implementation_bindings"] *= 2
    elif mutation == "wrong_family":
        raw["runtime_binding_reference"]["binding_owner"] = "SEARCH"
    elif mutation == "wrong_specification":
        raw["resolution"]["specification_fingerprint"] = "f" * 64
    elif mutation == "unknown_schema":
        raw["schema_version"] = 2
    elif mutation == "boolean_schema":
        raw["schema_version"] = True
    body = only_canonical_json(raw)
    if mutation == "noncanonical":
        body = json.dumps(raw, indent=2)
    elif mutation == "duplicate_json_key":
        body = body[:-1] + ',"schema_version":1}'
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "ALTER TABLE chart_calculation_compilation DISABLE TRIGGER chart_calculation_compilation_immutable"
        )
        connection.execute(
            "UPDATE chart_calculation_compilation SET compilation_json = %s, compilation_fingerprint = %s",
            (
                body,
                only_canonical_fingerprint({"domain": "onlyalpha.chart-calculation-compilation.v1", "relation": raw}),
            ),
        )
        connection.execute(
            "ALTER TABLE chart_calculation_compilation ENABLE TRIGGER chart_calculation_compilation_immutable"
        )
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        fixture.store.load_verified(fixture.operation)
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)


@pytest.mark.parametrize(
    "field",
    [
        "intent_fingerprint",
        "catalog_witness_fingerprint",
        "input_preparation_revision",
        "input_preparation_fence",
        "input_selection_fingerprint",
        "dataset_materialization_id",
        "binding_event_fingerprint",
        "binding_sequence",
        "binding_actor",
    ],
)
def test_complete_different_stored_context_is_corruption_not_replacement(
    compilation_system, postgres_dsn: str, field: str
) -> None:
    fixture = compilation_system
    original = fixture.compilation
    fixture.store.commit_or_replay(fixture.operation, fixture.preparation, original)
    updates = {}
    if field.startswith("binding_"):
        reference = original.runtime_binding_reference
        value = 2 if field == "binding_sequence" else "other-actor" if field == "binding_actor" else "f" * 64
        alternative = replace(original, runtime_binding_reference=replace(reference, **{field: value}))
        updates["runtime_binding_event_fingerprint"] = alternative.runtime_binding_reference.binding_event_fingerprint
    else:
        value = getattr(original, field)
        value = (
            value + 1
            if type(value) is int
            else "dataset-materialization:" + "f" * 64
            if field == "dataset_materialization_id"
            else "f" * 64
        )
        alternative = replace(original, **{field: value})
        if field != "intent_fingerprint":
            updates[field] = value
    assert OnlyChartCalculationCompilationV1.from_dict(alternative.to_dict()) == alternative
    updates.update(
        compilation_json=only_canonical_json(alternative.to_dict()),
        compilation_fingerprint=alternative.compilation_fingerprint,
    )
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "ALTER TABLE chart_calculation_compilation DISABLE TRIGGER chart_calculation_compilation_immutable"
        )
        connection.execute(
            sql.SQL("UPDATE chart_calculation_compilation SET {}").format(
                sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(column)) for column in updates)
            ),
            tuple(updates.values()),
        )
        connection.execute(
            "ALTER TABLE chart_calculation_compilation ENABLE TRIGGER chart_calculation_compilation_immutable"
        )
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        fixture.store.load_verified(fixture.operation)
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        fixture.store.commit_or_replay(fixture.operation, fixture.preparation, original)
    with psycopg.connect(postgres_dsn) as connection:
        assert (
            connection.execute("SELECT compilation_json FROM chart_calculation_compilation").fetchone()[0]
            == updates["compilation_json"]
        )


@pytest.mark.parametrize("with_row", (False, True))
@pytest.mark.parametrize(
    "table",
    [
        "product_command_admission",
        "product_command_receipt",
        "research_run_id_reservation",
        "chart_calculation_operation",
    ],
)
def test_t1_context_is_always_reverified_without_repair(
    compilation_system, postgres_dsn: str, table: str, with_row: bool
) -> None:
    fixture = compilation_system
    if with_row:
        fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(sql.SQL("ALTER TABLE {} DISABLE TRIGGER ALL").format(sql.Identifier(table)))
        connection.execute(sql.SQL("DELETE FROM {}").format(sql.Identifier(table)))
        connection.execute(sql.SQL("ALTER TABLE {} ENABLE TRIGGER ALL").format(sql.Identifier(table)))
    before = authority_facts(postgres_dsn)
    with pytest.raises(ValueError, match="CHART_OPERATION_RELATION_CORRUPT"):
        fixture.store.load_verified(fixture.operation)
    with pytest.raises(ValueError, match="CHART_OPERATION_RELATION_CORRUPT"):
        fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    assert authority_facts(postgres_dsn) == before


@pytest.mark.parametrize("with_row", (False, True))
def test_preparation_chain_is_always_reverified(compilation_system, postgres_dsn: str, with_row: bool) -> None:
    fixture = compilation_system
    if with_row:
        fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("ALTER TABLE chart_calculation_preparation_fact DISABLE TRIGGER ALL")
        connection.execute(
            "UPDATE chart_calculation_preparation_fact SET fact_fingerprint = %s WHERE revision = 1", ("f" * 64,)
        )
        connection.execute("ALTER TABLE chart_calculation_preparation_fact ENABLE TRIGGER ALL")
    before = authority_facts(postgres_dsn)
    with pytest.raises(ValueError, match="CHART_PREPARATION_RELATION_CORRUPT"):
        fixture.store.load_verified(fixture.operation)
    with pytest.raises(ValueError, match="CHART_PREPARATION_RELATION_CORRUPT"):
        fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    assert authority_facts(postgres_dsn) == before


@pytest.mark.parametrize("field", ("dataset_snapshot_fingerprint", "dataset_materialization_id"))
def test_recomputed_ready_fact_cannot_redefine_stored_compilation(
    compilation_system, postgres_dsn: str, field: str
) -> None:
    fixture = compilation_system
    fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    with psycopg.connect(postgres_dsn) as connection:
        row = connection.execute(
            "SELECT fact_json FROM chart_calculation_preparation_fact WHERE kind = 'INPUT_READY'"
        ).fetchone()
        body = json.loads(row[0])
        body["preparation"][field] = (
            "dataset-materialization:" + "f" * 64 if field == "dataset_materialization_id" else "f" * 64
        )
        connection.execute("ALTER TABLE chart_calculation_preparation_fact DISABLE TRIGGER ALL")
        connection.execute(
            "UPDATE chart_calculation_preparation_fact SET fact_json = %s, fact_fingerprint = %s WHERE kind = 'INPUT_READY'",
            (only_canonical_json(body), only_canonical_fingerprint(body)),
        )
        connection.execute("ALTER TABLE chart_calculation_preparation_fact ENABLE TRIGGER ALL")
    current = fixture.system.adapter.load_verified(fixture.operation)
    assert current.state == "INPUT_READY" and getattr(current, field) != getattr(fixture.preparation, field)
    before = authority_facts(postgres_dsn)
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        fixture.store.load_verified(fixture.operation)
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    assert authority_facts(postgres_dsn) == before


def test_foreign_operation_primary_key_cannot_adopt_copied_compilation(compilation_system, postgres_dsn: str) -> None:
    from onlyalpha.application.product_command_receipt import OnlyProductCommandId
    from tests.application.test_chart_calculation_admission import NOW

    fixture = compilation_system
    fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    foreign = (
        OnlyPostgresChartCalculationAdmissionStore(postgres_dsn)
        .admit_or_replay(
            OnlyProductCommandId("00000000-0000-4000-8000-000000000799"),
            fixture.operation.intent,
            fixture.operation.catalog_witness,
            accepted_at=NOW,
        )
        .operation
    )
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "ALTER TABLE chart_calculation_compilation DISABLE TRIGGER chart_calculation_compilation_immutable"
        )
        connection.execute("UPDATE chart_calculation_compilation SET operation_id = %s", (foreign.operation_id.value,))
        connection.execute(
            "ALTER TABLE chart_calculation_compilation ENABLE TRIGGER chart_calculation_compilation_immutable"
        )
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        fixture.store.load_verified(foreign)


def test_missing_preparation_cannot_certify_existing_relation(compilation_system, postgres_dsn: str) -> None:
    fixture = compilation_system
    fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("ALTER TABLE chart_calculation_preparation_fact DISABLE TRIGGER ALL")
        connection.execute("DELETE FROM chart_calculation_preparation_fact")
        connection.execute("ALTER TABLE chart_calculation_preparation_fact ENABLE TRIGGER ALL")
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        fixture.store.load_verified(fixture.operation)
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)


def test_redundant_schema_version_corruption_is_not_ignored(compilation_system, postgres_dsn: str) -> None:
    fixture = compilation_system
    fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    with psycopg.connect(postgres_dsn) as connection:
        constraint = connection.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'chart_calculation_compilation'::regclass AND pg_get_constraintdef(oid) LIKE '%schema_version%'"
        ).fetchone()[0]
        # Only this isolated test-owner fixture bypasses the check and immutable trigger.
        connection.execute(
            sql.SQL("ALTER TABLE chart_calculation_compilation DROP CONSTRAINT {}").format(sql.Identifier(constraint))
        )
        connection.execute(
            "ALTER TABLE chart_calculation_compilation DISABLE TRIGGER chart_calculation_compilation_immutable"
        )
        connection.execute("UPDATE chart_calculation_compilation SET schema_version = 2")
        connection.execute(
            "ALTER TABLE chart_calculation_compilation ENABLE TRIGGER chart_calculation_compilation_immutable"
        )
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        fixture.store.load_verified(fixture.operation)


def test_malformed_stored_json_is_corruption(compilation_system, postgres_dsn: str) -> None:
    fixture = compilation_system
    fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    with psycopg.connect(postgres_dsn) as connection:
        constraint = connection.execute(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'chart_calculation_compilation'::regclass AND pg_get_constraintdef(oid) LIKE '%compilation_json%'"
        ).fetchone()[0]
        connection.execute(
            sql.SQL("ALTER TABLE chart_calculation_compilation DROP CONSTRAINT {}").format(sql.Identifier(constraint))
        )
        connection.execute(
            "ALTER TABLE chart_calculation_compilation DISABLE TRIGGER chart_calculation_compilation_immutable"
        )
        connection.execute("UPDATE chart_calculation_compilation SET compilation_json = '{'")
        connection.execute(
            "ALTER TABLE chart_calculation_compilation ENABLE TRIGGER chart_calculation_compilation_immutable"
        )
    with pytest.raises(ValueError, match="CHART_COMPILATION_RELATION_CORRUPT"):
        fixture.store.load_verified(fixture.operation)


@pytest.mark.parametrize("state", ("MATERIALIZING_INPUT", "FAILED"))
def test_non_ready_preparation_cannot_create_compilation(compilation_system, postgres_dsn: str, state: str) -> None:
    fixture = compilation_system
    # Keep the valid CLAIM prefix; remove later facts as controlled fixture corruption.
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("ALTER TABLE chart_calculation_preparation_fact DISABLE TRIGGER ALL")
        connection.execute("DELETE FROM chart_calculation_preparation_fact WHERE revision > 1")
        connection.execute("ALTER TABLE chart_calculation_preparation_fact ENABLE TRIGGER ALL")
    claim = fixture.system.adapter.load_verified(fixture.operation)
    if state == "FAILED":
        from onlyalpha.application.runtime_generation import OnlyRuntimeWorkAdmissionClosureEvidence

        decision = fixture.system.adapter.begin_failure(
            fixture.operation, claim, "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE"
        )
        closure = OnlyRuntimeWorkAdmissionClosureEvidence(
            claim.runtime_work_id,
            claim.runtime_generation_fingerprint,
            "CHART_CALCULATION_INPUT",
            "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE",
            "test",
            "f" * 64,
            2,
        )
        fixture.system.adapter.fail(
            fixture.operation, decision, "CHART_RUNTIME_GENERATION_NOT_ELIGIBLE", closure_reference=closure
        )
    before = authority_facts(postgres_dsn)
    assert fixture.store.load_verified(fixture.operation) is None
    with pytest.raises(ValueError, match="CHART_INPUT_NOT_READY"):
        fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    assert fixture.store.load_verified(fixture.operation) is None
    assert authority_facts(postgres_dsn) == before


def test_unknown_storage_outcome_cannot_adopt_complete_different_relation(
    compilation_system, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = compilation_system
    alternative = different_compilation(fixture.compilation)
    fixture.store.commit_or_replay(fixture.operation, fixture.preparation, alternative)
    connect = psycopg.connect
    failed = []

    class ConnectionLoss:
        def __init__(self, connection):
            self.connection = connection

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

        def execute(self, query, *args):
            if "SELECT * FROM chart_calculation_compilation" in str(query) and not failed:
                failed.append(True)
                raise psycopg.OperationalError("injected interrupted relation read")
            return self.connection.execute(query, *args)

    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: ConnectionLoss(connect(*args, **kwargs)))
    with pytest.raises(OnlyProductCommandAuthorityUnavailableError):
        fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    assert failed == [True]
    assert fixture.store.load_verified(fixture.operation) == alternative


@pytest.mark.parametrize(
    "signal",
    (KeyboardInterrupt, SystemExit, OnlyResearchRuntimeCancellationRequested, OnlyResearchRuntimeOwnershipLost),
)
def test_control_signals_escape_without_reconciliation_or_insert(
    compilation_system, monkeypatch: pytest.MonkeyPatch, signal
) -> None:
    fixture = compilation_system
    connect = psycopg.connect
    calls = []

    class Interrupted:
        def __init__(self, connection):
            self.connection = connection

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

        def execute(self, query, *args):
            if "INSERT INTO chart_calculation_compilation" in str(query):
                raise signal("injected process control signal")
            return self.connection.execute(query, *args)

    def interrupted(*args, **kwargs):
        calls.append(True)
        return Interrupted(connect(*args, **kwargs))

    monkeypatch.setattr(psycopg, "connect", interrupted)
    with pytest.raises(signal):
        fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    assert calls == [True]
    assert fixture.store.load_verified(fixture.operation) is None


def test_compilation_transaction_readers_preserve_verified_operation_and_ready_history(
    postgres_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    ready = prepare(system)
    with psycopg.connect(postgres_dsn, row_factory=dict_row) as connection:
        operation = OnlyPostgresChartCalculationAdmissionStore.load_verified_in_transaction(
            connection, system.operation.operation_id
        )
        assert operation == system.operation
        assert OnlyPostgresChartCalculationPreparationStore.load_verified_in_transaction(connection, operation) == ready
    assert system.adapter.load_verified(system.operation) == ready
