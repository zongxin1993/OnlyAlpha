"""Actual PG18 narrow entry tests; fixture EXECUTE grants are not rollout."""

from __future__ import annotations

import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from onlyalpha.canonical import only_canonical_json
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority, OnlyPostgresSchemaVerifier
from onlyalpha.persistence.postgres.research_chart_native_execution_store import OnlyPostgresChartNativeExecutionStore
from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore
from onlyalpha.research.execution.errors import (
    OnlyResearchExecutionOwnershipLostError,
    OnlyResearchExecutionStoreUnavailableError,
)
from onlyalpha.research.execution.model import OnlyResearchRunAttemptId, OnlyResearchWorkerInstanceId
from onlyalpha.research.run.errors import OnlyPostgresMigrationIntegrityError, OnlyPostgresSchemaIncompatibleError
from onlyalpha.research.run.model import OnlyResearchRunState
from tests.application.test_chart_calculation_admission import NOW
from tests.research.postgres.migration_support import copy_migrations_through
from tests.research.postgres.test_chart_calculation_compilation import compilation_system as compilation_system
from tests.research.postgres.test_chart_calculation_run_admission import handoff
from tests.research.postgres.test_chart_native_publication_permissions import runtime_login, snapshot

pytestmark = [pytest.mark.integration, pytest.mark.postgres]
_MIGRATION = "0050_chart_native_execution_entry"
_FORWARD = (
    _MIGRATION,
    "0051_watchlist_configuration",
    "0052_watchlist_member_sources",
    "0053_backtest_native_specification",
    "0054_default_workspace_configuration",
)
_CLAIM = "public.chart_native_claim_v1(integer,uuid,uuid,bigint,text,text,text,uuid,uuid,interval,integer,timestamptz)"
_HEARTBEAT = "public.chart_native_heartbeat_v1(integer,uuid,uuid,bigint,text,text,text,uuid,uuid,integer,interval)"


@contextmanager
def sql_consumer_login(dsn: str):
    # Explicit test-local operator provisioning of just two real SQL operations.
    # Migration grants neither to any runtime role. No trigger/CHECK is disabled.
    with runtime_login(dsn, "onlyalpha_chart_execution_controller") as login:
        name = conninfo_to_dict(login)["user"]
        with psycopg.connect(dsn) as admin:
            admin.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(name)))
            for function in (_CLAIM, _HEARTBEAT):
                admin.execute(sql.SQL("GRANT EXECUTE ON FUNCTION " + function + " TO {}").format(sql.Identifier(name)))
        yield login


def context(fixture):
    return (
        1,
        fixture.operation.operation_id.value,
        fixture.operation.reserved_run_id.value,
        0,
        fixture.compilation.compilation_fingerprint,
        fixture.compilation.runtime_generation_fingerprint,
        only_canonical_json(fixture.compilation.to_dict()),
    )


def claim_sql(connection, fixture, *, parameters=None):
    parameters = parameters or (*context(fixture), str(uuid.uuid4()), str(uuid.uuid4()), timedelta(minutes=2), 3, NOW)
    return connection.execute(
        "SELECT public.chart_native_claim_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", parameters
    ).fetchone()[0]


