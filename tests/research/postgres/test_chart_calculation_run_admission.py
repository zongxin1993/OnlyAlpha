from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier

import psycopg
import pytest

from onlyalpha.application.product_command_authority import OnlyProductCommandAuthorityUnavailableError
from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.persistence.postgres.chart_calculation_preparation_store import (
    OnlyPostgresChartCalculationPreparationStore,
)
from onlyalpha.persistence.postgres.chart_calculation_store import OnlyPostgresChartCalculationAdmissionStore
from onlyalpha.persistence.postgres.research_execution_store import OnlyPostgresResearchExecutionStore
from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore
from onlyalpha.persistence.postgres.research_source_cut_store import OnlyPostgresResearchSourceCutAuthority
from onlyalpha.research.execution.model import OnlyResearchRunAttemptId, OnlyResearchWorkerInstanceId
from onlyalpha.research.run.model import OnlyResearchRunState
from tests.application.test_chart_calculation_admission import NOW
from tests.research.postgres.test_chart_calculation_compilation import (
    authority_facts,
    different_compilation,
)
from tests.research.postgres.test_chart_calculation_compilation import compilation_system as compilation_system

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]


def handoff(fixture, dsn):
    from onlyalpha.persistence.postgres.research_chart_calculation_run_admission_store import (
        OnlyPostgresChartCalculationRunAdmissionStore,
    )

    fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    return OnlyPostgresChartCalculationRunAdmissionStore(dsn, runtime_generations=fixture.system.runtime)


def test_atomic_handoff_exact_restart_and_concurrent_replay(compilation_system, postgres_dsn: str) -> None:
    fixture = compilation_system
    store = handoff(fixture, postgres_dsn)
    barrier = Barrier(2)

    def commit(_):
        barrier.wait()
        return store.commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = tuple(pool.map(commit, range(2)))
    assert runs[0] == runs[1]
    assert runs[0].run_id == fixture.operation.reserved_run_id
    assert runs[0].origin_kind.value == "CHART_CALCULATION"
    assert runs[0].state.value == "QUEUED"
    assert store.load_verified(fixture.operation) == runs[0]
    assert OnlyPostgresResearchRunStore(postgres_dsn).load(runs[0].run_id) == runs[0]
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_run").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM chart_calculation_run_admission").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM research_run_id_reservation").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM research_run_attempt").fetchone() == (0,)


def test_consumed_reservation_cannot_be_reinserted(compilation_system, postgres_dsn: str) -> None:
    fixture = compilation_system
    store = handoff(fixture, postgres_dsn)
    run = store.commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    with pytest.raises(psycopg.Error, match="CHART_RUN_ADMISSION_RELATION_CORRUPT"):
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(
                "INSERT INTO research_run_id_reservation (run_id, owner_kind, owner_id, reserved_at, schema_version) VALUES (%s,'CHART_CALCULATION',%s,%s,1)",
                (run.run_id.value, fixture.operation.operation_id.value, fixture.operation.accepted_at),
            )
    assert store.load_verified(fixture.operation) == run


def test_legacy_store_cannot_claim_even_explicitly_eligible_chart(compilation_system, postgres_dsn: str) -> None:
    fixture = compilation_system
    store = handoff(fixture, postgres_dsn)
    run = store.commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    execution = OnlyPostgresResearchExecutionStore(postgres_dsn)
    for eligible in (None, (run.run_id.value,)):
        assert (
            execution.claim_next(
                worker_instance_id=OnlyResearchWorkerInstanceId.new(),
                attempt_id=OnlyResearchRunAttemptId.new(),
                lease_duration=timedelta(seconds=60),
                max_attempts=3,
                run_started_at=NOW,
                eligible_run_ids=eligible,
            )
            is None
        )
        assert execution.expire_next(max_attempts=3, run_finished_at=NOW, eligible_run_ids=eligible) is None
        assert execution.load_cancellation_recovery_candidate(eligible) is None
    assert OnlyPostgresResearchRunStore(postgres_dsn).load(run.run_id) == run


