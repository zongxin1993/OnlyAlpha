from __future__ import annotations

import uuid
from contextlib import ExitStack, contextmanager
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

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
_UNSAFE_ROLE_MUTATIONS = {
    "login": ("ALTER ROLE {role} LOGIN", "ALTER ROLE {role} NOLOGIN"),
    "superuser": ("ALTER ROLE {role} SUPERUSER", "ALTER ROLE {role} NOSUPERUSER"),
    "createrole": ("ALTER ROLE {role} CREATEROLE", "ALTER ROLE {role} NOCREATEROLE"),
    "createdb": ("ALTER ROLE {role} CREATEDB", "ALTER ROLE {role} NOCREATEDB"),
    "replication": ("ALTER ROLE {role} REPLICATION", "ALTER ROLE {role} NOREPLICATION"),
    "bypassrls": ("ALTER ROLE {role} BYPASSRLS", "ALTER ROLE {role} NOBYPASSRLS"),
    "noinherit": ("ALTER ROLE {role} NOINHERIT", "ALTER ROLE {role} INHERIT"),
    "connection_limit": ("ALTER ROLE {role} CONNECTION LIMIT 0", "ALTER ROLE {role} CONNECTION LIMIT -1"),
    "password": ("ALTER ROLE {role} PASSWORD 'test-only-no-login'", "ALTER ROLE {role} PASSWORD NULL"),
    "password_expiry": (
        "ALTER ROLE {role} VALID UNTIL '2099-01-01T00:00:00Z'",
        "ALTER ROLE {role} VALID UNTIL 'infinity'",
    ),
    "membership": ("GRANT pg_read_all_data TO {role}", "REVOKE pg_read_all_data FROM {role}"),
    "table_grant": ("GRANT UPDATE ON research_run TO {role}", "REVOKE UPDATE ON research_run FROM {role}"),
    "column_grant": (
        "GRANT UPDATE(state) ON research_run TO {role}",
        "REVOKE UPDATE(state) ON research_run FROM {role}",
    ),
    "schema_grant": ("GRANT CREATE ON SCHEMA public TO {role}", "REVOKE CREATE ON SCHEMA public FROM {role}"),
    "function_grant": (
        "GRANT EXECUTE ON FUNCTION fixture_role_function() TO {role}",
        "REVOKE EXECUTE ON FUNCTION fixture_role_function() FROM {role}",
    ),
    "table_owner": (
        "ALTER TABLE fixture_role_table OWNER TO {role}",
        "ALTER TABLE fixture_role_table OWNER TO onlyalpha",
    ),
    "type_owner": ("ALTER TYPE fixture_role_type OWNER TO {role}", "ALTER TYPE fixture_role_type OWNER TO onlyalpha"),
    "type_grant": (
        "GRANT USAGE ON TYPE fixture_role_type TO {role}",
        "REVOKE USAGE ON TYPE fixture_role_type FROM {role}",
    ),
    "default_grant": (
        "ALTER DEFAULT PRIVILEGES FOR ROLE onlyalpha GRANT SELECT ON TABLES TO {role}",
        "ALTER DEFAULT PRIVILEGES FOR ROLE onlyalpha REVOKE SELECT ON TABLES FROM {role}",
    ),
    "parameter_grant": (
        "GRANT SET ON PARAMETER session_replication_role TO {role}",
        "REVOKE SET ON PARAMETER session_replication_role FROM {role}",
    ),
    "role_setting": (
        "ALTER ROLE {role} SET client_min_messages TO warning",
        "ALTER ROLE {role} RESET client_min_messages",
    ),
}


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
            # Only this newly created ephemeral login's test grants are removed.
            connection.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(name)))
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
            tuple(
                (
                    name,
                    connection.execute(
                        sql.SQL("SELECT row_to_json(r)::text FROM public.{} r ORDER BY row_to_json(r)::text").format(
                            sql.Identifier(name)
                        )
                    ).fetchall(),
                )
                for (name,) in connection.execute(
                    "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public' "
                    "AND tablename NOT IN ('research_run','research_run_attempt',"
                    "'chart_calculation_run_admission','onlyalpha_schema_migration') ORDER BY tablename"
                ).fetchall()
            ),
        )