@pytest.mark.parametrize("group", ["onlyalpha_chart_input_reader", "onlyalpha_chart_execution_controller"])
def test_migration_grants_no_runtime_entry_or_executor_membership(postgres_dsn: str, group: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    with runtime_login(postgres_dsn, group) as dsn:
        with psycopg.connect(dsn, autocommit=True) as connection:
            for function in (_CLAIM, _HEARTBEAT):
                assert connection.execute(
                    "SELECT has_function_privilege(current_user,p.oid,'EXECUTE') FROM pg_proc p "
                    "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname=%s",
                    (function.split("(")[0].removeprefix("public."),),
                ).fetchone() == (False,)
            for statement in (
                "SET ROLE onlyalpha_chart_sql_executor",
                "SET session_replication_role=replica",
                "UPDATE public.research_run SET state='RUNNING'",
                "SELECT public.chart_native_context_v1(NULL,NULL,NULL,NULL,NULL)",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(statement)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM pg_auth_members WHERE roleid=(SELECT oid FROM pg_roles WHERE rolname='onlyalpha_chart_sql_executor') OR member=(SELECT oid FROM pg_roles WHERE rolname='onlyalpha_chart_sql_executor')"
        ).fetchone() == (0,)
        assert (
            connection.execute(
                "SELECT rolcanlogin,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls FROM pg_roles WHERE rolname='onlyalpha_chart_sql_executor'"
            ).fetchone()
            == (False,) * 7
        )
        assert connection.execute(
            "SELECT count(*) FROM pg_proc WHERE proname IN ('chart_native_claim_v1','chart_native_heartbeat_v1') AND prosecdef AND proconfig=ARRAY['search_path=pg_catalog'] AND proowner=(SELECT oid FROM pg_roles WHERE rolname='onlyalpha_chart_sql_executor')"
        ).fetchone() == (2,)


def test_real_execute_only_login_commits_original_claim_and_history(compilation_system, postgres_dsn: str) -> None:
    fixture = compilation_system
    queued = handoff(fixture, postgres_dsn).commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    with sql_consumer_login(postgres_dsn) as login:
        with psycopg.connect(login) as connection:
            payload = claim_sql(connection, fixture)
            assert payload["schema_version"] == 1
            assert payload["run"]["run_id"] == queued.run_id.value
            assert payload["run"]["state"] == "RUNNING" and payload["run"]["revision"] == 1
            assert payload["attempt"]["attempt_number"] == 1 and payload["attempt"]["state"] == "ACTIVE"
            assert payload["attempt"]["run_id"] == queued.run_id.value
        with psycopg.connect(login, autocommit=True) as connection:
            for table in ("research_run", "research_run_attempt", "research_source_history"):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(sql.SQL("DELETE FROM public.{}").format(sql.Identifier(table)))
    running = OnlyPostgresResearchRunStore(postgres_dsn).load(queued.run_id)
    assert running == queued.transition(OnlyResearchRunState.RUNNING, at=NOW)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            "SELECT source_row->>'state' FROM research_source_history WHERE source_family='RESEARCH_RUN' AND native_locator=%s ORDER BY event_index",
            (queued.run_id.value,),
        ).fetchall() == [("QUEUED",), ("RUNNING",)]
        assert connection.execute(
            "SELECT source_row->>'state' FROM research_source_history WHERE source_family='RESEARCH_ATTEMPT'"
        ).fetchall() == [("ACTIVE",)]


@pytest.mark.parametrize(
    "mutation",
    [
        "operation",
        "run",
        "compilation",
        "generation",
        "whole_compilation",
        "null_version",
        "negative_lease",
        "zero_budget",
        "revision",
    ],
)
def test_sql_relation_and_request_mutations_publish_nothing(
    compilation_system, postgres_dsn: str, mutation: str
) -> None:
    fixture = compilation_system
    handoff(fixture, postgres_dsn).commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    parameters = [*context(fixture), str(uuid.uuid4()), str(uuid.uuid4()), timedelta(minutes=2), 3, NOW]
    replacements = {
        "operation": (1, str(uuid.uuid4())),
        "run": (2, str(uuid.uuid4())),
        "compilation": (4, "f" * 64),
        "generation": (5, "f" * 64),
        "whole_compilation": (6, "{}"),
        "null_version": (0, None),
        "negative_lease": (9, timedelta(seconds=-1)),
        "zero_budget": (10, 0),
        "revision": (3, 4),
    }
    index, value = replacements[mutation]
    parameters[index] = value
    before = snapshot(postgres_dsn)
    with sql_consumer_login(postgres_dsn) as login:
        with pytest.raises(psycopg.Error, match="CHART_NATIVE_(SQL_REQUEST_INVALID|OPERATIONAL_RELATION_INVALID)"):
            with psycopg.connect(login) as connection:
                claim_sql(connection, fixture, parameters=parameters)
    assert snapshot(postgres_dsn) == before


def test_two_real_connections_cannot_claim_two_active_attempts(compilation_system, postgres_dsn: str) -> None:
    fixture = compilation_system
    handoff(fixture, postgres_dsn).commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    barrier = Barrier(2)
    with sql_consumer_login(postgres_dsn) as login:

        def claim():
            with psycopg.connect(login) as connection:
                barrier.wait(timeout=30)
                return claim_sql(connection, fixture)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim) for _ in range(2)]
            results = [future.result(timeout=30) for future in futures]
    assert sum(item is not None for item in results) == 1
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT attempt_number,state FROM research_run_attempt").fetchall() == [(1, "ACTIVE")]


