from __future__ import annotations

import pytest

from tests.research.postgres.test_chart_native_publication_permissions import runtime_login

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_source_bootstrap_accepts_real_reader_login_but_not_operator_or_controller(postgres_dsn):
    import psycopg
    from onlyalpha_runtime_generation_manager.chart_native_source import only_require_chart_source_reader

    from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority

    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    with runtime_login(postgres_dsn, "onlyalpha_chart_input_reader") as dsn:
        only_require_chart_source_reader(dsn)
        with psycopg.connect(dsn) as connection:
            assert connection.execute("SELECT count(*) FROM public.research_run_attempt").fetchone() == (0,)
        for statement in (
            "UPDATE public.research_run SET state=state",
            "DELETE FROM public.research_run_attempt",
            "SELECT * FROM public.product_credential",
        ):
            with psycopg.connect(dsn) as connection, pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(statement)
    with pytest.raises(ValueError, match="CHART_NATIVE_SOURCE_READER_UNSAFE"):
        only_require_chart_source_reader(postgres_dsn)
    with (
        runtime_login(postgres_dsn, "onlyalpha_chart_execution_controller") as dsn,
        pytest.raises(ValueError, match="CHART_NATIVE_SOURCE_READER_UNSAFE"),
    ):
        only_require_chart_source_reader(dsn)


@pytest.mark.parametrize(
    "mutation", ["table", "column", "membership", "function", "schema", "builtin_function", "secret_column"]
)
def test_source_bootstrap_rejects_login_with_additional_mutation_authority(postgres_dsn, mutation):
    import psycopg
    from onlyalpha_runtime_generation_manager.chart_native_source import only_require_chart_source_reader
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict

    from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority

    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    with runtime_login(postgres_dsn, "onlyalpha_chart_input_reader") as dsn:
        name = sql.Identifier(conninfo_to_dict(dsn)["user"])
        with psycopg.connect(postgres_dsn, autocommit=True) as connection:
            connection.execute(
                "CREATE FUNCTION public.source_test_write() RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS 'BEGIN NULL; END'"
            )
            connection.execute("REVOKE ALL ON FUNCTION public.source_test_write() FROM PUBLIC")
            connection.execute(
                sql.SQL(
                    {
                        "table": "GRANT UPDATE ON public.research_run TO {}",
                        "column": "GRANT UPDATE(state) ON public.research_run TO {}",
                        "membership": "GRANT onlyalpha_chart_execution_controller TO {}",
                        "function": "GRANT EXECUTE ON FUNCTION public.source_test_write() TO {}",
                        "schema": "GRANT CREATE ON SCHEMA public TO {}",
                        "builtin_function": "GRANT EXECUTE ON FUNCTION pg_catalog.pg_read_file(text) TO {}",
                        "secret_column": "GRANT SELECT(credential_id) ON public.product_credential TO {}",
                    }[mutation]
                ).format(name)
            )
        with pytest.raises(ValueError, match="CHART_NATIVE_SOURCE_READER_UNSAFE"):
            only_require_chart_source_reader(dsn)


def test_reader_schema_reference_is_explicit_and_checksum_verified(postgres_dsn, tmp_path):
    import hashlib
    from pathlib import Path

    import psycopg

    from onlyalpha.persistence.postgres.market_data_catalog import OnlyPostgresMarketDataCatalog
    from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
    from onlyalpha.research.run.errors import OnlyPostgresSchemaIncompatibleError
    from tests.research.postgres.migration_support import copy_migrations_through

    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    root = tmp_path / "reference"
    root.mkdir()
    copy_migrations_through(root, "0049_chart_native_publication_permissions")
    with psycopg.connect(postgres_dsn) as connection:
        before = connection.execute("SELECT * FROM public.onlyalpha_schema_migration ORDER BY migration_id").fetchall()
    originals = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob("*.sql")}
    with runtime_login(postgres_dsn, "onlyalpha_chart_input_reader") as dsn:
        OnlyPostgresMarketDataCatalog(dsn, migration_root=root)
        leaf = root / "0049_chart_native_publication_permissions.sql"
        leaf.write_bytes(leaf.read_bytes() + b"\n-- changed reference\n")
        with pytest.raises(OnlyPostgresSchemaIncompatibleError, match="CHECKSUM_MISMATCH"):
            OnlyPostgresMarketDataCatalog(dsn, migration_root=root)
        leaf.unlink()
        with pytest.raises(OnlyPostgresSchemaIncompatibleError, match="AHEAD"):
            OnlyPostgresMarketDataCatalog(dsn, migration_root=root)
    with psycopg.connect(postgres_dsn) as connection:
        assert (
            before
            == connection.execute("SELECT * FROM public.onlyalpha_schema_migration ORDER BY migration_id").fetchall()
        )
    repository = Path(__file__).resolve().parents[3] / "database/postgres/migrations"
    assert originals == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in repository.glob("*.sql")}