def role_inventory(dsn: str):
    """Exact group identity/dependencies without exposing stored password material."""
    with psycopg.connect(dsn) as connection:
        return (
            connection.execute(
                "SELECT oid,rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,"
                "rolreplication,rolbypassrls,rolconnlimit,rolvaliduntil::text,rolpassword IS NOT NULL "
                "FROM pg_catalog.pg_authid WHERE rolname=ANY(%s) ORDER BY rolname",
                (list(_GROUPS),),
            ).fetchall(),
            connection.execute(
                "SELECT row_to_json(m)::text FROM pg_catalog.pg_auth_members m "
                "WHERE roleid IN (SELECT oid FROM pg_roles WHERE rolname=ANY(%s)) "
                "OR member IN (SELECT oid FROM pg_roles WHERE rolname=ANY(%s)) ORDER BY m.oid",
                (list(_GROUPS), list(_GROUPS)),
            ).fetchall(),
            connection.execute(
                "SELECT row_to_json(d)::text FROM pg_catalog.pg_shdepend d "
                "WHERE refclassid='pg_catalog.pg_authid'::regclass "
                "AND refobjid IN (SELECT oid FROM pg_roles WHERE rolname=ANY(%s)) "
                "ORDER BY row_to_json(d)::text",
                (list(_GROUPS),),
            ).fetchall(),
            connection.execute(
                "SELECT row_to_json(p)::text FROM pg_catalog.pg_parameter_acl p ORDER BY p.oid"
            ).fetchall(),
            connection.execute(
                "SELECT row_to_json(s)::text FROM pg_catalog.pg_db_role_setting s "
                "WHERE setrole IN (SELECT oid FROM pg_roles WHERE rolname=ANY(%s)) "
                "ORDER BY row_to_json(s)::text",
                (list(_GROUPS),),
            ).fetchall(),
        )


def historical_chart(dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reference = previous_schema(dsn, tmp_path)
    old = OnlyPostgresMigrationAuthority(dsn, migration_root=reference)
    with monkeypatch.context() as context:
        context.setattr(
            "tests.research.postgres.test_chart_calculation_admission.OnlyPostgresMigrationAuthority",
            lambda dsn: old,
        )
        chart = compilation_system.__wrapped__(dsn, tmp_path / "inputs", monkeypatch)
    from tests.application.test_chart_calculation_admission import NOW

    run = handoff(chart, dsn).commit_or_replay(chart.operation, chart.compilation, queued_at=NOW)
    return chart, run


def insert_attempt(connection, run_id: str, state: str = "ACTIVE", *, number: int = 1):
    from tests.application.test_chart_calculation_admission import NOW

    failure = state in {"FAILED", "EXPIRED"}
    attempt_id = uuid.uuid4()
    connection.execute(
        "INSERT INTO public.research_run_attempt "
        "(attempt_id,run_id,attempt_number,state,worker_instance_id,claimed_at,last_heartbeat_at,lease_expires_at,"
        "finished_at,failure_phase,failure_code,failure_detail) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            attempt_id,
            run_id,
            number,
            state,
            uuid.uuid4(),
            NOW,
            NOW,
            NOW + timedelta(seconds=60),
            None if state == "ACTIVE" else NOW,
            "OPERATIONAL" if failure else None,
            "FIXTURE_FAILURE" if failure else None,
            "controlled historical attempt" if failure else None,
        ),
    )
    return attempt_id


@pytest.mark.parametrize("group", _GROUPS)
@pytest.mark.parametrize("authority", ["owner", "grant"])
def test_preexisting_large_object_authority_is_rejected_unchanged(
    postgres_dsn: str, tmp_path: Path, group: str, authority: str
) -> None:
    previous_schema(postgres_dsn, tmp_path)
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        if connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (group,)).fetchone() is None:
            connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(group)))
        oid = connection.execute("SELECT lo_create(0)").fetchone()[0]
        statement = (
            "ALTER LARGE OBJECT {} OWNER TO {}" if authority == "owner" else "GRANT SELECT ON LARGE OBJECT {} TO {}"
        )
        connection.execute(sql.SQL(statement).format(sql.Literal(oid), sql.Identifier(group)))
    before = snapshot(postgres_dsn), role_inventory(postgres_dsn)
    try:
        with pytest.raises(OnlyPostgresMigrationIntegrityError) as caught:
            OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
        assert "CHART_NATIVE_DATABASE_ROLE_UNSAFE" in str(caught.value.__cause__)
        assert (snapshot(postgres_dsn), role_inventory(postgres_dsn)) == before
    finally:
        with psycopg.connect(postgres_dsn, autocommit=True) as connection:
            connection.execute("SELECT lo_unlink(%s)", (oid,))