def test_consumption_preserves_t1_t2_d2_readers_and_human_cancellation(compilation_system, postgres_dsn: str) -> None:
    fixture = compilation_system
    store = handoff(fixture, postgres_dsn)
    run = store.commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    runs = OnlyPostgresResearchRunStore(postgres_dsn)
    cancelled = runs.commit_transition(run, run.transition(OnlyResearchRunState.CANCELLED, at=NOW))
    fixture.system.runtime.release_work(run.run_id.value, actor="human-cancel", occurred_at=NOW)
    fixture.system.runtime.require_runtime_generation.side_effect = AssertionError("replay used execution availability")
    assert (
        store.commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW + timedelta(minutes=1))
        == cancelled
    )
    assert (
        OnlyPostgresChartCalculationAdmissionStore(postgres_dsn).load_verified(fixture.operation.operation_id)
        == fixture.operation
    )
    assert (
        OnlyPostgresChartCalculationPreparationStore(postgres_dsn).load_verified(fixture.operation)
        == fixture.preparation
    )
    assert fixture.store.load_verified(fixture.operation) == fixture.compilation
    assert runs.load(run.run_id) == cancelled
    assert runs.list_recent(limit=10) == (cancelled,)
    source = OnlyPostgresResearchSourceCutAuthority(postgres_dsn)
    cut = source.capture_closed_cut("RESEARCH_RUN")
    observations = source.iter_closed_cut_observations_verified(cut.cut_fingerprint, "RESEARCH_RUN")
    assert [item.canonical_payload["source_row"]["state"] for item in observations] == ["QUEUED", "CANCELLED"]
    assert all(item.canonical_payload["source_row"]["origin_kind"] == "CHART_CALCULATION" for item in observations)


@pytest.mark.parametrize("outcome", ["committed", "rolled_back", "silent_rollback"])
def test_commit_ambiguity_requires_postcommit_composite_proof(
    compilation_system, postgres_dsn: str, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    fixture = compilation_system
    store = handoff(fixture, postgres_dsn)
    before = authority_facts(postgres_dsn)
    connect = psycopg.connect
    injected = []

    class CommitFault:
        def __init__(self, connection):
            self.connection = connection
            self.wrote = False

        def execute(self, query, *args):
            if "INSERT INTO chart_calculation_run_admission" in str(query):
                self.wrote = True
            return self.connection.execute(query, *args)

        def commit(self):
            if self.wrote and not injected:
                injected.append(outcome)
                if outcome == "committed":
                    self.connection.commit()
                else:
                    self.connection.rollback()
                if outcome != "silent_rollback":
                    raise psycopg.OperationalError("injected commit acknowledgement loss")
                return None
            return self.connection.commit()

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: CommitFault(connect(*args, **kwargs)))
    if outcome == "committed":
        run = store.commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
        assert store.load_verified(fixture.operation) == run
    elif outcome == "rolled_back":
        with pytest.raises(OnlyProductCommandAuthorityUnavailableError):
            store.commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
        assert authority_facts(postgres_dsn) == before
    else:
        with pytest.raises(ValueError, match="CHART_RUN_ADMISSION_COMMIT_UNKNOWN"):
            store.commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
        assert authority_facts(postgres_dsn) == before
    assert injected == [outcome]
    fixture.system.runtime.release_work.assert_not_called()


def test_authoritative_compilation_not_caller_self_consistency(compilation_system, postgres_dsn: str) -> None:
    fixture = compilation_system
    store = handoff(fixture, postgres_dsn)
    alternative = different_compilation(fixture.compilation)
    alternative.verify_operation_preparation(fixture.operation, fixture.preparation)
    before = authority_facts(postgres_dsn)
    with pytest.raises(ValueError, match="CHART_RUN_ADMISSION_CONFLICT"):
        store.commit_or_replay(fixture.operation, alternative, queued_at=NOW)
    assert authority_facts(postgres_dsn) == before


