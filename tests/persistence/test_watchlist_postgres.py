from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import pytest

from onlyalpha.application.market_data_product import OnlyMarketDataSourceReferenceV1
from onlyalpha.application.watchlists import OnlyWatchlist, OnlyWatchlistError
from onlyalpha.persistence.postgres.watchlist_store import OnlyPostgresWatchlistStore
from onlyalpha.research.operations.deployment import OnlyResearchSemanticStoreId

pytestmark = pytest.mark.postgres
NAMESPACE = OnlyResearchSemanticStoreId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac")
SOURCE = OnlyMarketDataSourceReferenceV1("source", "a" * 64, "test.market_data")
LIST = OnlyWatchlist("0926c6a2-0cb8-47a5-8d94-cdb89b336182", "日常", SOURCE, ("BTCUSDT.BINANCE",))


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
        replace(LIST, instrument_ids=("BTCUSDT.BINANCE", "BTCUSDT.BINANCE"))
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