def test_queued_cancel_and_claim_row_exclusion(compilation_system, postgres_dsn: str) -> None:
    fixture = compilation_system
    queued = handoff(fixture, postgres_dsn).commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    with sql_consumer_login(postgres_dsn) as login:
        with psycopg.connect(postgres_dsn) as cancel:
            cancel.execute("LOCK TABLE public.research_run IN ROW EXCLUSIVE MODE")
            cancel.execute("SELECT run_id FROM public.research_run WHERE run_id=%s FOR UPDATE", (queued.run_id.value,))
            with psycopg.connect(login) as worker:
                assert claim_sql(worker, fixture) is None  # Actual SKIP LOCKED.
            cancel.execute(
                "UPDATE public.research_run SET state='CANCELLED',revision=1,finished_at=%s WHERE run_id=%s",
                (NOW, queued.run_id.value),
            )
        with psycopg.connect(login) as worker:
            assert claim_sql(worker, fixture) is None
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_run_attempt").fetchone() == (0,)


def test_claim_rollback_and_t1_table_exclusion(compilation_system, postgres_dsn: str) -> None:
    fixture = compilation_system
    queued = handoff(fixture, postgres_dsn).commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    before = snapshot(postgres_dsn)
    with sql_consumer_login(postgres_dsn) as login:
        with psycopg.connect(login) as worker:
            assert claim_sql(worker, fixture) is not None
            with psycopg.connect(postgres_dsn) as t1:
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    t1.execute("LOCK TABLE public.research_run IN SHARE MODE NOWAIT")
            worker.rollback()
    assert snapshot(postgres_dsn) == before
    assert OnlyPostgresResearchRunStore(postgres_dsn).load(queued.run_id) == queued


def test_temp_shadow_cannot_redirect_authoritative_source_history(compilation_system, postgres_dsn: str) -> None:
    fixture = compilation_system
    handoff(fixture, postgres_dsn).commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    with sql_consumer_login(postgres_dsn) as login:
        with psycopg.connect(login) as worker:
            worker.execute("CREATE TEMP TABLE research_run (run_id uuid)")
            worker.execute("CREATE TEMP TABLE research_source_history_frontier (singleton boolean,last_index bigint)")
            worker.execute("INSERT INTO research_source_history_frontier VALUES (true,999)")
            worker.execute("CREATE TEMP TABLE research_source_history (event_index bigint)")
            assert claim_sql(worker, fixture) is not None
            assert worker.execute("SELECT last_index FROM pg_temp.research_source_history_frontier").fetchone() == (
                999,
            )
            assert worker.execute("SELECT count(*) FROM pg_temp.research_source_history").fetchone() == (0,)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute(
            "SELECT count(*) FROM public.research_source_history WHERE source_family='RESEARCH_ATTEMPT'"
        ).fetchone() == (1,)


@pytest.mark.parametrize("mutation", ["none", "worker", "number", "revision", "generation", "expired"])
def test_heartbeat_rechecks_exact_owner_revision_generation_and_server_lease(
    compilation_system, postgres_dsn: str, mutation: str
) -> None:
    fixture = compilation_system
    run = handoff(fixture, postgres_dsn).commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    with sql_consumer_login(postgres_dsn) as login:
        with psycopg.connect(login) as worker:
            payload = claim_sql(worker, fixture)
        params = [
            *context(fixture),
            payload["attempt"]["attempt_id"],
            payload["attempt"]["worker_instance_id"],
            1,
            timedelta(minutes=3),
        ]
        params[3] = 1
        if mutation == "worker":
            params[8] = str(uuid.uuid4())
        elif mutation == "number":
            params[9] = 2
        elif mutation == "revision":
            params[3] = 2
        elif mutation == "generation":
            params[5] = "f" * 64
        elif mutation == "expired":
            # Privileged clock-boundary fault injection for a NEGATIVE result.
            # The positive Claim above went through the real guarded entry.
            with psycopg.connect(postgres_dsn) as admin:
                admin.execute("SET LOCAL session_replication_role=replica")
                admin.execute(
                    "UPDATE public.research_run_attempt SET claimed_at=clock_timestamp()-interval '2 minutes',"
                    "last_heartbeat_at=clock_timestamp()-interval '2 minutes',"
                    "lease_expires_at=clock_timestamp()-interval '1 minute' WHERE run_id=%s",
                    (run.run_id.value,),
                )
        with psycopg.connect(login) as heartbeat:
            if mutation == "none":
                result = heartbeat.execute(
                    "SELECT public.chart_native_heartbeat_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", params
                ).fetchone()[0]
                assert result["attempt"]["attempt_id"] == payload["attempt"]["attempt_id"]
                assert result["run"]["revision"] == 1
            else:
                with pytest.raises(psycopg.Error, match="CHART_NATIVE_(OWNERSHIP_LOST|OPERATIONAL_RELATION_INVALID)"):
                    heartbeat.execute(
                        "SELECT public.chart_native_heartbeat_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", params
                    )