def test_concurrent_new_operation_and_handoff_preserve_lock_order(
    compilation_system, postgres_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from threading import Event, local

    from tests.application.test_chart_calculation_admission import request, witness

    fixture = compilation_system
    handoff_store = handoff(fixture, postgres_dsn)
    new_operation_store = OnlyPostgresChartCalculationAdmissionStore(postgres_dsn)
    command = OnlyProductCommandId("00000000-0000-4000-8000-000000000951")
    shared_table_held, resume_new_operation = Event(), Event()
    actor = local()
    connect = psycopg.connect

    class LockSchedule:
        def __init__(self, connection):
            self.connection = connection
            self.role = getattr(actor, "role", None)

        def execute(self, query, *args):
            text = str(query)
            if self.role == "handoff" and text == "LOCK TABLE research_run IN ROW EXCLUSIVE MODE":
                # Correct table-first order blocks on T1 without owning the frontier.
                resume_new_operation.set()
            result = self.connection.execute(query, *args)
            if self.role == "new_operation" and text == "LOCK TABLE research_run IN SHARE MODE":
                shared_table_held.set()
                assert resume_new_operation.wait(timeout=30)
            if self.role == "handoff" and "SELECT last_index FROM research_source_history_frontier" in text:
                # Reproduce the old inverse order: D3 owns frontier while T1 owns SHARE.
                resume_new_operation.set()
            return result

        def commit(self):
            return self.connection.commit()

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: LockSchedule(connect(*args, **kwargs)))

    def admit_new_operation():
        actor.role = "new_operation"
        return new_operation_store.admit_or_replay(command, request(), witness(), accepted_at=NOW)

    def admit_run():
        actor.role = "handoff"
        return handoff_store.commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        new = pool.submit(admit_new_operation)
        assert shared_table_held.wait(timeout=30)
        queued = pool.submit(admit_run)
        assert new.result(timeout=60).operation.operation_id == command
        assert queued.result(timeout=60).run_id == fixture.operation.reserved_run_id


@pytest.mark.parametrize("reference", ["result", "artifact", "evidence"])
def test_cancellation_references_are_rejected_without_corrupting_admission(
    compilation_system, postgres_dsn: str, reference: str
) -> None:
    from onlyalpha.research.run.errors import OnlyResearchRunIntegrityError

    fixture = compilation_system
    store = handoff(fixture, postgres_dsn)
    run = store.commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    runs = OnlyPostgresResearchRunStore(postgres_dsn)
    before = authority_facts(postgres_dsn)
    references = {"research_result_fingerprint": "a" * 64}
    if reference in {"artifact", "evidence"}:
        references["artifact_content_fingerprint"] = "b" * 64
    if reference == "evidence":
        references["calculation_execution_evidence_fingerprints"] = ("c" * 64,)
    with pytest.raises(OnlyResearchRunIntegrityError):
        cancelled = run.transition(OnlyResearchRunState.CANCELLED, at=NOW, **references)
        runs.commit_transition(run, cancelled)
    assert authority_facts(postgres_dsn) == before
    assert store.load_verified(fixture.operation) == run


def test_postcut_locator_owner_swap_is_not_certified_irrelevance(compilation_system, postgres_dsn: str) -> None:
    from psycopg.rows import dict_row

    from onlyalpha.research.source_cut import OnlySourceCutError
    from tests.research.postgres.test_novelty_read_to_act import _admission, _frontier, _preadmit
    from tests.research.postgres.test_postgres_authority import _create_receipt, _queued

    fixture = compilation_system
    chart = handoff(fixture, postgres_dsn)
    scientific = _queued("00000000-0000-4000-8000-000000000952")
    command = OnlyProductCommandId("00000000-0000-4000-8000-000000000953")
    subject = "4" * 64
    _preadmit(postgres_dsn, command, "a" * 64)
    runs = OnlyPostgresResearchRunStore(postgres_dsn)
    runs._create_queued_with_verified_novelty_admission(
        scientific,
        _create_receipt(command, scientific, "a" * 64),
        _admission(command, "a" * 64, scientific, subject),
        expected_source_frontier=_frontier(postgres_dsn),
    )
    frontier = _frontier(postgres_dsn)
    chart.commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    with psycopg.connect(postgres_dsn, row_factory=dict_row) as connection:
        connection.execute("SET LOCAL session_replication_role = replica")
        connection.execute(
            "UPDATE research_source_history SET native_locator = %s WHERE source_family = 'RESEARCH_RUN' AND event_index > %s",
            (scientific.run_id.value, frontier),
        )
    with psycopg.connect(postgres_dsn, row_factory=dict_row) as connection:
        with pytest.raises(OnlySourceCutError):
            runs._has_relevant_source_change(connection, frontier, (subject,), current_frontier=_frontier(postgres_dsn))


