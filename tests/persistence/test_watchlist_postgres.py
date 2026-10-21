from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest

from onlyalpha.application.market_data_product import OnlyMarketDataSourceReferenceV1
from onlyalpha.application.watchlists import OnlyWatchlist, OnlyWatchlistError, OnlyWatchlistMember
from onlyalpha.persistence.postgres.watchlist_store import OnlyPostgresWatchlistStore
from onlyalpha.research.operations.deployment import OnlyResearchSemanticStoreId

pytestmark = pytest.mark.postgres
NAMESPACE = OnlyResearchSemanticStoreId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac")
SOURCE = OnlyMarketDataSourceReferenceV1("source", "a" * 64, "test.market_data")
LIST = OnlyWatchlist("0926c6a2-0cb8-47a5-8d94-cdb89b336182", "日常", (OnlyWatchlistMember(SOURCE, "BTCUSDT.BINANCE"),))


def test_watchlist_commit_replay_conflict_and_fresh_reader(postgres_dsn: str) -> None:
    store = OnlyPostgresWatchlistStore(postgres_dsn, NAMESPACE)
    assert store.read().version == 0
    command = str(uuid4())
    saved = store.save(command, 0, (LIST,))
    assert saved.version == 1 and saved.lists == (LIST,)
    fresh = OnlyPostgresWatchlistStore(postgres_dsn, NAMESPACE)
    assert fresh.read() == saved
    assert fresh.save(command, 0, (LIST,)) == saved
    assert fresh.command(command) == saved
    changed = replace(LIST, name="趋势")
    with pytest.raises(OnlyWatchlistError, match="COMMAND_CONFLICT"):
        fresh.save(command, 0, (changed,))
    with pytest.raises(OnlyWatchlistError, match="VERSION_CONFLICT"):
        fresh.save(str(uuid4()), 0, (changed,))
    next_book = fresh.save(str(uuid4()), 1, (changed,))
    assert next_book.version == 2 and next_book.lists[0].name == "趋势"
    assert fresh.command(command) == saved
    assert OnlyPostgresWatchlistStore(postgres_dsn, OnlyResearchSemanticStoreId.new()).read().version == 0


def test_watchlist_concurrent_edits_have_one_winner(postgres_dsn: str) -> None:
    store = OnlyPostgresWatchlistStore(postgres_dsn, NAMESPACE)

    def save(name: str):
        try:
            return store.save(str(uuid4()), 0, (replace(LIST, name=name),)).version
        except OnlyWatchlistError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(save, ("甲", "乙")))
    assert sorted(map(str, outcomes)) == ["1", "WATCHLIST_VERSION_CONFLICT"]
    assert store.read().version == 1


def test_duplicate_members_and_invalid_identity_are_refused() -> None:
    with pytest.raises(OnlyWatchlistError):
        replace(LIST, members=(LIST.members[0], LIST.members[0]))
    with pytest.raises(OnlyWatchlistError):
        replace(LIST, list_id="not-an-id")
    with pytest.raises(OnlyWatchlistError):
        replace(LIST, name="  ")


def test_stale_head_cannot_hide_a_committed_configuration_revision(postgres_dsn: str) -> None:
    import psycopg

    store = OnlyPostgresWatchlistStore(postgres_dsn, NAMESPACE)
    store.save(str(uuid4()), 0, (LIST,))
    store.save(str(uuid4()), 1, (replace(LIST, name="趋势"),))
    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("UPDATE watchlist_head SET version = 1 WHERE namespace_id = %s", (NAMESPACE.value,))
    with pytest.raises(OnlyWatchlistError, match="HISTORY_CORRUPT"):
        store.read()


