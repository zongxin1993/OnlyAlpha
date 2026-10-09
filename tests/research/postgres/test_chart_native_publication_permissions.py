from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from onlyalpha.persistence.postgres.migration import (
    OnlyPostgresMigrationAuthority,
    OnlyPostgresSchemaVerifier,
)
from onlyalpha.research.run.errors import OnlyPostgresMigrationIntegrityError, OnlyPostgresSchemaIncompatibleError
from tests.research.postgres.migration_support import copy_migrations_through
from tests.research.postgres.test_chart_calculation_compilation import compilation_system as compilation_system
from tests.research.postgres.test_chart_calculation_native_publication import (
    native_publication_case as native_publication_case,
)
from tests.research.postgres.test_chart_calculation_run_admission import handoff
from tests.runtime_support.chart_execution_host import exact_host_environment as exact_host_environment

pytestmark = [pytest.mark.integration, pytest.mark.postgres]
_PREVIOUS = "0048_chart_calculation_run_admission"
_MIGRATION = "0049_chart_native_publication_permissions"
_GROUPS = ("onlyalpha_chart_input_reader", "onlyalpha_chart_execution_controller")


@contextmanager
def runtime_login(dsn: str, group: str):
    """Real non-superuser login; SET ROLE on an admin connection is not the proof."""
    name = "chart_runtime_test_" + uuid.uuid4().hex
    password = uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEROLE NOCREATEDB NOBYPASSRLS").format(
                sql.Identifier(name), sql.Literal(password)
            )
        )
        connection.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(name)))
    try:
        yield make_conninfo(dsn, user=name, password=password)
    finally:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))


def previous_schema(dsn: str, tmp_path: Path):
    root = tmp_path / "previous-schema"
    root.mkdir()
    copy_migrations_through(root, _PREVIOUS)
    OnlyPostgresMigrationAuthority(dsn, migration_root=root).migrate()
    return root


def snapshot(dsn: str):
    with psycopg.connect(dsn) as connection:
        return (
            connection.execute("SELECT row_to_json(r)::text FROM research_run r ORDER BY run_id").fetchall(),
            connection.execute(
                "SELECT row_to_json(a)::text FROM research_run_attempt a ORDER BY attempt_id"
            ).fetchall(),
            connection.execute(
                "SELECT row_to_json(a)::text FROM chart_calculation_run_admission a ORDER BY run_id"
            ).fetchall(),
            connection.execute(
                "SELECT migration_id,checksum_sha256 FROM onlyalpha_schema_migration ORDER BY migration_id"
            ).fetchall(),
        )


@pytest.mark.parametrize("historical_state", ["QUEUED", "CANCELLED"])
def test_forward_migration_preserves_exact_queued_and_direct_cancelled_bytes(
    compilation_system,
    postgres_dsn: str,
    tmp_path: Path,
    historical_state: str,
) -> None:
    from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore
    from onlyalpha.research.run.model import OnlyResearchRunState
    from tests.application.test_chart_calculation_admission import NOW

    fixture = compilation_system
    run = handoff(fixture, postgres_dsn).commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    if historical_state == "CANCELLED":
        run = OnlyPostgresResearchRunStore(postgres_dsn).commit_transition(
            run, run.transition(OnlyResearchRunState.CANCELLED, at=NOW)
        )
    # The setup uses current history. Isolate migration-under-test by rolling its
    # DDL/ACL/ledger back to the known previous history in this ephemeral test DB.
    # Never edit a published migration or touch a deployed database.
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("DROP TRIGGER chart_native_publication_attempt_closed ON research_run_attempt")
        connection.execute("DROP FUNCTION chart_native_publication_attempt_guard()")
        for group in _GROUPS:
            connection.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(group)))
        connection.execute("DELETE FROM onlyalpha_schema_migration WHERE migration_id = %s", (_MIGRATION,))
    before = snapshot(postgres_dsn)
    previous = tmp_path / "previous-reference"
    previous.mkdir()
    copy_migrations_through(previous, _PREVIOUS)
    assert OnlyPostgresSchemaVerifier(postgres_dsn, migration_root=previous).status().compatible
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == (_MIGRATION,)
    after = snapshot(postgres_dsn)
    assert after[:3] == before[:3]
    assert after[3][:-1] == before[3]
    assert OnlyPostgresResearchRunStore(postgres_dsn).load(run.run_id) == run
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == ()
    with pytest.raises(OnlyPostgresSchemaIncompatibleError, match="AHEAD"):
        OnlyPostgresSchemaVerifier(postgres_dsn, migration_root=previous).assert_compatible()
    assert handoff(fixture, postgres_dsn).load_verified(fixture.operation) == run
    assert snapshot(postgres_dsn)[1] == []