@pytest.mark.parametrize("missing", ["middle", "tail", "whole_suffix"])
def test_missing_postcut_history_cannot_certify_no_relevant_change(
    compilation_system, postgres_dsn: str, missing: str
) -> None:
    from psycopg.rows import dict_row

    from onlyalpha.research.source_cut import OnlySourceCutError
    from tests.research.postgres.test_novelty_read_to_act import _frontier, _preadmit

    fixture = compilation_system
    store = handoff(fixture, postgres_dsn)
    frontier = _frontier(postgres_dsn)
    run = store.commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    runs = OnlyPostgresResearchRunStore(postgres_dsn)
    runs.commit_transition(run, run.transition(OnlyResearchRunState.CANCELLED, at=NOW))
    _preadmit(postgres_dsn, OnlyProductCommandId("00000000-0000-4000-8000-000000000954"), "a" * 64)
    current = _frontier(postgres_dsn)
    assert current == frontier + 3
    with psycopg.connect(postgres_dsn, row_factory=dict_row) as connection:
        connection.execute("SET LOCAL session_replication_role = replica")
        if missing == "middle":
            connection.execute("DELETE FROM research_source_history WHERE event_index = %s", (frontier + 2,))
        elif missing == "tail":
            connection.execute("DELETE FROM research_source_history WHERE event_index = %s", (current,))
        else:
            connection.execute("DELETE FROM research_source_history WHERE event_index > %s", (frontier,))
    with psycopg.connect(postgres_dsn, row_factory=dict_row) as connection:
        with pytest.raises(OnlySourceCutError, match="SOURCE_CUT_JOURNAL_GAP"):
            runs._has_relevant_source_change(connection, frontier, ("4" * 64,), current_frontier=current)


@pytest.mark.parametrize("mutation", ["relation_missing", "compilation", "queue", "run_missing", "receipt_missing"])
def test_corrupt_consumed_authority_is_not_absence_or_replay(
    compilation_system, postgres_dsn: str, mutation: str
) -> None:
    fixture = compilation_system
    store = handoff(fixture, postgres_dsn)
    run = store.commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    with psycopg.connect(postgres_dsn) as connection:
        # Explicit privileged corruption injection; production constraints/triggers stay enabled.
        connection.execute("SET LOCAL session_replication_role = replica")
        if mutation == "relation_missing":
            connection.execute("DELETE FROM chart_calculation_run_admission")
        elif mutation == "compilation":
            connection.execute("UPDATE chart_calculation_run_admission SET compilation_fingerprint = %s", ("f" * 64,))
        elif mutation == "queue":
            connection.execute("UPDATE chart_calculation_run_admission SET queued_at = queued_at + interval '1 second'")
        elif mutation == "run_missing":
            connection.execute("DELETE FROM research_run")
        else:
            connection.execute("DELETE FROM product_command_receipt")
    with pytest.raises(ValueError):
        store.load_verified(fixture.operation)
    with pytest.raises(ValueError):
        store.commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    with pytest.raises(ValueError):
        OnlyPostgresChartCalculationAdmissionStore(postgres_dsn).load_verified(fixture.operation.operation_id)
    if mutation != "run_missing":
        from onlyalpha.research.run.errors import OnlyResearchRunIntegrityError

        with pytest.raises((ValueError, OnlyResearchRunIntegrityError)):
            OnlyPostgresResearchRunStore(postgres_dsn).load(run.run_id)


@pytest.mark.parametrize("insert_after_cut", [False, True])
def test_chart_does_not_block_novelty_inflight_or_postcut_freshness(
    compilation_system, postgres_dsn: str, insert_after_cut: bool
) -> None:
    from tests.research.postgres.test_novelty_read_to_act import _admission, _frontier, _preadmit
    from tests.research.postgres.test_postgres_authority import _create_receipt, _queued

    fixture = compilation_system
    chart = handoff(fixture, postgres_dsn)
    command = OnlyProductCommandId("00000000-0000-4000-8000-000000000941")
    generic = _queued("00000000-0000-4000-8000-000000000942")
    _preadmit(postgres_dsn, command, "a" * 64)
    if not insert_after_cut:
        chart.commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    frontier = _frontier(postgres_dsn)
    if insert_after_cut:
        chart.commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    runs = OnlyPostgresResearchRunStore(postgres_dsn)
    receipt = _create_receipt(command, generic, "a" * 64)
    assert (
        runs._create_queued_with_verified_novelty_admission(
            generic, receipt, _admission(command, "a" * 64, generic), expected_source_frontier=frontier
        )
        == receipt
    )
    assert runs.load(generic.run_id) == generic