def test_global_command_identity_and_unknown_admission_never_create_a_second_effect(postgres_dsn: str) -> None:
    from onlyalpha.application.product_command_receipt import (
        OnlyProductCommandAdmissionV1,
        OnlyProductCommandId,
        OnlyProductCommandKind,
    )
    from onlyalpha.persistence.postgres.product_command_authority import OnlyPostgresProductCommandAuthority

    authority = OnlyPostgresProductCommandAuthority(postgres_dsn)
    command = OnlyProductCommandId(str(uuid4()))
    authority.admit_exact(OnlyProductCommandAdmissionV1(command, OnlyProductCommandKind.CREATE_INTEGRATION, "a" * 64))
    store = OnlyPostgresWatchlistStore(postgres_dsn, NAMESPACE)
    with pytest.raises(OnlyWatchlistError, match="COMMAND_CONFLICT"):
        store.save(command.value, 0, (LIST,))
    assert store.read().version == 0
    pending = OnlyProductCommandId(str(uuid4()))
    authority.admit_exact(OnlyProductCommandAdmissionV1(pending, OnlyProductCommandKind.SAVE_WATCHLISTS, "a" * 64))
    with pytest.raises(OnlyWatchlistError, match="COMMAND_UNKNOWN"):
        store.command(pending.value)
    assert store.read().version == 0


def test_first_read_is_one_snapshot_when_a_writer_commits_between_queries(postgres_dsn: str, monkeypatch) -> None:
    from threading import Event, current_thread

    import psycopg

    store = OnlyPostgresWatchlistStore(postgres_dsn, NAMESPACE)
    entered, release = Event(), Event()
    original = psycopg.connect

    class ReadProbe:
        def __init__(self, connection):
            self.connection = connection

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

        def execute(self, statement, *args):
            result = self.connection.execute(statement, *args)
            if statement.lstrip().startswith("SELECT r.version"):
                entered.set()
                assert release.wait(timeout=5)
            return result

    def connect(*args, **kwargs):
        connection = original(*args, **kwargs)
        return ReadProbe(connection) if current_thread().name.startswith("watchlist-reader") else connection

    monkeypatch.setattr(psycopg, "connect", connect)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="watchlist-reader") as executor:
        future = executor.submit(store.read)
        assert entered.wait(timeout=5)
        try:
            store.save(str(uuid4()), 0, (LIST,))
        finally:
            release.set()
        assert future.result(timeout=5).version == 0
    assert store.read().version == 1


@pytest.mark.parametrize("mutation", ["missing-head", "history-gap", "selected-payload", "selected-receipt"])
def test_configuration_proofs_fail_closed(postgres_dsn: str, mutation: str) -> None:
    import psycopg

    from onlyalpha.application.product_command_authority import OnlyProductCommandReceiptCorruptError

    store = OnlyPostgresWatchlistStore(postgres_dsn, NAMESPACE)
    first = str(uuid4())
    store.save(first, 0, (LIST,))
    store.save(str(uuid4()), 1, (replace(LIST, name="趋势"),))
    with psycopg.connect(postgres_dsn) as connection:
        if mutation == "missing-head":
            connection.execute("DELETE FROM watchlist_head WHERE namespace_id = %s", (NAMESPACE.value,))
        elif mutation == "history-gap":
            connection.execute("ALTER TABLE watchlist_revision DISABLE TRIGGER watchlist_revision_immutable")
            connection.execute(
                "DELETE FROM watchlist_revision WHERE namespace_id = %s AND version = 1", (NAMESPACE.value,)
            )
            connection.execute("ALTER TABLE watchlist_revision ENABLE TRIGGER watchlist_revision_immutable")
        elif mutation == "selected-payload":
            connection.execute("ALTER TABLE watchlist_revision DISABLE TRIGGER watchlist_revision_immutable")
            connection.execute(
                "UPDATE watchlist_revision SET book_json = '{}'::jsonb WHERE namespace_id = %s AND version = 1",
                (NAMESPACE.value,),
            )
            connection.execute("ALTER TABLE watchlist_revision ENABLE TRIGGER watchlist_revision_immutable")
        else:
            connection.execute("ALTER TABLE product_command_receipt DISABLE TRIGGER USER")
            connection.execute(
                "UPDATE product_command_receipt SET outcome_id = %s WHERE command_id = %s", ("f" * 64, first)
            )
            connection.execute("ALTER TABLE product_command_receipt ENABLE TRIGGER USER")
    if mutation in {"missing-head", "history-gap"}:
        with pytest.raises(OnlyWatchlistError, match="HISTORY_CORRUPT"):
            store.read()
        with pytest.raises(OnlyWatchlistError, match="HISTORY_CORRUPT"):
            store.save(str(uuid4()), 2, ())
    else:
        with pytest.raises((OnlyWatchlistError, OnlyProductCommandReceiptCorruptError)):
            store.command(first)