@pytest.mark.parametrize("fault", ["ddl", "ledger"])
def test_migration_ddl_and_ledger_failure_roll_back_roles_acl_and_guard(
    postgres_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    previous_schema(postgres_dsn, tmp_path)
    before = snapshot(postgres_dsn)
    connect = psycopg.connect

    class FaultConnection:
        def __init__(self, connection):
            self.connection = connection

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def execute(self, query, params=None):
            if fault == "ddl" and "CREATE FUNCTION chart_native_publication_attempt_guard" in str(query):
                # Execute the role/ACL/guard DDL and then cause an actual PG error.
                self.connection.execute(query, params)
                return self.connection.execute("SELECT 1/0")
            if fault == "ledger" and "INSERT INTO onlyalpha_schema_migration" in str(query) and params[0] == _MIGRATION:
                return self.connection.execute("SELECT 1/0")
            return self.connection.execute(query, params)

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

    monkeypatch.setattr(psycopg, "connect", lambda *a, **kw: FaultConnection(connect(*a, **kw)))
    with pytest.raises(OnlyPostgresMigrationIntegrityError):
        OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    monkeypatch.setattr(psycopg, "connect", connect)
    assert snapshot(postgres_dsn) == before
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT to_regprocedure('chart_native_publication_attempt_guard()')").fetchone() == (
            None,
        )
        assert connection.execute(
            "SELECT count(*) FROM information_schema.role_table_grants WHERE grantee = ANY(%s)", (list(_GROUPS),)
        ).fetchone() == (0,)
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == (_MIGRATION,)


@pytest.mark.parametrize("unsafe", ["login", "superuser", "membership", "table_grant", "column_grant"])
def test_unsafe_preexisting_role_is_rejected_not_silently_repaired(
    postgres_dsn: str,
    tmp_path: Path,
    unsafe: str,
) -> None:
    previous_schema(postgres_dsn, tmp_path)
    role = _GROUPS[0]
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        if connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone() is None:
            connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        query = {
            "login": "ALTER ROLE onlyalpha_chart_input_reader LOGIN",
            "superuser": "ALTER ROLE onlyalpha_chart_input_reader SUPERUSER",
            "membership": "GRANT pg_read_all_data TO onlyalpha_chart_input_reader",
            "table_grant": "GRANT UPDATE ON research_run TO onlyalpha_chart_input_reader",
            "column_grant": "GRANT UPDATE(state) ON research_run TO onlyalpha_chart_input_reader",
        }[unsafe]
        connection.execute(query)
    before = snapshot(postgres_dsn)
    try:
        with pytest.raises(OnlyPostgresMigrationIntegrityError) as caught:
            OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
        assert "CHART_NATIVE_DATABASE_ROLE_UNSAFE" in str(caught.value.__cause__)
        assert snapshot(postgres_dsn) == before
    finally:
        with psycopg.connect(postgres_dsn, autocommit=True) as connection:
            if unsafe == "login":
                connection.execute("ALTER ROLE onlyalpha_chart_input_reader NOLOGIN")
            elif unsafe == "superuser":
                connection.execute("ALTER ROLE onlyalpha_chart_input_reader NOSUPERUSER")
            elif unsafe == "membership":
                connection.execute("REVOKE pg_read_all_data FROM onlyalpha_chart_input_reader")
            else:
                connection.execute("REVOKE ALL PRIVILEGES ON research_run FROM onlyalpha_chart_input_reader")
                connection.execute("REVOKE UPDATE(state) ON research_run FROM onlyalpha_chart_input_reader")
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == (_MIGRATION,)