def test_original_runtime_shared_proof_spans_actual_claim_commit(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    from onlyalpha.persistence.postgres.research_chart_calculation_run_admission_store import (
        OnlyPostgresChartCalculationRunAdmissionStore,
    )

    OnlyPostgresChartCalculationRunAdmissionStore(postgres_dsn, runtime_generations=runtime).commit_or_replay(
        system.operation, frozen, queued_at=NOW
    )
    connect = psycopg.connect
    commits = []

    class CommitProof:
        def __init__(self, connection):
            self.connection = connection
            self.wrote = False

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def execute(self, query, *args):
            if "SELECT public.chart_native_claim_v1" in str(query):
                self.wrote = True
            return self.connection.execute(query, *args)

        def commit(self):
            if self.wrote:
                code = "import fcntl,os,sys\nfd=os.open(sys.argv[1],os.O_RDWR)\ntry: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)\nexcept BlockingIOError: print('COMMIT_FENCED')\nelse: raise AssertionError('Work proof released before PG COMMIT')\n"
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

    with (
        sql_consumer_login(postgres_dsn) as login,
        runtime_login(postgres_dsn, "onlyalpha_chart_input_reader") as reader,
    ):
        store = OnlyPostgresChartNativeExecutionStore(login, reader_dsn=reader, runtime_generations=runtime)
        with monkeypatch.context() as patch:
            patch.setattr(psycopg, "connect", lambda *a, **kw: CommitProof(connect(*a, **kw)))
            claim = store.claim(
                system.operation,
                frozen,
                expected_revision=0,
                attempt_id=OnlyResearchRunAttemptId.new(),
                worker_instance_id=OnlyResearchWorkerInstanceId.new(),
                lease_duration=timedelta(minutes=2),
                max_attempts=3,
                run_started_at=NOW,
            )
    assert claim is not None and claim.attempt.run_id == system.operation.reserved_run_id
    assert commits == [True]
    assert runtime.require_work_binding_evidence(system.operation.reserved_run_id.value).active


def test_raw_table_grants_and_guc_cannot_impersonate_sql_executor(compilation_system, postgres_dsn: str) -> None:
    fixture = compilation_system
    run = handoff(fixture, postgres_dsn).commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    with runtime_login(postgres_dsn, "onlyalpha_chart_input_reader") as login:
        name = conninfo_to_dict(login)["user"]
        with psycopg.connect(postgres_dsn) as admin:
            admin.execute(sql.SQL("GRANT UPDATE ON public.research_run TO {}").format(sql.Identifier(name)))
        with psycopg.connect(login, autocommit=True) as connection:
            connection.execute("SET onlyalpha.chart_authorized='true'")
            with pytest.raises(psycopg.Error, match="CHART_NATIVE_EXECUTION_NOT_ENABLED"):
                connection.execute(
                    "UPDATE public.research_run SET state='RUNNING',revision=1,started_at=%s WHERE run_id=%s",
                    (NOW, run.run_id.value),
                )
    assert OnlyPostgresResearchRunStore(postgres_dsn).load(run.run_id) == run


@pytest.mark.parametrize("ack", ["committed", "rollback", "silent_rollback"])
def test_connection_claim_requires_exact_postcommit_ack(
    compilation_system, postgres_dsn: str, monkeypatch: pytest.MonkeyPatch, ack: str
) -> None:
    fixture = compilation_system
    run = handoff(fixture, postgres_dsn).commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    connect = psycopg.connect
    faults = []

    class CommitFault:
        def __init__(self, connection):
            self.connection = connection
            self.claimed = False

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def execute(self, query, *args):
            if "SELECT public.chart_native_claim_v1" in str(query):
                self.claimed = True
            return self.connection.execute(query, *args)

        def commit(self):
            if self.claimed and not faults:
                faults.append(ack)
                if ack == "committed":
                    self.connection.commit()
                else:
                    self.connection.rollback()
                if ack != "silent_rollback":
                    raise psycopg.OperationalError("injected Claim ACK loss")
                return None
            return self.connection.commit()

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

    with sql_consumer_login(postgres_dsn) as login:
        store = OnlyPostgresChartNativeExecutionStore(
            login, reader_dsn=postgres_dsn, runtime_generations=fixture.system.runtime
        )
        monkeypatch.setattr(psycopg, "connect", lambda *a, **kw: CommitFault(connect(*a, **kw)))
        kwargs = dict(
            expected_revision=0,
            attempt_id=OnlyResearchRunAttemptId.new(),
            worker_instance_id=OnlyResearchWorkerInstanceId.new(),
            lease_duration=timedelta(minutes=2),
            max_attempts=3,
            run_started_at=NOW,
        )
        if ack == "committed":
            claim = store.claim(fixture.operation, fixture.compilation, **kwargs)
            assert claim is not None and claim.attempt.run_id == run.run_id
        else:
            with pytest.raises(
                (OnlyResearchExecutionStoreUnavailableError, OnlyResearchExecutionOwnershipLostError),
                match="COMMIT_UNKNOWN",
            ):
                store.claim(fixture.operation, fixture.compilation, **kwargs)
            assert OnlyPostgresResearchRunStore(postgres_dsn).load(run.run_id) == run
    assert faults == [ack]
    fixture.system.runtime.release_work.assert_not_called()


@pytest.mark.parametrize("fault", ["ddl", "ledger"])
@pytest.mark.parametrize("executor_kind", ["fresh", "preexisting"])
def test_forward_entry_migration_is_atomic_and_previous_reader_reports_ahead(
    postgres_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    executor_kind: str,
    request: pytest.FixtureRequest,
) -> None:
    if executor_kind == "fresh":
        postgres_dsn = request.getfixturevalue("isolated_postgres_cluster")
    reference = tmp_path / "previous"
    reference.mkdir()
    copy_migrations_through(reference, "0049_chart_native_publication_permissions")
    OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=reference).migrate()
    with psycopg.connect(postgres_dsn) as connection:
        if executor_kind == "fresh":
            assert (
                connection.execute("SELECT 1 FROM pg_roles WHERE rolname='onlyalpha_chart_sql_executor'").fetchone()
                is None
            )
        elif (
            connection.execute("SELECT 1 FROM pg_roles WHERE rolname='onlyalpha_chart_sql_executor'").fetchone() is None
        ):
            connection.execute("CREATE ROLE onlyalpha_chart_sql_executor NOLOGIN NOINHERIT")
    before = snapshot(postgres_dsn), executor_inventory(postgres_dsn)
    connect = psycopg.connect
    injected = []

    class DdlFault:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def execute(self, query, params=None):
            if fault == "ddl" and "CREATE FUNCTION public.chart_native_claim_v1" in str(query):
                self.connection.execute(query, params)
                injected.append(fault)
                return self.connection.execute("SELECT 1/0")
            if fault == "ledger" and "INSERT INTO onlyalpha_schema_migration" in str(query) and params[0] == _MIGRATION:
                injected.append(fault)
                return self.connection.execute("SELECT 1/0")
            return self.connection.execute(query, params)

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

    with monkeypatch.context() as patch:
        patch.setattr(psycopg, "connect", lambda *a, **kw: DdlFault(connect(*a, **kw)))
        with pytest.raises(OnlyPostgresMigrationIntegrityError):
            OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    assert injected == [fault]
    assert (snapshot(postgres_dsn), executor_inventory(postgres_dsn)) == before
    with connect(postgres_dsn) as connection:
        assert connection.execute("SELECT to_regprocedure(%s)", (_CLAIM,)).fetchone() == (None,)
        assert connection.execute(
            "SELECT count(*) FROM pg_auth_members WHERE roleid=(SELECT oid FROM pg_roles WHERE rolname='onlyalpha_chart_sql_executor')"
        ).fetchone() == (0,)
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == _FORWARD
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == ()
    with pytest.raises(OnlyPostgresSchemaIncompatibleError, match="AHEAD"):
        OnlyPostgresSchemaVerifier(postgres_dsn, migration_root=reference).assert_compatible()