def test_watchlist_service_classifies_bound_intents_before_source_validation(postgres_dsn: str) -> None:
    from typing import cast

    from onlyalpha.application.market_data_product import OnlyMarketDataProductService
    from onlyalpha.application.product_command_receipt import (
        OnlyProductCommandAdmissionV1,
        OnlyProductCommandId,
        OnlyProductCommandKind,
    )
    from onlyalpha.application.source_read_access import OnlySourceReadSession
    from onlyalpha.application.watchlists import OnlyWatchlistService
    from onlyalpha.canonical import only_canonical_fingerprint
    from onlyalpha.persistence.postgres.product_command_authority import OnlyPostgresProductCommandAuthority

    store = OnlyPostgresWatchlistStore(postgres_dsn, NAMESPACE)
    service = OnlyWatchlistService(store, cast(OnlyMarketDataProductService, object()))
    authority = OnlyPostgresProductCommandAuthority(postgres_dsn)
    for kind in (OnlyProductCommandKind.CREATE_INTEGRATION, OnlyProductCommandKind.SAVE_WATCHLISTS):
        command = OnlyProductCommandId(str(uuid4()))
        authority.admit_exact(OnlyProductCommandAdmissionV1(command, kind, "a" * 64))
        with pytest.raises(OnlyWatchlistError, match="WATCHLIST_COMMAND_CONFLICT"):
            service.save(command.value, 0, (LIST,), cast(OnlySourceReadSession, object()))
    pending = OnlyProductCommandId(str(uuid4()))
    fingerprint = only_canonical_fingerprint({"namespace_id": NAMESPACE.value, "expected_version": 0, "lists": (LIST,)})
    authority.admit_exact(OnlyProductCommandAdmissionV1(pending, OnlyProductCommandKind.SAVE_WATCHLISTS, fingerprint))
    with pytest.raises(OnlyWatchlistError, match="WATCHLIST_COMMAND_UNKNOWN"):
        service.save(pending.value, 0, (LIST,), cast(OnlySourceReadSession, object()))
    assert store.read().version == 0


def _insert_original_revision(connection, namespace, command, payload, *, before_migration=False):
    from psycopg.types.json import Jsonb

    from onlyalpha.application.product_command_receipt import (
        OnlyProductCommandAdmissionV1,
        OnlyProductCommandId,
        OnlyProductCommandKind,
        OnlyProductCommandOutcomeKind,
        OnlyProductCommandOutcomeRef,
        OnlyProductCommandReceipt,
    )
    from onlyalpha.canonical import only_canonical_fingerprint
    from onlyalpha.core.clock import only_system_utc_now
    from onlyalpha.persistence.postgres.product_command_authority import OnlyPostgresProductCommandAuthority as Commands

    fingerprint = only_canonical_fingerprint({"namespace_id": namespace.value, "book": payload})
    intent = only_canonical_fingerprint(
        {"namespace_id": namespace.value, "expected_version": 0, "lists": payload["lists"]}
    )
    admission = OnlyProductCommandAdmissionV1(
        OnlyProductCommandId(command), OnlyProductCommandKind.SAVE_WATCHLISTS, intent
    )
    Commands.insert_or_verify_admission(connection, admission)
    if before_migration:
        connection.execute(
            """INSERT INTO watchlist_revision
            (namespace_id,version,fingerprint,book_json,command_id) VALUES (%s,1,%s,%s,%s)""",
            (namespace.value, fingerprint, Jsonb(payload), command),
        )
    else:
        connection.execute(
            """INSERT INTO watchlist_revision
            (namespace_id,version,fingerprint,book_json,command_id,representation_version) VALUES (%s,1,%s,%s,%s,1)""",
            (namespace.value, fingerprint, Jsonb(payload), command),
        )
    connection.execute("INSERT INTO watchlist_head(namespace_id,version) VALUES (%s,1)", (namespace.value,))
    Commands.insert_verified_receipt(
        connection,
        OnlyProductCommandReceipt(
            admission.command_id,
            admission.command_kind,
            admission.command_fingerprint,
            OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.WATCHLIST_REVISION, fingerprint),
            only_system_utc_now(),
        ),
    )