@pytest.mark.parametrize("group", _GROUPS)
def test_real_runtime_login_cannot_mutate_authorities_or_escalate(postgres_dsn: str, group: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    before = snapshot(postgres_dsn)
    with runtime_login(postgres_dsn, group) as dsn:
        with psycopg.connect(dsn, autocommit=True) as connection:
            assert connection.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user").fetchone() == (False,)
            for statement in (
                "UPDATE research_run SET state='COMPLETED'",
                "INSERT INTO research_run_attempt(attempt_id) VALUES(gen_random_uuid())",
                "DELETE FROM chart_calculation_run_admission",
                "UPDATE integration_revision SET revision_sequence=1",
                "SELECT * FROM product_credential",
                "SELECT * FROM integration_draft",
                "ALTER TABLE research_run DISABLE TRIGGER ALL",
                "SET session_replication_role=replica",
                "SET ROLE onlyalpha",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(statement)
    assert snapshot(postgres_dsn) == before


def test_attempt_guard_blocks_raw_sql_even_for_trusted_owner_until_native_consumer_exists(
    compilation_system,
    postgres_dsn: str,
) -> None:
    from tests.application.test_chart_calculation_admission import NOW

    fixture = compilation_system
    run = handoff(fixture, postgres_dsn).commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    before = snapshot(postgres_dsn)
    with pytest.raises(psycopg.Error, match="CHART_NATIVE_EXECUTION_NOT_ENABLED"):
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(
                "INSERT INTO research_run_attempt "
                "(attempt_id,run_id,attempt_number,state,worker_instance_id,claimed_at,last_heartbeat_at,lease_expires_at) "
                "VALUES (%s,%s,1,'ACTIVE',%s,%s,%s,%s)",
                (uuid.uuid4(), run.run_id.value, uuid.uuid4(), NOW, NOW, NOW + timedelta(seconds=60)),
            )
    assert snapshot(postgres_dsn) == before


def test_real_source_read_role_and_installed_host_still_do_not_authorize_chart_claim(
    native_publication_case,
    exact_host_environment,
    tmp_path: Path,
    postgres_dsn: str,
) -> None:
    from onlyalpha.application.chart_calculation_native_protocol import (
        ONLYALPHA_CHART_NATIVE_PUBLICATION_CONTRACT_VERSION,
    )
    from onlyalpha.persistence.postgres.research_execution_store import OnlyPostgresResearchExecutionStore
    from onlyalpha.research.execution.model import OnlyResearchRunAttemptId, OnlyResearchWorkerInstanceId
    from tests.application.test_chart_calculation_admission import NOW
    from tests.runtime_support.chart_publication_input import export_input

    chart, compilation, registry, _, _ = native_publication_case
    before = snapshot(postgres_dsn)
    with runtime_login(postgres_dsn, _GROUPS[0]) as dsn:
        # Real original PostgreSQL metadata readers; only physical facts remain
        # the declared saved-original contract fake. No Provider/account access.
        issued = export_input(
            dsn, chart.operation.operation_id.value, chart.dataset._root, tmp_path / "original-facts.json", registry
        )
        from onlyalpha.research.dataset.publication_input import _only_require_verified_sealed_chart_publication_input

        _only_require_verified_sealed_chart_publication_input(
            issued,
            compilation.result_plan_fingerprint,
            compilation.graph_fingerprint,
            compilation.runtime_generation_fingerprint,
        )
    builder, _, host_type = exact_host_environment
    host = host_type(registry=registry, builder=builder, cache_root=tmp_path / "permission-host")
    try:
        actual = host.acquire(compilation.runtime_generation_fingerprint)
        assert ONLYALPHA_CHART_NATIVE_PUBLICATION_CONTRACT_VERSION not in {
            item.value for item in actual.handshake.supported_capabilities
        }
    finally:
        host.close()
    assert (
        OnlyPostgresResearchExecutionStore(postgres_dsn).claim_next(
            worker_instance_id=OnlyResearchWorkerInstanceId.new(),
            attempt_id=OnlyResearchRunAttemptId.new(),
            lease_duration=timedelta(seconds=60),
            max_attempts=3,
            run_started_at=NOW,
            eligible_run_ids=(chart.run.run_id.value,),
        )
        is None
    )
    assert snapshot(postgres_dsn) == before