@pytest.mark.parametrize("state", ["ACTIVE", "SUCCEEDED", "FAILED", "EXPIRED", "CANCELLED"])
def test_preexisting_chart_attempt_blocks_migration_without_erasing_history(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    _, run = historical_chart(postgres_dsn, tmp_path, monkeypatch)
    with psycopg.connect(postgres_dsn) as connection:
        insert_attempt(connection, run.run_id.value, state)
    before = snapshot(postgres_dsn), role_inventory(postgres_dsn)
    with pytest.raises(OnlyPostgresMigrationIntegrityError) as caught:
        OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    assert "CHART_NATIVE_EXISTING_ATTEMPT_UNSUPPORTED" in str(caught.value.__cause__)
    assert (snapshot(postgres_dsn), role_inventory(postgres_dsn)) == before


def test_attempt_writer_cannot_slip_between_history_check_and_guard_installation(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, run = historical_chart(postgres_dsn, tmp_path, monkeypatch)
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        if connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (_GROUPS[1],)).fetchone() is None:
            connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(_GROUPS[1])))
    connect = psycopg.connect
    protected = []
    before = snapshot(postgres_dsn)
    with runtime_login(postgres_dsn, _GROUPS[1]) as writer_dsn:
        with connect(postgres_dsn) as connection:
            name = conninfo_to_dict(writer_dsn)["user"]
            connection.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(name)))
            connection.execute(sql.SQL("GRANT INSERT ON research_run_attempt TO {}").format(sql.Identifier(name)))
            connection.execute(sql.SQL("GRANT INSERT ON research_source_history TO {}").format(sql.Identifier(name)))
            connection.execute(
                sql.SQL("GRANT SELECT,UPDATE ON research_source_history_frontier TO {}").format(sql.Identifier(name))
            )

        class InterleavingConnection:
            def __init__(self, connection):
                self.connection = connection

            def __getattr__(self, name):
                return getattr(self.connection, name)

            def execute(self, query, params=None):
                if isinstance(query, str) and "CREATE FUNCTION chart_native_publication_attempt_guard" in query:
                    prefix, grants = query.split("GRANT USAGE ON SCHEMA public", 1)
                    self.connection.execute(prefix)
                    # A real non-owner writer needs this exact table lock for INSERT.
                    # NOWAIT proves exclusion at the barrier without clocks/sleeps.
                    with connect(writer_dsn) as writer:
                        try:
                            writer.execute("LOCK TABLE public.research_run_attempt IN ROW EXCLUSIVE MODE NOWAIT")
                        except psycopg.errors.LockNotAvailable:
                            protected.append(True)
                        else:
                            insert_attempt(writer, run.run_id.value)
                            protected.append(False)
                    return self.connection.execute("GRANT USAGE ON SCHEMA public" + grants)
                return self.connection.execute(query, params)

            def __enter__(self):
                self.connection.__enter__()
                return self

            def __exit__(self, *args):
                return self.connection.__exit__(*args)

        monkeypatch.setattr(psycopg, "connect", lambda *a, **kw: InterleavingConnection(connect(*a, **kw)))
        assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == (_MIGRATION,)
        monkeypatch.setattr(psycopg, "connect", connect)
        assert protected == [True]
        with pytest.raises(psycopg.Error, match="CHART_NATIVE_EXECUTION_NOT_ENABLED"):
            with connect(writer_dsn) as writer:
                insert_attempt(writer, run.run_id.value)
    after = snapshot(postgres_dsn)
    assert after[:3] == before[:3]
    assert after[3][:-1] == before[3]
    assert after[4] == before[4]


