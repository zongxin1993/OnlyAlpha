"""Native Watchlist persistence over existing canonical PG facts, not UI acceptance."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from packages.backend.tests.application.test_schema_postgres import migration_backend, schema_db
from packages.backend.tests.postgres_link import CommitAckCut, wait_for_database_lock_barrier

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]
NOW = datetime(2026, 8, 27, tzinfo=UTC)
NS = "b52eb762-34cf-47d4-8cca-56ef93f0d2ac"
SOURCE = {
    "integration_id": "source",
    "integration_revision_fingerprint": "a" * 64,
    "expected_type_id": "test.market_data",
}
LIST = {
    "list_id": "0926c6a2-0cb8-47a5-8d94-cdb89b336182",
    "name": "日常",
    "members": [{"source": dict(SOURCE), "instrument_id": "BTCUSDT.BINANCE"}],
}
__all__ = ["migration_backend", "schema_db"]


@pytest.fixture
def watchlist_db(schema_db: str) -> str:
    return schema_db


def run(
    probe: Path,
    operation: str,
    *,
    command_id: str | None = None,
    expected_version: int = 0,
    lists: tuple[dict[str, Any], ...] = (LIST,),
    namespace: str = NS,
) -> dict[str, Any]:
    payload = {
        "op": operation,
        "command_id": command_id or str(uuid4()),
        "namespace_id": namespace,
        "expected_version": expected_version,
        "lists": list(lists),
        "accepted_at": NOW.isoformat(),
    }
    result = subprocess.run(
        [str(probe)], input=json.dumps(payload), text=True, capture_output=True, timeout=20, check=False
    )
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


def expected(version: int, lists: tuple[dict[str, Any], ...] = (LIST,)) -> dict[str, object]:
    return {"book": {"version": version, "lists": list(lists)}}


def test_native_history_reader_and_current_writer_exact_cross_process_replay(
    native_probe: Path, watchlist_db: str
) -> None:
    assert run(native_probe, "watchlist-read") == expected(0, ())
    original = str(uuid4())
    first = run(native_probe, "watchlist-save", command_id=original)
    assert first == expected(1)
    assert run(native_probe, "watchlist-read") == expected(1)
    assert run(native_probe, "watchlist-command", command_id=original) == expected(1)
    assert run(native_probe, "watchlist-save", command_id=original) == expected(1)
    changed = {**LIST, "name": "趋势"}
    second = str(uuid4())
    assert run(native_probe, "watchlist-save", command_id=second, expected_version=1, lists=(changed,)) == expected(
        2, (changed,)
    )
    assert run(native_probe, "watchlist-read") == expected(2, (changed,))
    assert run(native_probe, "watchlist-command", command_id=second) == expected(2, (changed,))
    assert run(native_probe, "watchlist-save", command_id=second, expected_version=1, lists=(changed,)) == expected(
        2, (changed,)
    )
    assert run(native_probe, "watchlist-command", command_id=original) == expected(1)
    assert run(native_probe, "watchlist-save", command_id=original) == expected(1)
    assert run(native_probe, "watchlist-command", command_id=original) == first
    assert run(native_probe, "watchlist-save", command_id=original, lists=(changed,)) == {
        "error": "WATCHLIST_COMMAND_CONFLICT"
    }
    losing = str(uuid4())
    assert run(native_probe, "watchlist-save", command_id=losing) == {"error": "WATCHLIST_VERSION_CONFLICT"}
    assert run(native_probe, "load-admission", command_id=losing)["admission"] is None
    assert run(native_probe, "watchlist-read", namespace=str(uuid4())) == expected(0, ())
    assert run(native_probe, "watchlist-command", command_id=original, namespace=str(uuid4())) == {
        "error": "WATCHLIST_HISTORY_CORRUPT"
    }


def fixture_record(
    probe: Path, cid: str, payload: dict[str, Any], *, representation: int = 2, kind: str = "SAVE_WATCHLISTS"
) -> dict[str, Any]:
    request = {
        "op": "watchlist-fixture-record",
        "command_id": cid,
        "namespace_id": NS,
        "book": payload,
        "representation": representation,
        "expected_version": 0,
        "kind": kind,
        "accepted_at": NOW.isoformat(),
    }
    result = subprocess.run(
        [str(probe)], input=json.dumps(request), text=True, capture_output=True, timeout=20, check=False
    )
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


def insert_admission(connection: Any, records: dict[str, Any]) -> None:
    # Values originate from current Rust constructors; real SQL triggers publish source history.
    a = records["admission"]
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (a["command_id"],))
    connection.execute(
        "INSERT INTO product_command_admission(command_id,command_kind,command_fingerprint,schema_version) VALUES(%s,%s,%s,%s)",
        (a["command_id"], a["command_kind"], a["command_fingerprint"], a["schema_version"]),
    )


def insert_receipt(connection: Any, records: dict[str, Any]) -> None:
    r = records["receipt"]
    columns = [
        "command_id",
        "command_kind",
        "command_fingerprint",
        "outcome_kind",
        "outcome_id",
        "accepted_at",
        "schema_version",
    ]
    connection.execute(
        "INSERT INTO product_command_receipt("
        + ",".join(columns)
        + ") VALUES("
        + ",".join(["%s"] * len(columns))
        + ")",
        [r[key] for key in columns],
    )


def insert_original(probe: Path, dsn: str, *, empty: bool) -> tuple[str, dict[str, Any]]:
    payload: dict[str, Any] = {
        "version": 1,
        "lists": [
            {
                "list_id": LIST["list_id"],
                "name": LIST["name"],
                "source": dict(SOURCE),
                "instrument_ids": [] if empty else [LIST["members"][0]["instrument_id"]],
            }
        ],
    }
    cid = str(uuid4())
    records = fixture_record(probe, cid, payload, representation=1)
    with psycopg.connect(dsn) as connection:
        insert_admission(connection, records)
        connection.execute(
            "INSERT INTO watchlist_revision(namespace_id,version,fingerprint,book_json,command_id,representation_version) VALUES(%s,1,%s,%s,%s,1)",
            (NS, records["fingerprint"], Jsonb(payload), cid),
        )
        connection.execute("INSERT INTO watchlist_head(namespace_id,version) VALUES(%s,1)", (NS,))
        insert_receipt(connection, records)
    return cid, payload


@pytest.mark.parametrize("empty", [False, True])
def test_original_immutable_history_is_verified_before_projection_and_never_rewritten(
    native_probe: Path, watchlist_db: str, empty: bool
) -> None:
    cid, _payload = insert_original(native_probe, watchlist_db, empty=empty)
    lists = ({**LIST, "members": []} if empty else LIST,)
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
    assert run(native_probe, "watchlist-read") == expected(2)


def test_admission_only_is_unknown_and_changed_or_foreign_intent_never_executes(
    native_probe: Path, watchlist_db: str
) -> None:
    for family in ["CREATE_INTEGRATION", "SAVE_WATCHLISTS"]:
        cid = str(uuid4())
        records = fixture_record(native_probe, cid, {"version": 0, "lists": [LIST]}, kind=family)
        with psycopg.connect(watchlist_db) as connection:
            insert_admission(connection, records)
        error = "WATCHLIST_COMMAND_UNKNOWN" if family == "SAVE_WATCHLISTS" else "WATCHLIST_COMMAND_CONFLICT"
        assert run(native_probe, "watchlist-command", command_id=cid) == {"error": error}
        assert run(native_probe, "watchlist-save", command_id=cid) == {"error": error}
        assert run(native_probe, "watchlist-save", command_id=cid, lists=()) == {"error": "WATCHLIST_COMMAND_CONFLICT"}
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
    first, second = str(uuid4()), str(uuid4())
    assert run(native_probe, "watchlist-save", command_id=first) == expected(1)
    assert run(
        native_probe, "watchlist-save", command_id=second, expected_version=1, lists=({**LIST, "name": "趋势"},)
    ) == expected(2, ({**LIST, "name": "趋势"},))
    with psycopg.connect(watchlist_db) as connection:
        if mutation == "missing-head":
            connection.execute("DELETE FROM watchlist_head WHERE namespace_id=%s", (NS,))
        elif mutation == "stale-head":
            connection.execute("UPDATE watchlist_head SET version=1 WHERE namespace_id=%s", (NS,))
        elif mutation == "history-gap":
            connection.execute("ALTER TABLE watchlist_revision DISABLE TRIGGER watchlist_revision_immutable")
            connection.execute("DELETE FROM watchlist_revision WHERE namespace_id=%s AND version=1", (NS,))
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
            "SELECT count(*) FROM watchlist_revision WHERE namespace_id=%s", (NS,)
        ).fetchone() == (1,)
    assert run(native_probe, "watchlist-read") == expected(1)


@pytest.mark.parametrize("empty", [False, True])
def test_original_outcomeless_intent_is_unknown_only_when_its_source_is_reconstructible(
    native_probe: Path, watchlist_db: str, empty: bool
) -> None:
    original = {
        "list_id": LIST["list_id"],
        "name": LIST["name"],
        "source": dict(SOURCE),
        "instrument_ids": [] if empty else [LIST["members"][0]["instrument_id"]],
    }
    cid = str(uuid4())
    records = fixture_record(native_probe, cid, {"version": 1, "lists": [original]}, representation=1)
    with psycopg.connect(watchlist_db) as connection:
        insert_admission(connection, records)
    lists = ({**LIST, "members": []} if empty else LIST,)
    assert run(native_probe, "watchlist-save", command_id=cid, lists=lists) == {
        "error": "WATCHLIST_COMMAND_CONFLICT" if empty else "WATCHLIST_COMMAND_UNKNOWN"
    }
    assert run(native_probe, "watchlist-command", command_id=cid) == {"error": "WATCHLIST_COMMAND_UNKNOWN"}
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
                        "namespace_id": NS,
                        "expected_version": 0,
                        "lists": [{**LIST, "name": name}],
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
        assert outcomes == [expected(1, ({**LIST, "name": "甲"},))] * 2
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
            "SELECT count(*) FROM watchlist_revision WHERE namespace_id=%s", (NS,)
        ).fetchone() == (1,)
    assert run(native_probe, "watchlist-read") in outcomes


def insert_predecessor(probe: Path, connection: Any, cid: str) -> None:
    payload = {"version": 1, "lists": [LIST]}
    records = fixture_record(probe, cid, payload)
    insert_admission(connection, records)
    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("watchlists:" + NS,))
    connection.execute(
        "INSERT INTO watchlist_revision(namespace_id,version,fingerprint,book_json,command_id,representation_version) VALUES(%s,1,%s,%s,%s,2)",
        (NS, records["fingerprint"], Jsonb(payload), cid),
    )
    connection.execute("INSERT INTO watchlist_head(namespace_id,version) VALUES(%s,1)", (NS,))
    insert_receipt(connection, records)


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
                insert_predecessor(native_probe, control, predecessor)
                lock_kind = "transactionid"
            elif operation == "watchlist-read":
                control.execute("LOCK TABLE watchlist_head IN ACCESS EXCLUSIVE MODE")
                lock_kind = "relation"
            else:
                control.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("watchlists:" + NS,))
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
                        "namespace_id": NS,
                        "expected_version": 0,
                        "lists": [LIST],
                        "accepted_at": NOW.isoformat(),
                    }
                )
            )
            child.stdin.close()
            child.stdin = None
            wait_for_database_lock_barrier(watchlist_db, child, ready["backend_pid"], blocker, lock_kind)
            if operation == "watchlist-read":
                insert_predecessor(native_probe, control, predecessor)
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
        admission = run(native_probe, "load-admission", command_id=contender)["admission"]
        if operation == "namespace-contention":
            assert admission is not None and admission["command_kind"] == "SAVE_WATCHLISTS"
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
    if existing:
        assert run(native_probe, "watchlist-save") == expected(1)
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
    assert run(native_probe, "load-admission", command_id=cid)["admission"] is None
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
        connection.execute("INSERT INTO watchlist_head(namespace_id,version) VALUES(%s,1)", (NS,))
    assert run(native_probe, "watchlist-read") == {"error": "WATCHLIST_HISTORY_CORRUPT"}
    assert run(native_probe, "watchlist-save") == {"error": "WATCHLIST_HISTORY_CORRUPT"}


def test_count_equal_max_cannot_certify_history_containing_a_nonpositive_version(
    native_probe: Path, watchlist_db: str
) -> None:
    assert run(native_probe, "watchlist-save") == expected(1)
    assert run(native_probe, "watchlist-save", expected_version=1, lists=({**LIST, "name": "趋势"},)) == expected(
        2, ({**LIST, "name": "趋势"},)
    )
    with psycopg.connect(watchlist_db) as connection:
        connection.execute("ALTER TABLE watchlist_revision DISABLE TRIGGER watchlist_revision_immutable")
        connection.execute("ALTER TABLE watchlist_revision DROP CONSTRAINT watchlist_revision_version_check")
        connection.execute("UPDATE watchlist_revision SET version=0 WHERE namespace_id=%s AND version=1", (NS,))
        connection.execute("ALTER TABLE watchlist_revision ENABLE TRIGGER watchlist_revision_immutable")
        assert connection.execute(
            "SELECT count(*),max(version) FROM watchlist_revision WHERE namespace_id=%s", (NS,)
        ).fetchone() == (2, 2)
    assert run(native_probe, "watchlist-read") == {"error": "WATCHLIST_HISTORY_CORRUPT"}


def test_rehashed_original_empty_source_and_outcome_still_require_original_command_intent(
    native_probe: Path, watchlist_db: str
) -> None:
    cid, payload = insert_original(native_probe, watchlist_db, empty=True)
    payload["lists"][0]["source"]["integration_id"] = "different-source"
    fingerprint = fixture_record(native_probe, cid, payload, representation=1)["fingerprint"]
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
    cid = str(uuid4())
    assert run(native_probe, "watchlist-save", command_id=cid) == expected(1)
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
    # A second process independently reopens the exact malformed retained history.
    assert run(native_probe, "watchlist-read") == {"error": "WATCHLIST_HISTORY_CORRUPT"}
    assert run(native_probe, "watchlist-read") == {"error": "WATCHLIST_HISTORY_CORRUPT"}
    assert run(native_probe, "watchlist-command", command_id=cid) == {"error": "WATCHLIST_HISTORY_CORRUPT"}


@pytest.mark.parametrize(
    "path,original",
    [
        ("{lists,0,name}", "日常"),
        ("{lists,0,members,0,source,integration_id}", "source"),
        ("{lists,0,members,0,source}", SOURCE),
    ],
)
@pytest.mark.parametrize("representation", [1, 2])
def test_raw_value_marker_cannot_reinterpret_original_watchlist_history(
    native_probe: Path, watchlist_db: str, path: str, original: object, representation: int
) -> None:
    if representation == 1:
        cid, _payload = insert_original(native_probe, watchlist_db, empty=False)
        path = path.replace(",members,0,source", ",source")
    else:
        cid = str(uuid4())
        assert run(native_probe, "watchlist-save", command_id=cid) == expected(1)
    marker = {"$serde_json::private::RawValue": json.dumps(original, ensure_ascii=False)}
    with psycopg.connect(watchlist_db) as connection:
        connection.execute("ALTER TABLE watchlist_revision DISABLE TRIGGER watchlist_revision_immutable")
        connection.execute(
            "UPDATE watchlist_revision SET book_json=jsonb_set(book_json,%s::text[],%s) WHERE command_id=%s",
            (path, Jsonb(marker), cid),
        )
        connection.execute("ALTER TABLE watchlist_revision ENABLE TRIGGER watchlist_revision_immutable")
    # A second process independently reopens the exact malformed retained history.
    assert run(native_probe, "watchlist-read") == {"error": "WATCHLIST_HISTORY_CORRUPT"}
    assert run(native_probe, "watchlist-read") == {"error": "WATCHLIST_HISTORY_CORRUPT"}
    assert run(native_probe, "watchlist-command", command_id=cid) == {"error": "WATCHLIST_HISTORY_CORRUPT"}
    assert run(native_probe, "watchlist-save", command_id=cid) == {"error": "WATCHLIST_HISTORY_CORRUPT"}
