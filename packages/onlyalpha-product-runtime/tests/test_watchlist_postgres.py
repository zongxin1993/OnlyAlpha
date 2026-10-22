"""Native Watchlist persistence over existing canonical PG facts, not UI acceptance."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from onlyalpha.application.market_data_product import OnlyMarketDataSourceReferenceV1
from onlyalpha.application.product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandOutcomeRef,
    OnlyProductCommandReceipt,
)
from onlyalpha.application.watchlists import OnlyWatchlist, OnlyWatchlistBook, OnlyWatchlistMember
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.persistence.postgres.product_command_authority import OnlyPostgresProductCommandAuthority as Commands
from onlyalpha.persistence.postgres.watchlist_store import OnlyPostgresWatchlistStore
from onlyalpha.research.operations.deployment import OnlyResearchSemanticStoreId
from tests.support.postgres_link import CommitAckCut, wait_for_database_lock_barrier

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]
NOW = datetime(2026, 8, 27, tzinfo=UTC)
NS = OnlyResearchSemanticStoreId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac")
SOURCE = OnlyMarketDataSourceReferenceV1("source", "a" * 64, "test.market_data")
LIST = OnlyWatchlist("0926c6a2-0cb8-47a5-8d94-cdb89b336182", "日常", (OnlyWatchlistMember(SOURCE, "BTCUSDT.BINANCE"),))


@pytest.fixture
def watchlist_db(postgres_dsn: str) -> str:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    return postgres_dsn


def run(
    probe: Path,
    operation: str,
    *,
    command_id: str | None = None,
    expected_version: int = 0,
    lists: tuple[OnlyWatchlist, ...] = (LIST,),
    namespace: str = NS.value,
) -> dict[str, Any]:
    payload = {
        "op": operation,
        "command_id": command_id or str(uuid4()),
        "namespace_id": namespace,
        "expected_version": expected_version,
        "lists": [asdict(item) for item in lists],
        "accepted_at": NOW.isoformat(),
    }
    result = subprocess.run([str(probe)], input=json.dumps(payload), text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


def expected(version: int, lists: tuple[OnlyWatchlist, ...] = (LIST,)) -> dict[str, object]:
    return {"book": json.loads(json.dumps(asdict(OnlyWatchlistBook(version, lists))))}


def test_python_history_native_reader_and_native_current_writer_exact_replay(
    native_probe: Path, watchlist_db: str
) -> None:
    owner = OnlyPostgresWatchlistStore(watchlist_db, NS)
    assert run(native_probe, "watchlist-read") == expected(0, ())
    original = str(uuid4())
    first = owner.save(original, 0, (LIST,))
    assert run(native_probe, "watchlist-read") == expected(1)
    assert run(native_probe, "watchlist-command", command_id=original) == expected(1)
    assert run(native_probe, "watchlist-save", command_id=original) == expected(1)
    changed = replace(LIST, name="趋势")
    second = str(uuid4())
    assert run(native_probe, "watchlist-save", command_id=second, expected_version=1, lists=(changed,)) == expected(
        2, (changed,)
    )
    fresh = OnlyPostgresWatchlistStore(watchlist_db, NS)
    assert fresh.read() == OnlyWatchlistBook(2, (changed,))
    assert fresh.command(second) == fresh.read()
    assert fresh.save(second, 1, (changed,)) == fresh.read()
    assert run(native_probe, "watchlist-command", command_id=original) == expected(1)
    assert run(native_probe, "watchlist-save", command_id=original) == expected(1)
    assert owner.command(original) == first
    assert run(native_probe, "watchlist-save", command_id=original, lists=(changed,)) == {
        "error": "WATCHLIST_COMMAND_CONFLICT"
    }
    losing = str(uuid4())
    assert run(native_probe, "watchlist-save", command_id=losing) == {"error": "WATCHLIST_VERSION_CONFLICT"}
    assert Commands(watchlist_db).load_admission(OnlyProductCommandId(losing)) is None
    assert run(native_probe, "watchlist-read", namespace=str(uuid4())) == expected(0, ())
    assert run(native_probe, "watchlist-command", command_id=original, namespace=str(uuid4())) == {
        "error": "WATCHLIST_HISTORY_CORRUPT"
    }


def insert_original(dsn: str, *, empty: bool) -> tuple[str, dict[str, Any]]:
    payload: dict[str, Any] = {
        "version": 1,
        "lists": [
            {
                "list_id": LIST.list_id,
                "name": LIST.name,
                "source": asdict(SOURCE),
                "instrument_ids": [] if empty else [LIST.members[0].instrument_id],
            }
        ],
    }
    cid = str(uuid4())
    fingerprint = only_canonical_fingerprint({"namespace_id": NS.value, "book": payload})
    intent = only_canonical_fingerprint({"namespace_id": NS.value, "expected_version": 0, "lists": payload["lists"]})
    admission = OnlyProductCommandAdmissionV1(OnlyProductCommandId(cid), OnlyProductCommandKind.SAVE_WATCHLISTS, intent)
    with psycopg.connect(dsn) as connection:
        Commands.insert_or_verify_admission(connection, admission)
        connection.execute(
            "INSERT INTO watchlist_revision(namespace_id,version,fingerprint,book_json,command_id,representation_version) VALUES(%s,1,%s,%s,%s,1)",
            (NS.value, fingerprint, Jsonb(payload), cid),
        )
        connection.execute("INSERT INTO watchlist_head(namespace_id,version) VALUES(%s,1)", (NS.value,))
        Commands.insert_verified_receipt(
            connection,
            OnlyProductCommandReceipt(
                admission.command_id,
                admission.command_kind,
                intent,
                OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.WATCHLIST_REVISION, fingerprint),
                NOW,
            ),
        )
    return cid, payload


@pytest.mark.parametrize("empty", [False, True])
def test_original_immutable_history_is_verified_before_projection_and_never_rewritten(
    native_probe: Path, watchlist_db: str, empty: bool
) -> None:
    cid, _payload = insert_original(watchlist_db, empty=empty)
    lists = (replace(LIST, members=()) if empty else LIST,)
    with psycopg.connect(watchlist_db) as connection:
        before = connection.execute("SELECT * FROM watchlist_revision WHERE command_id=%s", (cid,)).fetchone()
        receipt = connection.execute("SELECT * FROM product_command_receipt WHERE command_id=%s", (cid,)).fetchone()
    assert run(native_probe, "watchlist-read") == expected(1, lists)
    assert run(native_probe, "watchlist-command", command_id=cid) == expected(1, lists)
    assert run(native_probe, "watchlist-save", command_id=cid, lists=lists) == expected(1, lists)
    assert run(native_probe, "watchlist-save", expected_version=1) == expected(2)
    assert run(native_probe, "watchlist-save", command_id=cid, lists=lists) == expected(1, lists)
    with psycopg.connect(watchlist_db) as connection:
        assert connection.execute("SELECT * FROM watchlist_revision WHERE command_id=%s", (cid,)).fetchone() == before
        assert (
            connection.execute("SELECT * FROM product_command_receipt WHERE command_id=%s", (cid,)).fetchone()
            == receipt
        )
    assert OnlyPostgresWatchlistStore(watchlist_db, NS).read() == OnlyWatchlistBook(2, (LIST,))


def test_admission_only_is_unknown_and_changed_or_foreign_intent_never_executes(
    native_probe: Path, watchlist_db: str
) -> None:
    owner = Commands(watchlist_db)
    for family in [OnlyProductCommandKind.CREATE_INTEGRATION, OnlyProductCommandKind.SAVE_WATCHLISTS]:
        cid = OnlyProductCommandId(str(uuid4()))
        intent = only_canonical_fingerprint({"namespace_id": NS.value, "expected_version": 0, "lists": (LIST,)})
        owner.admit_exact(OnlyProductCommandAdmissionV1(cid, family, intent))
        error = (
            "WATCHLIST_COMMAND_UNKNOWN"
            if family is OnlyProductCommandKind.SAVE_WATCHLISTS
            else "WATCHLIST_COMMAND_CONFLICT"
        )
        assert run(native_probe, "watchlist-command", command_id=cid.value) == {"error": error}
        assert run(native_probe, "watchlist-save", command_id=cid.value) == {"error": error}
        assert run(native_probe, "watchlist-save", command_id=cid.value, lists=()) == {
            "error": "WATCHLIST_COMMAND_CONFLICT"
        }
    assert run(native_probe, "watchlist-read") == expected(0, ())


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-head",
        "stale-head",
        "history-gap",
        "payload",
        "representation",
        "receipt-outcome",
        "source-ref",
        "intent",
    ],
)
def test_current_and_exact_history_proofs_fail_closed(native_probe: Path, watchlist_db: str, mutation: str) -> None:
    owner = OnlyPostgresWatchlistStore(watchlist_db, NS)
    first, second = str(uuid4()), str(uuid4())
    owner.save(first, 0, (LIST,))
    owner.save(second, 1, (replace(LIST, name="趋势"),))
    with psycopg.connect(watchlist_db) as connection:
        if mutation == "missing-head":
            connection.execute("DELETE FROM watchlist_head WHERE namespace_id=%s", (NS.value,))
        elif mutation == "stale-head":
            connection.execute("UPDATE watchlist_head SET version=1 WHERE namespace_id=%s", (NS.value,))
        elif mutation == "history-gap":
            connection.execute("ALTER TABLE watchlist_revision DISABLE TRIGGER watchlist_revision_immutable")
            connection.execute("DELETE FROM watchlist_revision WHERE namespace_id=%s AND version=1", (NS.value,))
            connection.execute("ALTER TABLE watchlist_revision ENABLE TRIGGER watchlist_revision_immutable")
        elif mutation in {"payload", "representation", "source-ref"}:
            connection.execute("ALTER TABLE watchlist_revision DISABLE TRIGGER watchlist_revision_immutable")
            if mutation == "payload":
                connection.execute("UPDATE watchlist_revision SET book_json='{}'::jsonb WHERE command_id=%s", (second,))
            elif mutation == "representation":
                connection.execute(
                    "UPDATE watchlist_revision SET representation_version=1 WHERE command_id=%s", (second,)
                )
            else:
                connection.execute(
                    "UPDATE watchlist_revision SET book_json=jsonb_set(book_json,'{lists,0,members,0,source,integration_id}','\"other\"'::jsonb) WHERE command_id=%s",
                    (second,),
                )
            connection.execute("ALTER TABLE watchlist_revision ENABLE TRIGGER watchlist_revision_immutable")
        elif mutation == "receipt-outcome":
            connection.execute("ALTER TABLE product_command_receipt DISABLE TRIGGER USER")
            connection.execute(
                "UPDATE product_command_receipt SET outcome_id=%s WHERE command_id=%s", ("f" * 64, second)
            )
            connection.execute("ALTER TABLE product_command_receipt ENABLE TRIGGER USER")
        else:
            # Mutate both projections consistently: equality of copied intent is not proof of the book intent.
            connection.execute("ALTER TABLE product_command_admission DISABLE TRIGGER USER")
            connection.execute("ALTER TABLE product_command_receipt DISABLE TRIGGER USER")
            connection.execute("SET CONSTRAINTS ALL DEFERRED")
            connection.execute(
                "UPDATE product_command_admission SET command_fingerprint=%s WHERE command_id=%s", ("f" * 64, second)
            )
            connection.execute(
                "UPDATE product_command_receipt SET command_fingerprint=%s WHERE command_id=%s", ("f" * 64, second)
            )
            connection.execute("ALTER TABLE product_command_admission ENABLE TRIGGER USER")
            connection.execute("ALTER TABLE product_command_receipt ENABLE TRIGGER USER")
    assert run(native_probe, "watchlist-read") == {"error": "WATCHLIST_HISTORY_CORRUPT"}
    if mutation not in {"missing-head", "stale-head", "history-gap"}:
        assert run(native_probe, "watchlist-command", command_id=second) == {"error": "WATCHLIST_HISTORY_CORRUPT"}
    assert run(native_probe, "watchlist-save", expected_version=2, lists=()) == {"error": "WATCHLIST_HISTORY_CORRUPT"}


def test_actual_commit_ack_loss_preserves_one_revision_and_exact_command_query(
    native_probe: Path, watchlist_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = str(uuid4())
    with CommitAckCut(watchlist_db) as fault:
        with monkeypatch.context() as child:
            child.setenv("ONLYALPHA_POSTGRES_DSN", fault.dsn)
            assert run(native_probe, "watchlist-save", command_id=cid) == {"error": "WATCHLIST_UNAVAILABLE"}
        assert fault.done.is_set()
    assert run(native_probe, "watchlist-command", command_id=cid) == expected(1)
    assert run(native_probe, "watchlist-save", command_id=cid) == expected(1)
    with psycopg.connect(watchlist_db) as connection:
        assert connection.execute(
            "SELECT count(*) FROM watchlist_revision WHERE namespace_id=%s", (NS.value,)
        ).fetchone() == (1,)
    assert OnlyPostgresWatchlistStore(watchlist_db, NS).read() == OnlyWatchlistBook(1, (LIST,))


@pytest.mark.parametrize("empty", [False, True])
def test_original_outcomeless_intent_is_unknown_only_when_its_source_is_reconstructible(
    native_probe: Path, watchlist_db: str, empty: bool
) -> None:
    original = {
        "list_id": LIST.list_id,
        "name": LIST.name,
        "source": asdict(SOURCE),
        "instrument_ids": [] if empty else [LIST.members[0].instrument_id],
    }
    cid = OnlyProductCommandId(str(uuid4()))
    intent = only_canonical_fingerprint({"namespace_id": NS.value, "expected_version": 0, "lists": [original]})
    Commands(watchlist_db).admit_exact(
        OnlyProductCommandAdmissionV1(cid, OnlyProductCommandKind.SAVE_WATCHLISTS, intent)
    )
    lists = (replace(LIST, members=()) if empty else LIST,)
    assert run(native_probe, "watchlist-save", command_id=cid.value, lists=lists) == {
        "error": "WATCHLIST_COMMAND_CONFLICT" if empty else "WATCHLIST_COMMAND_UNKNOWN"
    }
    assert run(native_probe, "watchlist-command", command_id=cid.value) == {"error": "WATCHLIST_COMMAND_UNKNOWN"}
    assert run(native_probe, "watchlist-read") == expected(0, ())


def concurrent(probe: Path, commands: tuple[str, str], names: tuple[str, str]) -> list[dict[str, Any]]:
    children = [
        subprocess.Popen(
            [str(probe), "--barrier"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        for _ in commands
    ]
    try:
        for child in children:
            assert child.stdout is not None
            assert json.loads(child.stdout.readline()) == {"ready": True}
        for child, cid, name in zip(children, commands, names, strict=True):
            assert child.stdin is not None
            child.stdin.write(
                json.dumps(
                    {
                        "op": "watchlist-save",
                        "command_id": cid,
                        "namespace_id": NS.value,
                        "expected_version": 0,
                        "lists": [asdict(replace(LIST, name=name))],
                        "accepted_at": NOW.isoformat(),
                    }
                )
            )
            child.stdin.close()
            child.stdin = None
        result = []
        for child in children:
            stdout, stderr = child.communicate(timeout=20)
            assert child.returncode == 0, stderr
            result.append(cast(dict[str, Any], json.loads(stdout)))
        return result
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=20)


@pytest.mark.parametrize(
    "case", ["same-command-same-intent", "same-command-changed-intent", "different-command-same-version"]
)
def test_two_ready_connections_preserve_one_global_effect_and_no_overwrite(
    native_probe: Path, watchlist_db: str, case: str
) -> None:
    first = str(uuid4())
    second = str(uuid4()) if case == "different-command-same-version" else first
    names = ("甲", "甲" if case == "same-command-same-intent" else "乙")
    outcomes = concurrent(native_probe, (first, second), names)
    if case == "same-command-same-intent":
        assert outcomes == [expected(1, (replace(LIST, name="甲"),))] * 2
    else:
        success = [row for row in outcomes if "book" in row]
        assert len(success) == 1
        assert {
            "error": "WATCHLIST_VERSION_CONFLICT"
            if case == "different-command-same-version"
            else "WATCHLIST_COMMAND_CONFLICT"
        } in outcomes
    with psycopg.connect(watchlist_db) as connection:
        assert connection.execute(
            "SELECT count(*) FROM watchlist_revision WHERE namespace_id=%s", (NS.value,)
        ).fetchone() == (1,)
    assert run(native_probe, "watchlist-read") in outcomes


def insert_predecessor(connection: Any, cid: str) -> None:
    payload = asdict(OnlyWatchlistBook(1, (LIST,)))
    fingerprint = only_canonical_fingerprint({"namespace_id": NS.value, "book": payload})
    intent = only_canonical_fingerprint({"namespace_id": NS.value, "expected_version": 0, "lists": payload["lists"]})
    admission = OnlyProductCommandAdmissionV1(OnlyProductCommandId(cid), OnlyProductCommandKind.SAVE_WATCHLISTS, intent)
    Commands.insert_or_verify_admission(connection, admission)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("watchlists:" + NS.value,))
    connection.execute(
        "INSERT INTO watchlist_revision(namespace_id,version,fingerprint,book_json,command_id,representation_version) VALUES(%s,1,%s,%s,%s,2)",
        (NS.value, fingerprint, Jsonb(payload), cid),
    )
    connection.execute("INSERT INTO watchlist_head(namespace_id,version) VALUES(%s,1)", (NS.value,))
    Commands.insert_verified_receipt(
        connection,
        OnlyProductCommandReceipt(
            admission.command_id,
            admission.command_kind,
            intent,
            OnlyProductCommandOutcomeRef(OnlyProductCommandOutcomeKind.WATCHLIST_REVISION, fingerprint),
            NOW,
        ),
    )


@pytest.mark.parametrize("operation", ["watchlist-save", "watchlist-read", "namespace-contention"])
def test_database_lock_barriers_preserve_current_state_and_read_snapshot(
    native_probe: Path, watchlist_db: str, operation: str
) -> None:
    child: subprocess.Popen[str] | None = None
    predecessor = str(uuid4())
    contender = str(uuid4())
    try:
        with psycopg.connect(watchlist_db) as control:
            blocker = control.info.backend_pid
            if operation == "watchlist-save":
                # Admission/Receipt also own an existing global source-history
                # frontier lock. Prepare the predecessor in the canonical order;
                # a writer cannot hold that frontier while another advances it.
                insert_predecessor(control, predecessor)
                lock_kind = "transactionid"
            elif operation == "watchlist-read":
                control.execute("LOCK TABLE watchlist_head IN ACCESS EXCLUSIVE MODE")
                lock_kind = "relation"
            else:
                control.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("watchlists:" + NS.value,))
                lock_kind = "advisory"
            child = subprocess.Popen(
                [str(native_probe), "--pid-barrier"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert child.stdout is not None and child.stdin is not None
            ready = json.loads(child.stdout.readline())
            assert ready["ready"] is True
            child.stdin.write(
                json.dumps(
                    {
                        "op": "watchlist-save" if operation == "namespace-contention" else operation,
                        "command_id": contender,
                        "namespace_id": NS.value,
                        "expected_version": 0,
                        "lists": [asdict(LIST)],
                        "accepted_at": NOW.isoformat(),
                    }
                )
            )
            child.stdin.close()
            child.stdin = None
            wait_for_database_lock_barrier(watchlist_db, child, ready["backend_pid"], blocker, lock_kind)
            if operation == "watchlist-read":
                insert_predecessor(control, predecessor)
            # Exiting commits the predecessor and releases the exact held barrier.
        assert child is not None
        stdout, stderr = child.communicate(timeout=20)
        assert child.returncode == 0, stderr
        assert (
            json.loads(stdout)
            == {
                "watchlist-save": {"error": "WATCHLIST_VERSION_CONFLICT"},
                "watchlist-read": expected(0, ()),
                "namespace-contention": expected(1),
            }[operation]
        )
        admission = Commands(watchlist_db).load_admission(OnlyProductCommandId(contender))
        if operation == "namespace-contention":
            assert admission is not None and admission.command_kind is OnlyProductCommandKind.SAVE_WATCHLISTS
        else:
            assert admission is None
        assert run(native_probe, "watchlist-read") == expected(1)
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=20)


@pytest.mark.parametrize("existing", [False, True])
def test_receipt_insert_failure_rolls_back_new_admission_revision_and_head(
    native_probe: Path, watchlist_db: str, existing: bool
) -> None:
    owner = OnlyPostgresWatchlistStore(watchlist_db, NS)
    if existing:
        owner.save(str(uuid4()), 0, (LIST,))
    version = 1 if existing else 0
    cid = str(uuid4())
    with psycopg.connect(watchlist_db) as connection:
        before = connection.execute("SELECT * FROM watchlist_revision ORDER BY namespace_id,version").fetchall()
        source_before = connection.execute("SELECT * FROM research_source_history ORDER BY event_index").fetchall()
        frontier_before = connection.execute("SELECT * FROM research_source_history_frontier").fetchall()
        connection.execute(
            "CREATE FUNCTION reject_watchlist_receipt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.command_kind='SAVE_WATCHLISTS' THEN RAISE EXCEPTION 'controlled receipt failure'; END IF; RETURN NEW; END $$"
        )
        connection.execute(
            "CREATE TRIGGER reject_watchlist_receipt BEFORE INSERT ON product_command_receipt FOR EACH ROW EXECUTE FUNCTION reject_watchlist_receipt()"
        )
    assert run(native_probe, "watchlist-save", command_id=cid, expected_version=version, lists=()) == {
        "error": "WATCHLIST_UNAVAILABLE"
    }
    assert Commands(watchlist_db).load_admission(OnlyProductCommandId(cid)) is None
    assert run(native_probe, "watchlist-read") == expected(version, (LIST,) if existing else ())
    with psycopg.connect(watchlist_db) as connection:
        assert connection.execute("SELECT * FROM watchlist_revision ORDER BY namespace_id,version").fetchall() == before
        assert (
            connection.execute("SELECT * FROM research_source_history ORDER BY event_index").fetchall() == source_before
        )
        assert connection.execute("SELECT * FROM research_source_history_frontier").fetchall() == frontier_before
        assert connection.execute(
            "SELECT count(*) FROM product_command_receipt WHERE command_id=%s", (cid,)
        ).fetchone() == (0,)


def test_dangling_head_without_any_history_is_corrupt_not_empty(native_probe: Path, watchlist_db: str) -> None:
    with psycopg.connect(watchlist_db) as connection:
        connection.execute("ALTER TABLE watchlist_head DROP CONSTRAINT watchlist_head_namespace_id_version_fkey")
        connection.execute("INSERT INTO watchlist_head(namespace_id,version) VALUES(%s,1)", (NS.value,))
    assert run(native_probe, "watchlist-read") == {"error": "WATCHLIST_HISTORY_CORRUPT"}
    assert run(native_probe, "watchlist-save") == {"error": "WATCHLIST_HISTORY_CORRUPT"}


def test_count_equal_max_cannot_certify_history_containing_a_nonpositive_version(
    native_probe: Path, watchlist_db: str
) -> None:
    owner = OnlyPostgresWatchlistStore(watchlist_db, NS)
    owner.save(str(uuid4()), 0, (LIST,))
    owner.save(str(uuid4()), 1, (replace(LIST, name="趋势"),))
    with psycopg.connect(watchlist_db) as connection:
        connection.execute("ALTER TABLE watchlist_revision DISABLE TRIGGER watchlist_revision_immutable")
        connection.execute("ALTER TABLE watchlist_revision DROP CONSTRAINT watchlist_revision_version_check")
        connection.execute("UPDATE watchlist_revision SET version=0 WHERE namespace_id=%s AND version=1", (NS.value,))
        connection.execute("ALTER TABLE watchlist_revision ENABLE TRIGGER watchlist_revision_immutable")
        assert connection.execute(
            "SELECT count(*),max(version) FROM watchlist_revision WHERE namespace_id=%s", (NS.value,)
        ).fetchone() == (2, 2)
    assert run(native_probe, "watchlist-read") == {"error": "WATCHLIST_HISTORY_CORRUPT"}


def test_rehashed_original_empty_source_and_outcome_still_require_original_command_intent(
    native_probe: Path, watchlist_db: str
) -> None:
    cid, payload = insert_original(watchlist_db, empty=True)
    payload["lists"][0]["source"]["integration_id"] = "different-source"
    fingerprint = only_canonical_fingerprint({"namespace_id": NS.value, "book": payload})
    with psycopg.connect(watchlist_db) as connection:
        connection.execute("ALTER TABLE watchlist_revision DISABLE TRIGGER watchlist_revision_immutable")
        connection.execute("ALTER TABLE product_command_receipt DISABLE TRIGGER USER")
        connection.execute(
            "UPDATE watchlist_revision SET book_json=%s,fingerprint=%s WHERE command_id=%s",
            (Jsonb(payload), fingerprint, cid),
        )
        connection.execute("UPDATE product_command_receipt SET outcome_id=%s WHERE command_id=%s", (fingerprint, cid))
        connection.execute("ALTER TABLE watchlist_revision ENABLE TRIGGER watchlist_revision_immutable")
        connection.execute("ALTER TABLE product_command_receipt ENABLE TRIGGER USER")
    assert run(native_probe, "watchlist-read") == {"error": "WATCHLIST_HISTORY_CORRUPT"}
    assert run(native_probe, "watchlist-command", command_id=cid) == {"error": "WATCHLIST_HISTORY_CORRUPT"}


@pytest.mark.parametrize("primitive", [{"$serde_json::private::Number": "1"}, "1", True, 1.0])
def test_original_version_primitive_type_cannot_be_laundered_by_json_value_deserialization(
    native_probe: Path, watchlist_db: str, primitive: object
) -> None:
    from onlyalpha.application.watchlists import OnlyWatchlistError

    cid = str(uuid4())
    owner = OnlyPostgresWatchlistStore(watchlist_db, NS)
    owner.save(cid, 0, (LIST,))
    with psycopg.connect(watchlist_db) as connection:
        connection.execute("ALTER TABLE watchlist_revision DISABLE TRIGGER watchlist_revision_immutable")
        connection.execute(
            "UPDATE watchlist_revision SET book_json=jsonb_set(book_json,'{version}',%s) WHERE command_id=%s",
            (Jsonb(primitive), cid),
        )
        connection.execute("ALTER TABLE watchlist_revision ENABLE TRIGGER watchlist_revision_immutable")
    # Keep the original numerical book hash/Admission/Receipt. Raw object/string/
    # boolean/fractional types are not a canonical integer, even if a decoder can
    # reinterpret the object as the same number.
    with pytest.raises(OnlyWatchlistError, match="WATCHLIST_HISTORY_CORRUPT"):
        owner.read()
    assert run(native_probe, "watchlist-read") == {"error": "WATCHLIST_HISTORY_CORRUPT"}
    assert run(native_probe, "watchlist-command", command_id=cid) == {"error": "WATCHLIST_HISTORY_CORRUPT"}


@pytest.mark.parametrize(
    "path,original",
    [
        ("{lists,0,name}", "日常"),
        ("{lists,0,members,0,source,integration_id}", "source"),
        ("{lists,0,members,0,source}", asdict(SOURCE)),
    ],
)
@pytest.mark.parametrize("representation", [1, 2])
def test_raw_value_marker_cannot_reinterpret_original_watchlist_history(
    native_probe: Path, watchlist_db: str, path: str, original: object, representation: int
) -> None:
    from onlyalpha.application.watchlists import OnlyWatchlistError

    owner = OnlyPostgresWatchlistStore(watchlist_db, NS)
    if representation == 1:
        cid, _payload = insert_original(watchlist_db, empty=False)
        path = path.replace(",members,0,source", ",source")
    else:
        cid = str(uuid4())
        owner.save(cid, 0, (LIST,))
    marker = {"$serde_json::private::RawValue": json.dumps(original, ensure_ascii=False)}
    with psycopg.connect(watchlist_db) as connection:
        connection.execute("ALTER TABLE watchlist_revision DISABLE TRIGGER watchlist_revision_immutable")
        connection.execute(
            "UPDATE watchlist_revision SET book_json=jsonb_set(book_json,%s::text[],%s) WHERE command_id=%s",
            (path, Jsonb(marker), cid),
        )
        connection.execute("ALTER TABLE watchlist_revision ENABLE TRIGGER watchlist_revision_immutable")
    with pytest.raises(OnlyWatchlistError, match="WATCHLIST_HISTORY_CORRUPT"):
        owner.read()
    assert run(native_probe, "watchlist-read") == {"error": "WATCHLIST_HISTORY_CORRUPT"}
    assert run(native_probe, "watchlist-command", command_id=cid) == {"error": "WATCHLIST_HISTORY_CORRUPT"}
    assert run(native_probe, "watchlist-save", command_id=cid) == {"error": "WATCHLIST_HISTORY_CORRUPT"}