@pytest.mark.parametrize("historical_state", ["QUEUED", "CANCELLED"])
def test_forward_migration_preserves_exact_queued_and_direct_cancelled_bytes(
    postgres_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    historical_state: str,
) -> None:
    from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore
    from onlyalpha.research.run.model import OnlyResearchRunState
    from tests.application.test_chart_calculation_admission import NOW

    fixture, run = historical_chart(postgres_dsn, tmp_path, monkeypatch)
    if historical_state == "CANCELLED":
        run = OnlyPostgresResearchRunStore(postgres_dsn).commit_transition(
            run, run.transition(OnlyResearchRunState.CANCELLED, at=NOW)
        )
    before = snapshot(postgres_dsn)
    previous = tmp_path / "previous-reference"
    previous.mkdir()
    copy_migrations_through(previous, _PREVIOUS)
    assert OnlyPostgresSchemaVerifier(postgres_dsn, migration_root=previous).status().compatible
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == (_MIGRATION,)
    after = snapshot(postgres_dsn)
    assert after[:3] == before[:3]
    assert after[3][:-1] == before[3]
    assert after[4] == before[4]
    assert OnlyPostgresResearchRunStore(postgres_dsn).load(run.run_id) == run
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == ()
    with pytest.raises(OnlyPostgresSchemaIncompatibleError, match="AHEAD"):
        OnlyPostgresSchemaVerifier(postgres_dsn, migration_root=previous).assert_compatible()
    assert handoff(fixture, postgres_dsn).load_verified(fixture.operation) == run
    assert snapshot(postgres_dsn)[1] == []


@pytest.mark.parametrize("fault", ["ddl", "ledger"])
@pytest.mark.parametrize("groups", ["fresh", "preexisting"])
def test_migration_ddl_and_ledger_failure_roll_back_roles_acl_and_guard(
    postgres_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
    groups: str,
) -> None:
    previous_schema(postgres_dsn, tmp_path)
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        if groups == "fresh":
            # DROP ROLE itself refuses dependencies anywhere in this isolated
            # cluster. Never DROP OWNED or clear other databases to force it.
            assert role_inventory(postgres_dsn)[2] == []
            for group in _GROUPS:
                connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(group)))
        else:
            for group in _GROUPS:
                if connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (group,)).fetchone() is None:
                    connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(group)))
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

    with ExitStack() as stack:
        if groups == "preexisting":
            stack.enter_context(runtime_login(postgres_dsn, _GROUPS[0]))
        roles_before = role_inventory(postgres_dsn)
        monkeypatch.setattr(psycopg, "connect", lambda *a, **kw: FaultConnection(connect(*a, **kw)))
        with pytest.raises(OnlyPostgresMigrationIntegrityError):
            OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
        monkeypatch.setattr(psycopg, "connect", connect)
        assert snapshot(postgres_dsn) == before
        assert role_inventory(postgres_dsn) == roles_before
        with psycopg.connect(postgres_dsn) as connection:
            assert connection.execute(
                "SELECT to_regprocedure('chart_native_publication_attempt_guard()')"
            ).fetchone() == (None,)
            assert connection.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname='chart_native_publication_attempt_closed'"
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT count(*) FROM information_schema.role_table_grants WHERE grantee = ANY(%s)", (list(_GROUPS),)
            ).fetchone() == (0,)
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == (_MIGRATION,)


@pytest.mark.parametrize("group", _GROUPS)
@pytest.mark.parametrize("unsafe", tuple(_UNSAFE_ROLE_MUTATIONS))
def test_unsafe_preexisting_role_is_rejected_not_silently_repaired(
    postgres_dsn: str,
    tmp_path: Path,
    unsafe: str,
    group: str,
) -> None:
    previous_schema(postgres_dsn, tmp_path)
    role = group
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        if connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone() is None:
            connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role)))
        connection.execute("CREATE FUNCTION fixture_role_function() RETURNS int LANGUAGE sql AS 'SELECT 1'")
        connection.execute("CREATE TABLE fixture_role_table (value int)")
        connection.execute("CREATE TYPE fixture_role_type AS ENUM ('fixture')")
        connection.execute(sql.SQL(_UNSAFE_ROLE_MUTATIONS[unsafe][0]).format(role=sql.Identifier(role)))
    before = snapshot(postgres_dsn)
    roles_before = role_inventory(postgres_dsn)
    try:
        with pytest.raises(OnlyPostgresMigrationIntegrityError) as caught:
            OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
        assert "CHART_NATIVE_DATABASE_ROLE_UNSAFE" in str(caught.value.__cause__)
        assert snapshot(postgres_dsn) == before
        assert role_inventory(postgres_dsn) == roles_before
    finally:
        with psycopg.connect(postgres_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL(_UNSAFE_ROLE_MUTATIONS[unsafe][1]).format(role=sql.Identifier(role)))
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == (_MIGRATION,)