@pytest.mark.parametrize("scope", ["global", "schema"])
def test_creator_named_default_execute_grants_cannot_open_entry(postgres_dsn: str, tmp_path: Path, scope: str) -> None:
    reference = tmp_path / "previous"
    reference.mkdir()
    copy_migrations_through(reference, "0049_chart_native_publication_permissions")
    OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=reference).migrate()
    with runtime_login(postgres_dsn, "onlyalpha_chart_execution_controller") as login:
        name = conninfo_to_dict(login)["user"]
        schema = " IN SCHEMA public" if scope == "schema" else ""
        statement = sql.SQL("ALTER DEFAULT PRIVILEGES" + schema + " GRANT EXECUTE ON FUNCTIONS TO {}").format(
            sql.Identifier(name)
        )
        with psycopg.connect(postgres_dsn) as admin:
            admin.execute(statement)
        before = snapshot(postgres_dsn), executor_inventory(postgres_dsn)
        try:
            with pytest.raises(OnlyPostgresMigrationIntegrityError) as caught:
                OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
            assert "CHART_NATIVE_SQL_ENTRY_ACL_UNSAFE" in str(caught.value.__cause__)
            assert (snapshot(postgres_dsn), executor_inventory(postgres_dsn)) == before
            with psycopg.connect(postgres_dsn) as admin:
                assert admin.execute("SELECT to_regprocedure(%s)", (_CLAIM,)).fetchone() == (None,)
        finally:
            with psycopg.connect(postgres_dsn) as admin:
                admin.execute(
                    sql.SQL("ALTER DEFAULT PRIVILEGES" + schema + " REVOKE EXECUTE ON FUNCTIONS FROM {}").format(
                        sql.Identifier(name)
                    )
                )
        assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == _FORWARD