@pytest.mark.parametrize("origin", ["GENERAL", "PRIVATE_STRATEGY"])
def test_chart_oldest_queue_does_not_starve_legacy_claim(
    compilation_system, postgres_dsn: str, tmp_path, origin: str
) -> None:
    from onlyalpha.research.run.model import OnlyResearchOriginKind
    from tests.research.postgres.test_postgres_authority import _queued
    from tests.support.research_run_seeder import OnlyPostgresResearchRunSeeder

    fixture = compilation_system
    chart = handoff(fixture, postgres_dsn)
    chart_run = chart.commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    composition_fingerprint = None
    if origin == "PRIVATE_STRATEGY":
        from pathlib import Path

        from onlyalpha.persistence.postgres.private_asset_store import OnlyPostgresPrivateAssetStore
        from onlyalpha.persistence.postgres.private_strategy_research_composition_store import (
            OnlyPostgresPrivateStrategyResearchCompositionStore,
        )
        from onlyalpha.quant_assets import (
            OnlyPrivateAssetExampleImporterV1,
            OnlyPrivateStrategyResearchComposer,
            only_load_private_asset_example_bundle,
        )
        from tests.research.postgres.test_private_strategy_production_authority import (
            _generation,
            _simple_momentum_context,
        )

        assets = OnlyPostgresPrivateAssetStore(postgres_dsn)
        imported = OnlyPrivateAssetExampleImporterV1(assets).import_bundles(
            tuple(
                only_load_private_asset_example_bundle(Path("examples/private-assets") / kind / "simple_momentum")
                for kind in ("factor", "strategy")
            )
        )
        generation, _ = _generation(
            assets,
            imported["factor.simple_momentum"],
            tmp_path / "strategy-authoring",
            provider_id="candidate.private.simple_momentum.claim",
        )
        context = _simple_momentum_context()
        composition = (
            OnlyPrivateStrategyResearchComposer(assets, generation.catalog)
            .compose(imported["strategy.simple_momentum"], context)
            .composition
        )
        OnlyPostgresPrivateStrategyResearchCompositionStore(postgres_dsn).put(composition, context)
        composition_fingerprint = composition.composition_fingerprint
    generic = _queued("00000000-0000-4000-8000-000000000943")
    generic = replace(
        generic,
        queued_at=NOW + timedelta(minutes=1),
        origin_kind=OnlyResearchOriginKind(origin),
        strategy_research_composition_fingerprint=composition_fingerprint,
    )
    OnlyPostgresResearchRunSeeder(postgres_dsn).seed_queued(generic)
    execution = OnlyPostgresResearchExecutionStore(postgres_dsn)
    claim = execution.claim_next(
        worker_instance_id=OnlyResearchWorkerInstanceId.new(),
        attempt_id=OnlyResearchRunAttemptId.new(),
        lease_duration=timedelta(seconds=60),
        max_attempts=3,
        run_started_at=NOW + timedelta(minutes=2),
        eligible_run_ids=(chart_run.run_id.value, generic.run_id.value),
    )
    assert claim is not None and claim.attempt.run_id == generic.run_id
    assert OnlyPostgresResearchRunStore(postgres_dsn).load(chart_run.run_id) == chart_run