def test_original_0051_history_replays_without_rewriting_payload_fingerprint_or_receipt(postgres_dsn):
    from dataclasses import asdict

    import psycopg

    command = str(uuid4())
    payload = {
        "version": 1,
        "lists": [
            {
                "list_id": LIST.list_id,
                "name": LIST.name,
                "source": asdict(SOURCE),
                "instrument_ids": [LIST.members[0].instrument_id],
            }
        ],
    }
    with psycopg.connect(postgres_dsn) as connection:
        _insert_original_revision(connection, NAMESPACE, command, payload)
        before = connection.execute("SELECT * FROM watchlist_revision WHERE command_id = %s", (command,)).fetchone()
        receipt = connection.execute(
            "SELECT * FROM product_command_receipt WHERE command_id = %s", (command,)
        ).fetchone()
    store = OnlyPostgresWatchlistStore(postgres_dsn, NAMESPACE)
    original = store.read()
    assert original.lists == (LIST,)
    assert store.command(command) == original
    assert store.save(command, 0, (LIST,)) == original
    other = OnlyWatchlistMember(replace(SOURCE, integration_id="other"), LIST.members[0].instrument_id)
    mixed = replace(LIST, members=(*LIST.members, other))
    upgraded = store.save(str(uuid4()), 1, (mixed,))
    assert upgraded.version == 2
    assert OnlyPostgresWatchlistStore(postgres_dsn, NAMESPACE).read() == upgraded
    assert store.command(command) == original
    assert store.save(command, 0, (LIST,)) == original
    with pytest.raises(OnlyWatchlistError, match="COMMAND_CONFLICT"):
        store.save(command, 0, (replace(LIST, members=(other,)),))
    with psycopg.connect(postgres_dsn) as connection:
        assert (
            connection.execute("SELECT * FROM watchlist_revision WHERE command_id = %s", (command,)).fetchone()
            == before
        )
        assert (
            connection.execute("SELECT * FROM product_command_receipt WHERE command_id = %s", (command,)).fetchone()
            == receipt
        )


@pytest.mark.parametrize("mutation", ["source", "member", "representation", "fingerprint"])
def test_original_history_structural_mutation_fails_closed(postgres_dsn, mutation):
    from dataclasses import asdict

    import psycopg

    command = str(uuid4())
    payload = {
        "version": 1,
        "lists": [
            {
                "list_id": LIST.list_id,
                "name": LIST.name,
                "source": asdict(SOURCE),
                "instrument_ids": [LIST.members[0].instrument_id],
            }
        ],
    }
    with psycopg.connect(postgres_dsn) as connection:
        _insert_original_revision(connection, NAMESPACE, command, payload)
        # Verify the deferred receipt FK before fault-injection DDL; do not disable integrity checks.
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        connection.execute("ALTER TABLE watchlist_revision DISABLE TRIGGER watchlist_revision_immutable")
        if mutation == "source":
            payload["lists"][0]["source"]["integration_id"] = "other"
        elif mutation == "member":
            payload["lists"][0]["instrument_ids"].append("BTCUSDT.BINANCE")
        if mutation in ("source", "member"):
            from psycopg.types.json import Jsonb

            connection.execute(
                "UPDATE watchlist_revision SET book_json=%s WHERE command_id=%s", (Jsonb(payload), command)
            )
        elif mutation == "representation":
            connection.execute("UPDATE watchlist_revision SET representation_version=2 WHERE command_id=%s", (command,))
        else:
            connection.execute("UPDATE watchlist_revision SET fingerprint=%s WHERE command_id=%s", ("f" * 64, command))
        connection.execute("ALTER TABLE watchlist_revision ENABLE TRIGGER watchlist_revision_immutable")
    store = OnlyPostgresWatchlistStore(postgres_dsn, NAMESPACE)
    with pytest.raises(OnlyWatchlistError, match="HISTORY_CORRUPT"):
        store.read()
    with pytest.raises(OnlyWatchlistError, match="HISTORY_CORRUPT"):
        store.command(command)