def executor_inventory(dsn: str):
    """Bounded role/ACL/guard inventory; no stored password material."""
    with psycopg.connect(dsn) as connection:
        return (
            connection.execute(
                "SELECT oid,rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,rolreplication,rolbypassrls,rolconnlimit,rolvaliduntil::text,rolpassword IS NOT NULL FROM pg_authid WHERE rolname='onlyalpha_chart_sql_executor'"
            ).fetchall(),
            connection.execute(
                "SELECT row_to_json(d)::text FROM pg_shdepend d WHERE refclassid='pg_authid'::regclass AND refobjid=(SELECT oid FROM pg_roles WHERE rolname='onlyalpha_chart_sql_executor') ORDER BY row_to_json(d)::text"
            ).fetchall(),
            connection.execute(
                "SELECT row_to_json(m)::text FROM pg_auth_members m WHERE roleid=(SELECT oid FROM pg_roles WHERE rolname='onlyalpha_chart_sql_executor') OR member=(SELECT oid FROM pg_roles WHERE rolname='onlyalpha_chart_sql_executor') ORDER BY m.oid"
            ).fetchall(),
            connection.execute(
                "SELECT row_to_json(s)::text FROM pg_db_role_setting s WHERE setrole=(SELECT oid FROM pg_roles WHERE rolname='onlyalpha_chart_sql_executor') ORDER BY row_to_json(s)::text"
            ).fetchall(),
            connection.execute(
                "SELECT p.oid,p.proowner,p.proacl::text,pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname IN ('chart_native_context_v1','chart_native_claim_v1','chart_native_heartbeat_v1','chart_native_run_mutation_guard','chart_native_publication_attempt_guard','research_source_record','research_source_capture_change') ORDER BY p.proname"
            ).fetchall(),
            connection.execute(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='research_run_chart_capability_check'"
            ).fetchall(),
            connection.execute("SELECT row_to_json(a)::text FROM pg_default_acl a ORDER BY a.oid").fetchall(),
        )


@pytest.mark.parametrize("operation", ["claim", "heartbeat"])
def test_infinite_lease_is_rejected_without_operational_or_journal_mutation(
    compilation_system, postgres_dsn: str, operation: str
) -> None:
    fixture = compilation_system
    handoff(fixture, postgres_dsn).commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    with sql_consumer_login(postgres_dsn) as login:
        if operation == "heartbeat":
            with psycopg.connect(login) as worker:
                published = claim_sql(worker, fixture)
            params = [
                *context(fixture),
                published["attempt"]["attempt_id"],
                published["attempt"]["worker_instance_id"],
                1,
                "infinity",
            ]
            params[3] = 1
            query = "SELECT public.chart_native_heartbeat_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::interval)"
        else:
            params = [*context(fixture), str(uuid.uuid4()), str(uuid.uuid4()), "infinity", 3, NOW]
            query = "SELECT public.chart_native_claim_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::interval,%s,%s)"
        before = snapshot(postgres_dsn)
        with pytest.raises(psycopg.Error, match="CHART_NATIVE_SQL_REQUEST_INVALID"):
            with psycopg.connect(login) as connection:
                connection.execute(query, params)
        assert snapshot(postgres_dsn) == before