@pytest.mark.parametrize("draining", [False, True])
def test_real_runtime_lock_covers_commit_and_retired_exact_replay(
    postgres_dsn: str, tmp_path, monkeypatch: pytest.MonkeyPatch, draining: bool
) -> None:
    import subprocess
    import sys
    from types import SimpleNamespace

    from onlyalpha.application.chart_calculation_run_admission import OnlyChartCalculationRunAdmissionService
    from onlyalpha.persistence.postgres.chart_calculation_compilation_store import (
        OnlyPostgresChartCalculationCompilationStore,
    )
    from onlyalpha.persistence.postgres.research_chart_calculation_run_admission_store import (
        OnlyPostgresChartCalculationRunAdmissionStore,
    )
    from tests.application.test_chart_calculation_compilation import compilation
    from tests.research.postgres.test_chart_calculation_preparation import (
        WORKER,
        chart_runtime_registry,
        prepared_system,
    )

    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    runtime, generation, other = chart_runtime_registry(system, tmp_path / "runtime")
    system.service._runtime = runtime
    ready = system.service.prepare(
        system.operation, worker_id=WORKER, runtime_generation_fingerprint=generation, occurred_at=NOW
    )
    frozen = compilation(SimpleNamespace(operation=system.operation, preparation=ready))
    compiled = OnlyPostgresChartCalculationCompilationStore(postgres_dsn)
    compiled.commit_or_replay(system.operation, ready, frozen)
    if draining:
        runtime.activate_for_new_work(expected_current=generation, target=other, actor="human", occurred_at=NOW)
    store = OnlyPostgresChartCalculationRunAdmissionStore(postgres_dsn, runtime_generations=runtime)
    connect = psycopg.connect
    commits = []

    class CommitProof:
        def __init__(self, connection):
            self.connection = connection
            self.wrote = False

        def execute(self, query, *args):
            if "INSERT INTO chart_calculation_run_admission" in str(query):
                self.wrote = True
            return self.connection.execute(query, *args)

        def commit(self):
            if self.wrote:
                code = "import fcntl, os, sys\nfd=os.open(sys.argv[1],os.O_RDWR)\ntry: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)\nexcept BlockingIOError: print('COMMIT_FENCED')\nelse: raise AssertionError('runtime lock not held through commit')\n"
                proof = subprocess.run(
                    [sys.executable, "-c", code, str(runtime.root / ".generation-authority.lock")],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                assert proof.stdout.strip() == "COMMIT_FENCED"
                commits.append(True)
            return self.connection.commit()

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

    with monkeypatch.context() as fault:
        fault.setattr(psycopg, "connect", lambda *args, **kwargs: CommitProof(connect(*args, **kwargs)))
        run = store.commit_or_replay(system.operation, frozen, queued_at=NOW)
    assert commits == [True]
    runs = OnlyPostgresResearchRunStore(postgres_dsn)
    cancelled = runs.commit_transition(run, run.transition(OnlyResearchRunState.CANCELLED, at=NOW))
    runtime.release_work(run.run_id.value, actor="human", occurred_at=NOW)
    if not draining:
        runtime.activate_for_new_work(expected_current=generation, target=other, actor="human", occurred_at=NOW)
    runtime.retire(generation, actor="human", occurred_at=NOW)
    service = OnlyChartCalculationRunAdmissionService(
        preparations=system.adapter,
        compilations=compiled,
        datasets=system.dataset,
        materializations=system.dataset,
        runtime_generations=runtime,
        runs=store,
    )
    ledger = (runtime.root / "generation-events.jsonl").read_bytes()
    assert service.admit(system.operation, queued_at=NOW + timedelta(minutes=1)) == cancelled
    assert (runtime.root / "generation-events.jsonl").read_bytes() == ledger


def test_two_processes_commit_one_reserved_occurrence(
    postgres_dsn: str, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess
    import sys
    from types import SimpleNamespace

    from onlyalpha.persistence.postgres.chart_calculation_compilation_store import (
        OnlyPostgresChartCalculationCompilationStore,
    )
    from tests.application.test_chart_calculation_compilation import compilation
    from tests.research.postgres.test_chart_calculation_preparation import (
        WORKER,
        chart_runtime_registry,
        prepared_system,
    )

    system = prepared_system(postgres_dsn, tmp_path, monkeypatch)
    runtime, generation, _ = chart_runtime_registry(system, tmp_path / "runtime")
    system.service._runtime = runtime
    ready = system.service.prepare(
        system.operation, worker_id=WORKER, runtime_generation_fingerprint=generation, occurred_at=NOW
    )
    frozen = compilation(SimpleNamespace(operation=system.operation, preparation=ready))
    OnlyPostgresChartCalculationCompilationStore(postgres_dsn).commit_or_replay(system.operation, ready, frozen)
    clients = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.runtime_support.chart_run_admission_client",
                str(runtime.root),
                system.operation.operation_id.value,
                (NOW + timedelta(seconds=index)).isoformat(),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(2)
    ]
    try:
        for client in clients:
            assert client.stdout.readline().strip() == "READY"
        for client in clients:
            client.stdin.write("COMMIT\n")
            client.stdin.flush()
        outputs = [client.communicate(timeout=60) for client in clients]
        assert [client.returncode for client in clients] == [0, 0], outputs
        assert (
            outputs[0][0]
            == outputs[1][0]
            == system.operation.reserved_run_id.value + ":" + frozen.compilation_fingerprint + "\n"
        )
    finally:
        for client in clients:
            if client.poll() is None:
                client.kill()
            client.wait()
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_run").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM chart_calculation_run_admission").fetchone() == (1,)