def test_original_unknown_admission_stays_unknown_for_exact_intent(postgres_dsn):
    from dataclasses import asdict

    from onlyalpha.application.product_command_receipt import (
        OnlyProductCommandAdmissionV1,
        OnlyProductCommandId,
        OnlyProductCommandKind,
    )
    from onlyalpha.canonical import only_canonical_fingerprint
    from onlyalpha.persistence.postgres.product_command_authority import OnlyPostgresProductCommandAuthority

    original_lists = [
        {
            "list_id": LIST.list_id,
            "name": LIST.name,
            "source": asdict(SOURCE),
            "instrument_ids": [LIST.members[0].instrument_id],
        }
    ]
    command = OnlyProductCommandId(str(uuid4()))
    fingerprint = only_canonical_fingerprint(
        {"namespace_id": NAMESPACE.value, "expected_version": 0, "lists": original_lists}
    )
    OnlyPostgresProductCommandAuthority(postgres_dsn).admit_exact(
        OnlyProductCommandAdmissionV1(command, OnlyProductCommandKind.SAVE_WATCHLISTS, fingerprint)
    )
    store = OnlyPostgresWatchlistStore(postgres_dsn, NAMESPACE)
    with pytest.raises(OnlyWatchlistError, match="COMMAND_UNKNOWN"):
        store.save(command.value, 0, (LIST,))
    with pytest.raises(OnlyWatchlistError, match="COMMAND_CONFLICT"):
        store.save(command.value, 0, (replace(LIST, name="changed"),))
    assert store.read().version == 0


def test_0052_migration_preserves_original_facts_and_is_atomic_restartable(postgres_dsn, tmp_path):
    from dataclasses import asdict

    import psycopg

    from onlyalpha.persistence.postgres.migration import (
        DEFAULT_MIGRATION_ROOT,
        OnlyPostgresMigrationAuthority,
    )
    from onlyalpha.research.run.errors import OnlyPostgresMigrationIntegrityError

    # The canonical _test fixture already admits the DSN; build the actual prior schema.
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    old_root = tmp_path / "prior"
    old_root.mkdir()
    for path in sorted(DEFAULT_MIGRATION_ROOT.glob("*.sql")):
        if path.name <= "0051_watchlist_configuration.sql":
            (old_root / path.name).write_bytes(path.read_bytes())
    OnlyPostgresMigrationAuthority(postgres_dsn, migration_root=old_root).migrate()
    command = str(uuid4())
    payload = {
        "version": 1,
        "lists": [
            {
                "list_id": LIST.list_id,
                "name": LIST.name,
                "source": asdict(SOURCE),
                "instrument_ids": [LIST.members[0].instrument_id],
            }
        ],
    }
    with psycopg.connect(postgres_dsn) as connection:
        _insert_original_revision(connection, NAMESPACE, command, payload, before_migration=True)
        before = connection.execute(
            "SELECT namespace_id,version,fingerprint,book_json,command_id FROM watchlist_revision"
        ).fetchall()
        receipts = connection.execute("SELECT * FROM product_command_receipt").fetchall()
        admissions = connection.execute("SELECT * FROM product_command_admission").fetchall()
        ledger = connection.execute("SELECT * FROM onlyalpha_schema_migration ORDER BY migration_id").fetchall()
        connection.execute("""CREATE FUNCTION reject_watchlist_upgrade() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            IF NEW.migration_id = '0052_watchlist_member_sources' THEN RAISE EXCEPTION 'injected ledger failure';
            END IF; RETURN NEW; END; $$""")
        connection.execute("""CREATE TRIGGER reject_watchlist_upgrade BEFORE INSERT ON onlyalpha_schema_migration
            FOR EACH ROW EXECUTE FUNCTION reject_watchlist_upgrade()""")
    migrator = OnlyPostgresMigrationAuthority(postgres_dsn)
    with pytest.raises(OnlyPostgresMigrationIntegrityError):
        migrator.migrate()
    with psycopg.connect(postgres_dsn) as connection:
        assert connection.execute("SELECT * FROM onlyalpha_schema_migration ORDER BY migration_id").fetchall() == ledger
        assert connection.execute("""SELECT count(*) FROM information_schema.columns WHERE table_name='watchlist_revision'
            AND column_name='representation_version'""").fetchone() == (0,)
        connection.execute("DROP TRIGGER reject_watchlist_upgrade ON onlyalpha_schema_migration")
        connection.execute("DROP FUNCTION reject_watchlist_upgrade()")
    assert migrator.migrate() == ("0052_watchlist_member_sources", "0053_backtest_native_specification")
    assert OnlyPostgresMigrationAuthority(postgres_dsn).migrate() == ()
    with psycopg.connect(postgres_dsn) as connection:
        assert (
            connection.execute(
                "SELECT namespace_id,version,fingerprint,book_json,command_id FROM watchlist_revision"
            ).fetchall()
            == before
        )
        assert connection.execute("SELECT * FROM product_command_receipt").fetchall() == receipts
        assert connection.execute("SELECT * FROM product_command_admission").fetchall() == admissions
        assert connection.execute("SELECT representation_version FROM watchlist_revision").fetchall() == [(1,)]
        upgraded = connection.execute("SELECT * FROM onlyalpha_schema_migration ORDER BY migration_id").fetchall()
        assert upgraded[: len(ledger)] == ledger
        assert [row[0] for row in upgraded[len(ledger) :]] == [
            "0052_watchlist_member_sources",
            "0053_backtest_native_specification",
        ]
    fresh = OnlyPostgresWatchlistStore(postgres_dsn, NAMESPACE)
    assert fresh.read().lists == (LIST,)
    assert fresh.command(command) == fresh.read()
    assert fresh.save(command, 0, (LIST,)) == fresh.read()