@pytest.mark.parametrize("mutation", ["login", "inherit", "membership", "members", "grant", "setting"])
def test_unsafe_preexisting_executor_is_rejected_without_role_repair(
    postgres_dsn: str, tmp_path: Path, mutation: str
) -> None:
    reference = tmp_path / "previous"
    reference.mkdir()
    copy_migrations_through(reference, "0049_chart_native_publication_permissions")
    OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=reference).migrate()
    statements = {
        "login": ("ALTER ROLE onlyalpha_chart_sql_executor LOGIN", "ALTER ROLE onlyalpha_chart_sql_executor NOLOGIN"),
        "inherit": (
            "ALTER ROLE onlyalpha_chart_sql_executor INHERIT",
            "ALTER ROLE onlyalpha_chart_sql_executor NOINHERIT",
        ),
        "membership": (
            "GRANT pg_read_all_data TO onlyalpha_chart_sql_executor",
            "REVOKE pg_read_all_data FROM onlyalpha_chart_sql_executor",
        ),
        "members": (
            "GRANT onlyalpha_chart_sql_executor TO onlyalpha_chart_execution_controller",
            "REVOKE onlyalpha_chart_sql_executor FROM onlyalpha_chart_execution_controller",
        ),
        "grant": (
            "GRANT SELECT ON public.product_credential TO onlyalpha_chart_sql_executor",
            "REVOKE SELECT ON public.product_credential FROM onlyalpha_chart_sql_executor",
        ),
        "setting": (
            "ALTER ROLE onlyalpha_chart_sql_executor SET client_min_messages=warning",
            "ALTER ROLE onlyalpha_chart_sql_executor RESET client_min_messages",
        ),
    }
    with psycopg.connect(postgres_dsn) as admin:
        if admin.execute("SELECT 1 FROM pg_roles WHERE rolname='onlyalpha_chart_sql_executor'").fetchone() is None:
            admin.execute("CREATE ROLE onlyalpha_chart_sql_executor NOLOGIN NOINHERIT")
        admin.execute(statements[mutation][0])
    before = snapshot(postgres_dsn), executor_inventory(postgres_dsn)
    try:
        with pytest.raises(OnlyPostgresMigrationIntegrityError) as caught:
            OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
        assert "CHART_NATIVE_SQL_EXECUTOR_UNSAFE" in str(caught.value.__cause__)
        assert (snapshot(postgres_dsn), executor_inventory(postgres_dsn)) == before
    finally:
        with psycopg.connect(postgres_dsn) as admin:
            admin.execute(statements[mutation][1])
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == _FORWARD


@pytest.mark.parametrize("missing", ["receipt", "admission", "preparation", "compilation", "consumption", "other_work"])
def test_missing_or_cross_owned_mandatory_sql_relation_is_not_a_claim(
    compilation_system, postgres_dsn: str, missing: str
) -> None:
    fixture = compilation_system
    handoff(fixture, postgres_dsn).commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    tables = {
        "receipt": "product_command_receipt",
        "admission": "product_command_admission",
        "preparation": "chart_calculation_preparation_fact",
        "compilation": "chart_calculation_compilation",
        "consumption": "chart_calculation_run_admission",
    }
    with psycopg.connect(postgres_dsn) as admin:
        # Privileged relation corruption for negative admission only; Claim
        # always uses the enabled real entry and cannot fix the corrupted owner.
        admin.execute("SET LOCAL session_replication_role=replica")
        if missing == "other_work":
            admin.execute("UPDATE public.chart_calculation_compilation SET runtime_work_id=%s", (uuid.uuid4(),))
        else:
            admin.execute(sql.SQL("DELETE FROM public.{}").format(sql.Identifier(tables[missing])))
    before = snapshot(postgres_dsn)
    with sql_consumer_login(postgres_dsn) as login:
        with pytest.raises(psycopg.Error, match="CHART_NATIVE_OPERATIONAL_RELATION_INVALID"):
            with psycopg.connect(login) as connection:
                claim_sql(connection, fixture)
    assert snapshot(postgres_dsn) == before