@pytest.mark.parametrize("expired", [False, True])
def test_legacy_mutation_paths_cannot_touch_injected_chart_attempt(
    compilation_system, postgres_dsn: str, expired: bool
) -> None:
    from onlyalpha.research.execution.errors import OnlyResearchExecutionOwnershipLostError
    from onlyalpha.research.execution.model import OnlyResearchExecutionClaim
    from onlyalpha.research.execution.policy import OnlyResearchRetryDecision
    from onlyalpha.research.execution.reconciliation import (
        OnlyResearchSemanticCompletionInspection,
        OnlyResearchSemanticCompletionStatus,
    )
    from onlyalpha.research.run.model import OnlyResearchRunFailure, OnlyResearchRunFailurePhase

    fixture = compilation_system
    store = handoff(fixture, postgres_dsn)
    run = store.commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    attempt_id, worker_id = OnlyResearchRunAttemptId.new(), OnlyResearchWorkerInstanceId.new()
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "INSERT INTO research_run_attempt (attempt_id, run_id, attempt_number, state, worker_instance_id, claimed_at, last_heartbeat_at, lease_expires_at) VALUES (%s,%s,1,'ACTIVE',%s,clock_timestamp()-interval '2 minutes',clock_timestamp()-interval '2 minutes',clock_timestamp()+%s)",
            (attempt_id.value, run.run_id.value, worker_id.value, timedelta(minutes=-1 if expired else 1)),
        )
    execution = OnlyPostgresResearchExecutionStore(postgres_dsn)
    claim = OnlyResearchExecutionClaim(execution.load_attempt(attempt_id))
    before = authority_facts(postgres_dsn)
    assert execution.expire_next(max_attempts=1, run_finished_at=NOW, eligible_run_ids=(run.run_id.value,)) is None
    assert execution.load_cancellation_recovery_candidate((run.run_id.value,)) is None
    failure = OnlyResearchRunFailure(OnlyResearchRunFailurePhase.OPERATIONAL, "INJECTED", "test")
    actions = [
        lambda: execution.heartbeat(
            attempt_id=attempt_id, worker_instance_id=worker_id, lease_duration=timedelta(minutes=1)
        ),
        lambda: execution.fail(
            claim=claim, run_finished_at=NOW, failure=failure, retry_decision=OnlyResearchRetryDecision.FINAL_FAIL
        ),
        lambda: execution.cancel(claim=claim, run_finished_at=NOW),
        lambda: execution.complete(
            claim=claim,
            run_finished_at=NOW,
            research_result_fingerprint="a" * 64,
            artifact_content_fingerprint="b" * 64,
            calculation_execution_evidence_fingerprints=("c" * 64,),
        ),
    ]
    for action in actions:
        with pytest.raises(OnlyResearchExecutionOwnershipLostError):
            action()
    from copy import copy

    malformed = copy(run)
    object.__setattr__(malformed, "state", OnlyResearchRunState.CANCEL_REQUESTED)
    with pytest.raises(OnlyResearchExecutionOwnershipLostError, match="RESEARCH_WORKER_ORIGIN_NOT_ELIGIBLE"):
        execution.reconcile_cancellation(
            expected=malformed,
            run_finished_at=NOW,
            inspection=OnlyResearchSemanticCompletionInspection(OnlyResearchSemanticCompletionStatus.ABSENT),
        )
    assert authority_facts(postgres_dsn) == before
