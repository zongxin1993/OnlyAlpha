from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority, OnlyPostgresSchemaVerifier
from onlyalpha.research.run.errors import OnlyPostgresMigrationIntegrityError
from tests.research.postgres.migration_support import copy_migrations_through
from tests.research.postgres.test_chart_calculation_compilation import authority_facts, compilation_system

pytestmark = [pytest.mark.integration, pytest.mark.external, pytest.mark.requires_network, pytest.mark.postgres]
MIGRATION = "0048_chart_calculation_run_admission"
PREVIOUS = "0047_chart_calculation_compilation_relation"


def history(dsn):
    with psycopg.connect(dsn) as connection:
        return connection.execute(
            "SELECT migration_id, checksum_sha256 FROM onlyalpha_schema_migration ORDER BY migration_id"
        ).fetchall()


def previous(dsn: str, root: Path):
    root.mkdir()
    copy_migrations_through(root, PREVIOUS)
    authority = OnlyPostgresMigrationAuthority(dsn, migration_root=root)
    assert authority.migrate()[-1] == PREVIOUS
    return authority


def handoff_reference(root: Path) -> Path:
    root.mkdir()
    copy_migrations_through(root, MIGRATION)
    return root


def test_handoff_migration_preserves_all_existing_authority_bytes(
    postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tests.research.postgres.test_chart_calculation_admission as admission

    old = previous(postgres_dsn, tmp_path / "previous")
    monkeypatch.setattr(admission, "OnlyPostgresMigrationAuthority", lambda dsn: old)
    fixture = compilation_system.__wrapped__(postgres_dsn, tmp_path / "inputs", monkeypatch)
    fixture.store.commit_or_replay(fixture.operation, fixture.preparation, fixture.compilation)
    before = authority_facts(postgres_dsn)
    old_history = history(postgres_dsn)
    reference = handoff_reference(tmp_path / "handoff-reference")
    current = OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=reference)
    status = OnlyPostgresSchemaVerifier(postgres_dsn, migration_root=reference).status()
    assert status.pending_migrations == (MIGRATION,)
    assert current.migrate() == (MIGRATION,)
    assert history(postgres_dsn)[:-1] == old_history
    assert authority_facts(postgres_dsn) == before
    assert fixture.store.load_verified(fixture.operation) == fixture.compilation
    assert current.migrate() == ()


def test_handoff_ddl_and_ledger_rollback_then_exact_retry(postgres_dsn: str, tmp_path: Path) -> None:
    previous(postgres_dsn, tmp_path / "previous")
    current = OnlyPostgresMigrationAuthority(
        postgres_dsn, migration_root=handoff_reference(tmp_path / "handoff-reference")
    )
    before = history(postgres_dsn)
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute(
            "CREATE FUNCTION reject_handoff_ledger() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.migration_id = '0048_chart_calculation_run_admission' THEN RAISE EXCEPTION 'injected ledger failure'; END IF; RETURN NEW; END; $$"
        )
        connection.execute(
            "CREATE TRIGGER reject_handoff_ledger BEFORE INSERT ON onlyalpha_schema_migration FOR EACH ROW EXECUTE FUNCTION reject_handoff_ledger()"
        )
    with pytest.raises(OnlyPostgresMigrationIntegrityError):
        current.migrate()
    assert history(postgres_dsn) == before
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT to_regclass('public.chart_calculation_run_admission')").fetchone() == (None,)
        connection.execute("DROP TRIGGER reject_handoff_ledger ON onlyalpha_schema_migration")
        connection.execute("DROP FUNCTION reject_handoff_ledger()")
    assert current.migrate() == (MIGRATION,)
    assert current.migrate() == ()
    assert history(postgres_dsn)[:-1] == before


def test_chart_run_cannot_commit_without_relation_or_as_legacy_origin(postgres_dsn: str, tmp_path: Path) -> None:
    from onlyalpha.application.chart_calculation_run_admission import only_chart_calculation_queued_run
    from onlyalpha.persistence.postgres.research_run_store import OnlyPostgresResearchRunStore, _insert_run_query
    from tests.application.test_chart_calculation_admission import NOW
    from tests.application.test_chart_calculation_compilation import compilation
    from tests.support.chart_calculation_compilation import prepared_input

    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    frozen = compilation(prepared_input(tmp_path))
    run = only_chart_calculation_queued_run(frozen, queued_at=NOW)
    for origin in ("CHART_CALCULATION", "GENERAL", "PRIVATE_STRATEGY"):
        with pytest.raises(psycopg.Error):
            with psycopg.connect(postgres_dsn) as connection:
                parameters = list(OnlyPostgresResearchRunStore._values(run))
                parameters[-1] = origin
                connection.execute(_insert_run_query(), parameters)
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT count(*) FROM research_run").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM research_run_id_reservation").fetchone() == (0,)