def test_duplicate_attempt_identity_rolls_back_second_original_run_claim(compilation_system, postgres_dsn: str) -> None:
    from onlyalpha.persistence.postgres.research_run_store import _insert_run_query
    from tests.research.postgres.test_chart_native_publication_permissions import insert_attempt
    from tests.research.postgres.test_postgres_authority import _queued

    fixture = compilation_system
    handoff(fixture, postgres_dsn).commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    legacy = _queued(str(uuid.uuid4()))
    with psycopg.connect(postgres_dsn) as admin:
        admin.execute(_insert_run_query(), OnlyPostgresResearchRunStore._values(legacy))
        existing = insert_attempt(admin, legacy.run_id.value)
    before = snapshot(postgres_dsn)
    params = [*context(fixture), str(existing), str(uuid.uuid4()), timedelta(minutes=2), 3, NOW]
    with sql_consumer_login(postgres_dsn) as login:
        with pytest.raises(psycopg.errors.UniqueViolation):
            with psycopg.connect(login) as connection:
                claim_sql(connection, fixture, parameters=params)
    assert snapshot(postgres_dsn) == before


def test_cancel_requested_heartbeat_requires_new_revision_and_never_shortens_lease(
    compilation_system, postgres_dsn: str
) -> None:
    fixture = compilation_system
    run = handoff(fixture, postgres_dsn).commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    with sql_consumer_login(postgres_dsn) as login:
        with psycopg.connect(login) as worker:
            claimed = claim_sql(worker, fixture)
        running = OnlyPostgresResearchRunStore(postgres_dsn).load(run.run_id)
        cancelled = OnlyPostgresResearchRunStore(postgres_dsn).commit_transition(
            running, running.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW)
        )
        params = [
            *context(fixture),
            claimed["attempt"]["attempt_id"],
            claimed["attempt"]["worker_instance_id"],
            1,
            timedelta(microseconds=1),
        ]
        params[3] = 1
        query = "SELECT public.chart_native_heartbeat_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        before = snapshot(postgres_dsn)
        with pytest.raises(psycopg.Error, match="CHART_NATIVE_OWNERSHIP_LOST"):
            with psycopg.connect(login) as worker:
                worker.execute(query, params)
        assert snapshot(postgres_dsn) == before
        params[3] = cancelled.revision
        with psycopg.connect(login) as worker:
            refreshed = worker.execute(query, params).fetchone()[0]
        assert refreshed["attempt"]["lease_expires_at"] == claimed["attempt"]["lease_expires_at"]
        assert refreshed["run"]["state"] == "CANCEL_REQUESTED" and refreshed["run"]["revision"] == 2


def test_heartbeat_cannot_renew_lease_which_expires_during_run_row_wait(compilation_system, postgres_dsn: str) -> None:
    fixture = compilation_system
    run = handoff(fixture, postgres_dsn).commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    ready = Event()
    pid = []
    with sql_consumer_login(postgres_dsn) as login:
        with psycopg.connect(login) as worker:
            claimed = claim_sql(worker, fixture)
        params = [
            *context(fixture),
            claimed["attempt"]["attempt_id"],
            claimed["attempt"]["worker_instance_id"],
            1,
            timedelta(minutes=2),
        ]
        params[3] = 1

        def heartbeat():
            with psycopg.connect(login) as worker:
                pid.append(worker.info.backend_pid)
                ready.set()
                with pytest.raises(psycopg.Error, match="CHART_NATIVE_OWNERSHIP_LOST"):
                    worker.execute("SELECT public.chart_native_heartbeat_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", params)

        with psycopg.connect(postgres_dsn) as holder, ThreadPoolExecutor(max_workers=1) as pool:
            holder.execute("SELECT run_id FROM public.research_run WHERE run_id=%s FOR UPDATE", (run.run_id.value,))
            future = pool.submit(heartbeat)
            try:
                assert ready.wait(timeout=30)
                deadline = time.monotonic() + 30
                while (
                    holder.info.backend_pid
                    not in holder.execute("SELECT pg_blocking_pids(%s)", (pid[0],)).fetchone()[0]
                ):
                    assert time.monotonic() < deadline, "heartbeat did not reach the database lock barrier"
                # Actual PG wait is the barrier, not elapsed time or a sleep.
                # Negative clock-boundary fault ends the lease between entry and
                # lock release. Sampling time before the wait would renew it.
                holder.execute("SET LOCAL session_replication_role=replica")
                holder.execute(
                    "UPDATE public.research_run_attempt SET lease_expires_at=clock_timestamp() WHERE run_id=%s",
                    (run.run_id.value,),
                )
                holder.commit()
            finally:
                holder.rollback()  # Release lock even if the assertion fails.
            future.result(timeout=30)