@pytest.mark.parametrize("group", _GROUPS)
def test_real_runtime_login_cannot_mutate_authorities_or_escalate(postgres_dsn: str, group: str) -> None:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    before = snapshot(postgres_dsn)
    with runtime_login(postgres_dsn, group) as dsn:
        with psycopg.connect(dsn, autocommit=True) as connection:
            assert connection.execute(
                "SELECT rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls FROM pg_roles "
                "WHERE rolname=current_user"
            ).fetchone() == (False, False, False, False, False)
            assert connection.execute(
                "SELECT r.rolname,m.admin_option FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid "
                "WHERE m.member=(SELECT oid FROM pg_roles WHERE rolname=current_user)"
            ).fetchall() == [(group, False)]
            assert connection.execute(
                "SELECT has_parameter_privilege(current_user,'session_replication_role','SET')"
            ).fetchone() == (False,)
            for statement in (
                "UPDATE public.research_run SET state='COMPLETED'",
                "INSERT INTO public.research_run_attempt(attempt_id) VALUES(gen_random_uuid())",
                "DELETE FROM public.chart_calculation_run_admission",
                "UPDATE public.integration_revision SET revision_sequence=1",
                "SELECT * FROM public.product_credential",
                "SELECT * FROM public.integration_draft",
                "ALTER TABLE public.research_run DISABLE TRIGGER ALL",
                "SET session_replication_role=replica",
                "SET ROLE onlyalpha",
                "SELECT * FROM pg_catalog.pg_authid",
                "SELECT public.chart_native_publication_attempt_guard()",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(statement)
    assert snapshot(postgres_dsn) == before


def test_wrong_runtime_credentials_cannot_change_migration_or_owner_facts(postgres_dsn: str, tmp_path: Path) -> None:
    from onlyalpha.research.run.errors import OnlyResearchRunStoreUnavailableError

    previous_schema(postgres_dsn, tmp_path)
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        if connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (_GROUPS[1],)).fetchone() is None:
            connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(_GROUPS[1])))
    with runtime_login(postgres_dsn, _GROUPS[1]) as dsn:
        before = snapshot(postgres_dsn), role_inventory(postgres_dsn)
        wrong = make_conninfo(dsn, password="wrong-controlled-test-password")
        with pytest.raises(OnlyResearchRunStoreUnavailableError):
            OnlyPostgresMigrationAuthority(wrong).migrate()
        assert (snapshot(postgres_dsn), role_inventory(postgres_dsn)) == before


def test_operator_missing_password_catalog_visibility_fails_closed_atomically(
    postgres_dsn: str, tmp_path: Path
) -> None:
    previous_schema(postgres_dsn, tmp_path)
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        if connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (_GROUPS[1],)).fetchone() is None:
            connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(_GROUPS[1])))
    with runtime_login(postgres_dsn, _GROUPS[1]) as dsn:
        name = conninfo_to_dict(dsn)["user"]
        with psycopg.connect(postgres_dsn) as connection:
            # This explicit test operator can plan, lock and create groups, but
            # cannot prove that existing groups have no stored password.
            connection.execute(sql.SQL("ALTER ROLE {} CREATEROLE").format(sql.Identifier(name)))
            connection.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(name)))
            connection.execute(
                sql.SQL("GRANT SELECT,UPDATE ON research_run,research_run_attempt TO {}").format(sql.Identifier(name))
            )
            connection.execute(
                sql.SQL("GRANT SELECT,INSERT ON onlyalpha_schema_migration TO {}").format(sql.Identifier(name))
            )
        before = snapshot(postgres_dsn), role_inventory(postgres_dsn)
        with pytest.raises(OnlyPostgresMigrationIntegrityError) as caught:
            OnlyPostgresMigrationAuthority(dsn).migrate()
        assert isinstance(caught.value.__cause__, psycopg.errors.InsufficientPrivilege)
        assert "pg_authid" in str(caught.value.__cause__)
        assert (snapshot(postgres_dsn), role_inventory(postgres_dsn)) == before


