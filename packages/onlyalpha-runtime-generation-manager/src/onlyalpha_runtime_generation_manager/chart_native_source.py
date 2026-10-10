"""Trusted in-process Source composition; no Host advertisement or operational writes.

Configuration is supplied by the infrastructure launcher, never by a Chart wire
request. The existing export Authority issues the input in this process. A reader
login, copied DTO or factory result cannot start a Chart Attempt.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

from onlyalpha.application.chart_calculation_compilation import OnlyChartCalculationInputVerifier
from onlyalpha.application.chart_calculation_input_export import OnlyChartCalculationInputExportService
from onlyalpha.persistence.clickhouse.client import OnlyClickHouseClient
from onlyalpha.persistence.clickhouse.config import OnlyClickHouseConfig
from onlyalpha.persistence.clickhouse.market_data_store import OnlyClickHouseMarketFactStore
from onlyalpha.persistence.postgres.chart_calculation_compilation_store import (
    OnlyPostgresChartCalculationCompilationStore,
)
from onlyalpha.persistence.postgres.chart_calculation_preparation_store import (
    OnlyPostgresChartCalculationPreparationStore,
)
from onlyalpha.persistence.postgres.chart_calculation_store import OnlyPostgresChartCalculationAdmissionStore
from onlyalpha.persistence.postgres.integration_store import OnlyPostgresIntegrationStore
from onlyalpha.persistence.postgres.market_data_catalog import OnlyPostgresMarketDataCatalog
from onlyalpha.research.dataset.parquet_store import OnlyParquetResearchDatasetSnapshotStore

from .registry import OnlyRuntimeGenerationRegistry

# Projection of the exact SELECT surface in immutable migration 0049. This list
# is a credential admission bound, not an alternate owning Source reader.
_SOURCE_TABLES = (
    "onlyalpha_schema_migration",
    "product_command_admission",
    "product_command_receipt",
    "chart_calculation_operation",
    "chart_calculation_preparation_fact",
    "chart_calculation_compilation",
    "chart_calculation_run_admission",
    "research_run",
    "research_run_id_reservation",
    "research_run_attempt",
    "integration",
    "integration_revision",
    "integration_revision_secret_binding",
    "market_source",
    "market_capture_session",
    "market_ingest_segment",
    "market_segment_state_event",
    "market_segment_physical_proof",
    "market_coverage_manifest",
    "market_coverage_manifest_segment",
    "market_data_revision",
    "market_revision_segment",
    "market_revision_seal",
)


# PG18 removes PUBLIC EXECUTE from these administrative capabilities at initdb
# (src/backend/catalog/system_functions.sql and system_views.sql). Check effective privileges, not
# proacl/dependency shape: a PUBLIC grant has no dependency on this reader. Match
# names to cover every overload. None is required by the owning Source readers.
_RESTRICTED_BUILTINS = (
    "pg_backup_start",
    "pg_backup_stop",
    "pg_create_restore_point",
    "pg_switch_wal",
    "pg_log_standby_snapshot",
    "pg_wal_replay_pause",
    "pg_wal_replay_resume",
    "pg_rotate_logfile",
    "pg_reload_conf",
    "pg_current_logfile",
    "pg_promote",
    "pg_stat_reset",
    "pg_stat_reset_shared",
    "pg_stat_reset_slru",
    "pg_stat_reset_single_table_counters",
    "pg_stat_reset_single_function_counters",
    "pg_stat_reset_backend_stats",
    "pg_stat_reset_replication_slot",
    "pg_stat_have_stats",
    "pg_stat_reset_subscription_stats",
    "lo_import",
    "lo_export",
    "pg_ls_logdir",
    "pg_ls_waldir",
    "pg_ls_archive_statusdir",
    "pg_ls_summariesdir",
    "pg_ls_tmpdir",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_replication_origin_advance",
    "pg_replication_origin_create",
    "pg_replication_origin_drop",
    "pg_replication_origin_oid",
    "pg_replication_origin_progress",
    "pg_replication_origin_session_is_setup",
    "pg_replication_origin_session_progress",
    "pg_replication_origin_session_reset",
    "pg_replication_origin_session_setup",
    "pg_replication_origin_xact_reset",
    "pg_replication_origin_xact_setup",
    "pg_show_replication_origin_status",
    "pg_stat_file",
    "pg_ls_dir",
    "pg_log_backend_memory_contexts",
    "pg_ls_logicalsnapdir",
    "pg_ls_logicalmapdir",
    "pg_ls_replslotdir",
    "pg_show_all_file_settings",
    "pg_hba_file_rules",
    "pg_ident_file_mappings",
    "pg_config",
    "pg_get_shmem_allocations",
    "pg_get_shmem_allocations_numa",
    "pg_get_backend_memory_contexts",
    "pg_get_aios",
)


def only_require_chart_source_reader(dsn: str) -> None:
    """Inspect a real authenticated principal, not SET ROLE on an operator session.

    Runtime admission rejects broad reads/writes, column grants, inherited roles,
    object ownership and callable SECURITY DEFINER authority. Privileged operators
    can change roles after inspection; malicious administration is explicitly not
    in the runtime threat model. No password catalogs or secret values are read.
    """
    with psycopg.connect(dsn) as connection:
        connection.execute("SET LOCAL search_path = pg_catalog")
        row = connection.execute(
            """
            SELECT session_user = current_user AND r.rolcanlogin AND r.rolinherit
              AND NOT r.rolsuper AND NOT r.rolcreatedb AND NOT r.rolcreaterole
              AND NOT r.rolreplication AND NOT r.rolbypassrls
              AND pg_catalog.pg_has_role(session_user, g.oid, 'USAGE')
              AND NOT g.rolcanlogin AND NOT g.rolsuper AND NOT g.rolcreatedb
              AND NOT g.rolcreaterole AND NOT g.rolreplication AND NOT g.rolbypassrls
              AND NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles other
                WHERE other.oid NOT IN (r.oid, g.oid)
                  AND pg_catalog.pg_has_role(session_user, other.oid, 'MEMBER'))
              AND NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_shdepend d
                WHERE d.refclassid = 'pg_catalog.pg_authid'::regclass
                  AND d.refobjid IN (r.oid, g.oid)
                  AND (d.dbid = 0 OR d.dbid = (SELECT oid FROM pg_catalog.pg_database
                                             WHERE datname = current_database()))
                  AND (d.deptype = 'o' OR d.dbid = 0
                       OR d.classid = 'pg_catalog.pg_proc'::regclass
                       OR d.classid = 'pg_catalog.pg_largeobject'::regclass))
              AND NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_namespace n
                WHERE n.nspname NOT LIKE 'pg_%%' AND n.nspname <> 'information_schema'
                  AND pg_catalog.has_schema_privilege(session_user, n.oid, 'CREATE'))
              AND NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname NOT LIKE 'pg_%%' AND n.nspname <> 'information_schema'
                  AND c.relkind IN ('r','p','v','m','f')
                  AND (pg_catalog.has_table_privilege(session_user, c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                    OR pg_catalog.has_any_column_privilege(session_user, c.oid, 'INSERT,UPDATE,REFERENCES')
                    OR ((n.nspname <> 'public' OR c.relname <> ALL(%s))
                        AND pg_catalog.has_any_column_privilege(session_user, c.oid, 'SELECT'))))
              AND NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname NOT LIKE 'pg_%%' AND c.relkind = 'S'
                  AND pg_catalog.has_sequence_privilege(session_user, c.oid, 'USAGE,UPDATE'))
              AND NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                JOIN (VALUES ('pg_authid', 'rolpassword'), ('pg_user_mapping', 'umoptions'),
                             ('pg_subscription', 'subconninfo')) AS secret(relation, column_name)
                  ON secret.relation = c.relname
                WHERE n.nspname = 'pg_catalog'
                  AND pg_catalog.has_column_privilege(session_user, c.oid, secret.column_name, 'SELECT'))
              AND NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_proc p
                JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
                WHERE ((n.nspname = 'pg_catalog' AND p.proname = ANY(%s))
                   OR (n.nspname NOT LIKE 'pg_%%' AND n.nspname <> 'information_schema'
                       AND p.prosecdef AND p.prorettype <> 'pg_catalog.trigger'::regtype))
                  AND pg_catalog.has_function_privilege(session_user, p.oid, 'EXECUTE'))
            FROM pg_catalog.pg_roles r CROSS JOIN pg_catalog.pg_roles g
            WHERE r.rolname = session_user AND g.rolname = 'onlyalpha_chart_input_reader'
            """,
            (list(_SOURCE_TABLES), list(_RESTRICTED_BUILTINS)),
        ).fetchone()
        if row != (True,):
            raise ValueError("CHART_NATIVE_SOURCE_READER_UNSAFE")


def only_chart_native_input_export(
    *,
    postgres_reader_dsn: str,
    clickhouse_reader: OnlyClickHouseConfig,
    dataset_root: Path,
    runtime_registry_root: Path,
    schema_reference_root: Path,
) -> OnlyChartCalculationInputExportService:
    """Compose existing owning ports only, with no Acquisition/Provider credentials.

    Both roots must be provisioned. Registry lock-file access is needed by its
    owning shared-read contract; generation events and Dataset bytes remain under
    their existing deployment permissions. No release/bind/repair is called here.
    The unchanged schema reference is supplied as a trusted deployment asset to
    the PostgreSQL catalog's existing compatibility verifier, not installed into
    a guessed site-packages directory or supplied by a Chart caller.
    """
    for root in (dataset_root, runtime_registry_root, schema_reference_root):
        if not isinstance(root, Path):
            raise ValueError("CHART_NATIVE_SOURCE_ROOT_UNAVAILABLE")
        if root.is_symlink() or not root.is_dir() or root.resolve() != root.absolute():
            raise ValueError("CHART_NATIVE_SOURCE_ROOT_UNAVAILABLE")
    for name in ("generation-events.jsonl", ".generation-authority.lock"):
        path = runtime_registry_root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("CHART_NATIVE_SOURCE_ROOT_UNAVAILABLE")
    if type(clickhouse_reader) is not OnlyClickHouseConfig:
        raise ValueError("CHART_NATIVE_SOURCE_READER_UNSAFE")
    only_require_chart_source_reader(postgres_reader_dsn)
    client = OnlyClickHouseClient(clickhouse_reader)
    readonly = client.query_json("SELECT getSetting('readonly') AS readonly")
    if len(readonly) != 1 or str(readonly[0].get("readonly")) != "1":
        # readonly=2 permits setting changes; readonly=0 is a writer, not a reader.
        raise ValueError("CHART_NATIVE_SOURCE_READER_UNSAFE")
    datasets = OnlyParquetResearchDatasetSnapshotStore(dataset_root)
    registry = OnlyRuntimeGenerationRegistry(runtime_registry_root)
    return OnlyChartCalculationInputExportService(
        operations=OnlyPostgresChartCalculationAdmissionStore(postgres_reader_dsn),
        preparations=OnlyPostgresChartCalculationPreparationStore(postgres_reader_dsn),
        compilations=OnlyPostgresChartCalculationCompilationStore(postgres_reader_dsn),
        inputs=OnlyChartCalculationInputVerifier(
            datasets=datasets, materializations=datasets, runtime_generations=registry
        ),
        integrations=OnlyPostgresIntegrationStore(postgres_reader_dsn),
        catalog=OnlyPostgresMarketDataCatalog(postgres_reader_dsn, migration_root=schema_reference_root),
        facts=OnlyClickHouseMarketFactStore(client),
        materializations=datasets,
    )