def test_original_empty_list_committed_replay_and_unknown_source_are_not_guessed(postgres_dsn):
    from dataclasses import asdict

    import psycopg

    from onlyalpha.application.product_command_receipt import (
        OnlyProductCommandAdmissionV1,
        OnlyProductCommandId,
        OnlyProductCommandKind,
    )
    from onlyalpha.canonical import only_canonical_fingerprint
    from onlyalpha.persistence.postgres.product_command_authority import OnlyPostgresProductCommandAuthority

    payload = {
        "version": 1,
        "lists": [{"list_id": LIST.list_id, "name": LIST.name, "source": asdict(SOURCE), "instrument_ids": []}],
    }
    command = str(uuid4())
    with psycopg.connect(postgres_dsn) as connection:
        _insert_original_revision(connection, NAMESPACE, command, payload)
        before = connection.execute("SELECT * FROM watchlist_revision WHERE command_id=%s", (command,)).fetchone()
        receipt = connection.execute("SELECT * FROM product_command_receipt WHERE command_id=%s", (command,)).fetchone()
    store = OnlyPostgresWatchlistStore(postgres_dsn, NAMESPACE)
    empty = replace(LIST, members=())
    committed = store.read()
    assert committed.lists == (empty,)
    assert store.save(command, 0, (empty,)) == committed
    assert store.command(command) == committed
    pending = OnlyProductCommandId(str(uuid4()))
    intent = only_canonical_fingerprint(
        {"namespace_id": NAMESPACE.value, "expected_version": 0, "lists": payload["lists"]}
    )
    OnlyPostgresProductCommandAuthority(postgres_dsn).admit_exact(
        OnlyProductCommandAdmissionV1(pending, OnlyProductCommandKind.SAVE_WATCHLISTS, intent)
    )
    with pytest.raises(OnlyWatchlistError, match="WATCHLIST_COMMAND_CONFLICT"):
        store.save(pending.value, 0, (empty,))
    with pytest.raises(OnlyWatchlistError, match="WATCHLIST_COMMAND_UNKNOWN"):
        store.command(pending.value)
    assert store.read() == committed
    with psycopg.connect(postgres_dsn) as connection:
        assert (
            connection.execute("SELECT * FROM watchlist_revision WHERE command_id=%s", (command,)).fetchone() == before
        )
        assert (
            connection.execute("SELECT * FROM product_command_receipt WHERE command_id=%s", (command,)).fetchone()
            == receipt
        )
        assert connection.execute(
            "SELECT count(*) FROM watchlist_revision WHERE command_id=%s", (pending.value,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM product_command_receipt WHERE command_id=%s", (pending.value,)
        ).fetchone() == (0,)