@pytest.mark.parametrize("state", ["ACTIVE", "SUCCEEDED", "FAILED", "EXPIRED", "CANCELLED"])
def test_attempt_guard_blocks_raw_sql_even_for_trusted_owner_until_native_consumer_exists(
    compilation_system,
    postgres_dsn: str,
    state: str,
) -> None:
    from tests.application.test_chart_calculation_admission import NOW

    fixture = compilation_system
    run = handoff(fixture, postgres_dsn).commit_or_replay(fixture.operation, fixture.compilation, queued_at=NOW)
    before = snapshot(postgres_dsn)
    with pytest.raises(psycopg.Error, match="CHART_NATIVE_EXECUTION_NOT_ENABLED"):
        with psycopg.connect(postgres_dsn) as connection:
            insert_attempt(connection, run.run_id.value, state)
    assert snapshot(postgres_dsn) == before


@pytest.mark.parametrize("group", _GROUPS)
@pytest.mark.parametrize("state", ["ACTIVE", "SUCCEEDED", "FAILED", "EXPIRED", "CANCELLED"])
def test_low_permission_login_cannot_insert_any_chart_attempt(
    compilation_system, postgres_dsn: str, group: str, state: str
) -> None:
    from tests.application.test_chart_calculation_admission import NOW

    chart = compilation_system
    run = handoff(chart, postgres_dsn).commit_or_replay(chart.operation, chart.compilation, queued_at=NOW)
    before = snapshot(postgres_dsn)
    with runtime_login(postgres_dsn, group) as dsn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with psycopg.connect(dsn) as connection:
                insert_attempt(connection, run.run_id.value, state)
    assert snapshot(postgres_dsn) == before


@pytest.mark.parametrize("state", ["ACTIVE", "SUCCEEDED", "FAILED", "EXPIRED", "CANCELLED"])
def test_attempt_update_cannot_transfer_legacy_history_to_chart(
    compilation_system, postgres_dsn: str, state: str
) -> None:
    from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore, _insert_run_query
    from tests.application.test_chart_calculation_admission import NOW
    from tests.research.postgres.test_postgres_authority import _queued

    chart = compilation_system
    run = handoff(chart, postgres_dsn).commit_or_replay(chart.operation, chart.compilation, queued_at=NOW)
    legacy = _queued(str(uuid.uuid4()))
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(_insert_run_query(), OnlyPostgresResearchRunStore._values(legacy))
        attempt = insert_attempt(connection, legacy.run_id.value, state)
    before = snapshot(postgres_dsn)
    with pytest.raises(psycopg.Error, match="CHART_NATIVE_EXECUTION_NOT_ENABLED"):
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(
                "UPDATE public.research_run_attempt SET run_id=%s WHERE attempt_id=%s", (run.run_id.value, attempt)
            )
    assert snapshot(postgres_dsn) == before


def test_group_reuse_in_another_test_database_preserves_original_authority(postgres_dsn: str) -> None:
    from onlyalpha.persistence.postgres import only_assert_postgres_test_database
    from tests.research.postgres.migration_support import current_migrations

    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    before = snapshot(postgres_dsn)
    database = "chart_role_reuse_" + uuid.uuid4().hex + "_test"
    other_dsn = urlsplit(postgres_dsn)._replace(path="/" + database).geturl()
    only_assert_postgres_test_database(other_dsn)
    with runtime_login(postgres_dsn, _GROUPS[0]) as reader:
        with psycopg.connect(postgres_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        try:
            roles_before = role_inventory(postgres_dsn)
            assert OnlyPostgresMigrationAuthority(other_dsn).migrate() == current_migrations()
            roles_after = role_inventory(postgres_dsn)
            assert roles_after[:2] == roles_before[:2]
            assert roles_after[3:] == roles_before[3:]
            original_dependencies = set(roles_before[2])
            assert original_dependencies.issubset(roles_after[2])
            assert snapshot(postgres_dsn) == before
            with psycopg.connect(reader) as connection:
                assert connection.execute("SELECT count(*) FROM public.research_run").fetchone() == (0,)
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute("SELECT * FROM public.product_credential")
        finally:
            with psycopg.connect(postgres_dsn, autocommit=True) as connection:
                connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


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
