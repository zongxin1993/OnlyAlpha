"""Native canonical Integration mutations: technical evidence, never Shipping UI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from .support.integration import NOW, call, create_request, lifecycle_request, replay_request
from .support.integration_rows import draft_bindings, draft_row, integration_row
from .test_schema_postgres import migration_backend as migration_backend
from .test_schema_postgres import schema_db as schema_db

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]


@pytest.fixture
def integration_db(schema_db: str) -> str:
    return schema_db


def test_create_atomic_empty_draft_and_independent_sql_readback_and_catalog_independent_replay(
    native_probe: Path, integration_db: str
) -> None:
    request = create_request()
    assert call(native_probe, replay_request(request, native_probe)) == {"result": None}
    result = call(native_probe, request)
    assert result["replayed"] is False
    admission = result["result"]["admission"]
    assert admission["command_fingerprint"] == replay_request(request, native_probe)["fingerprint"]
    assert result["result"]["receipt"] == {
        "outcome_kind": "INTEGRATION",
        "outcome_id": request["integration_id"],
        "accepted_at": "2026-09-20T00:00:00Z",
    }

    ident = request["integration_id"]
    owner = integration_row(integration_db, ident)
    draft = draft_row(integration_db, ident)
    assert owner["type_id"] == request["type_id"] and owner["lifecycle_state"] == "ACTIVE"
    assert owner["created_at"] == owner["updated_at"] == NOW
    assert draft["draft_version"] == 1 and dict(draft["public_configuration_document"]) == {}
    assert draft["probe_configuration_document"] is None and draft["base_revision_fingerprint"] is None
    assert draft["type_descriptor_document"] == json.loads(request["descriptor"])
    assert draft_bindings(integration_db, ident) == ()
    assert call(native_probe, replay_request(request, native_probe)) == dict(result, replayed=True)
    assert call(native_probe, request) == dict(result, replayed=True)


def test_same_command_different_intent_and_different_command_existing_owner_roll_back(
    native_probe: Path, integration_db: str
) -> None:
    request = create_request()
    result = call(native_probe, request)
    assert "error" not in result
    assert call(native_probe, dict(request, display_name="Changed")) == {"error": "PRODUCT_COMMAND_CONFLICT"}
    assert call(
        native_probe, dict(lifecycle_request(request, "ACTIVE", "DISABLED"), command_id=request["command_id"])
    ) == {"error": "PRODUCT_COMMAND_CONFLICT"}
    another = dict(request, command_id=str(uuid4()))
    assert call(native_probe, another) == {"error": "INTEGRATION_PERSISTENCE_CONFLICT"}
    with psycopg.connect(integration_db) as connection:
        assert connection.execute(
            "SELECT count(*) FROM product_command_admission WHERE command_id=%s", (another["command_id"],)
        ).fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM integration_draft").fetchone() == (1,)


@pytest.mark.parametrize(
    "path", [("ACTIVE", "DISABLED", "ACTIVE", "ARCHIVED"), ("ACTIVE", "DISABLED", "ARCHIVED"), ("ACTIVE", "ARCHIVED")]
)
def test_lifecycle_allowed_edges_archive_final_and_old_replay_after_later_progress(
    native_probe: Path, integration_db: str, path: tuple[str, ...]
) -> None:
    request = create_request()
    created = call(native_probe, request)
    commands = []
    for before, after in zip(path, path[1:], strict=False):
        command = lifecycle_request(request, before, after)
        result = call(native_probe, command)
        assert result["replayed"] is False
        assert (
            result["result"]["admission"]["command_fingerprint"] == replay_request(command, native_probe)["fingerprint"]
        )
        commands.append((command, result))
    owner = integration_row(integration_db, request["integration_id"])
    assert owner["lifecycle_state"] == "ARCHIVED"
    assert call(native_probe, replay_request(request, native_probe)) == dict(created, replayed=True)
    for command, result in commands:
        assert call(native_probe, command) == dict(result, replayed=True)
    for target in ["ACTIVE", "DISABLED", "ARCHIVED"]:
        rejected = lifecycle_request(request, "ARCHIVED", target)
        assert call(native_probe, rejected) == {"error": "INTEGRATION_LIFECYCLE_CONFLICT"}
        with psycopg.connect(integration_db) as connection:
            assert connection.execute(
                "SELECT count(*) FROM product_command_admission WHERE command_id=%s", (rejected["command_id"],)
            ).fetchone() == (0,)


def test_admission_only_unknown_and_dangling_receipt_never_create_effect(
    native_probe: Path, integration_db: str
) -> None:
    request = create_request()
    replay = replay_request(request, native_probe)
    admitted = dict(replay, op="admit")
    assert call(native_probe, admitted) == {"result": "CREATED"}
    assert call(native_probe, request) == {"error": "PRODUCT_COMMAND_OUTCOME_UNKNOWN"}
    assert call(native_probe, replay) == {"error": "PRODUCT_COMMAND_OUTCOME_UNKNOWN"}
    assert call(native_probe, dict(request, display_name="Changed")) == {"error": "PRODUCT_COMMAND_CONFLICT"}
    forged = dict(
        replay,
        op="receipt",
        outcome_kind="INTEGRATION",
        outcome_id=request["integration_id"],
        accepted_at=request["accepted_at"],
    )
    assert call(native_probe, forged) == {"result": "CREATED"}
    assert call(native_probe, replay) == {"error": "PRODUCT_COMMAND_RECEIPT_CORRUPT"}
    with psycopg.connect(integration_db) as connection:
        assert connection.execute("SELECT count(*) FROM integration").fetchone() == (0,)


@pytest.mark.parametrize("existing", [False, True])
def test_receipt_failure_rolls_back_head_draft_admission_and_source_frontier(
    native_probe: Path, integration_db: str, existing: bool
) -> None:
    request = create_request()
    if existing:
        assert "error" not in call(native_probe, request)
        request = lifecycle_request(request, "ACTIVE", "DISABLED")
    tables = ["integration", "integration_draft", "product_command_admission", "product_command_receipt"]
    with psycopg.connect(integration_db) as connection:
        rows_before = {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
        before = connection.execute("SELECT * FROM research_source_history ORDER BY event_index").fetchall()
        frontier = connection.execute("SELECT * FROM research_source_history_frontier").fetchall()
        connection.execute(
            "CREATE FUNCTION reject_integration_receipt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'controlled receipt failure'; END $$"
        )
        connection.execute(
            "CREATE TRIGGER reject_integration_receipt BEFORE INSERT ON product_command_receipt FOR EACH ROW EXECUTE FUNCTION reject_integration_receipt()"
        )
    assert call(native_probe, request) == {"error": "INTEGRATION_PERSISTENCE_UNAVAILABLE"}
    with psycopg.connect(integration_db) as connection:
        for table in tables:
            assert connection.execute(f"SELECT * FROM {table}").fetchall() == rows_before[table]
        assert connection.execute("SELECT * FROM research_source_history ORDER BY event_index").fetchall() == before
        assert connection.execute("SELECT * FROM research_source_history_frontier").fetchall() == frontier


@pytest.mark.parametrize("expected,target", [("ACTIVE", "ACTIVE"), ("DISABLED", "ACTIVE"), ("ARCHIVED", "DISABLED")])
def test_stale_or_noop_lifecycle_never_reserves_command(
    native_probe: Path, integration_db: str, expected: str, target: str
) -> None:
    request = create_request()
    assert "error" not in call(native_probe, request)
    mutation = lifecycle_request(request, expected, target)
    assert call(native_probe, mutation) == {"error": "INTEGRATION_LIFECYCLE_CONFLICT"}
    assert call(native_probe, replay_request(mutation, native_probe)) == {"result": None}


@pytest.mark.parametrize("same_command", [True, False])
def test_concurrent_create_at_observed_database_lock_keeps_one_owner(
    native_probe: Path, integration_db: str, same_command: bool
) -> None:
    from packages.backend.tests.postgres_link import wait_for_database_lock_barrier

    request = create_request()
    contender = dict(request) if same_command else dict(request, command_id=str(uuid4()))
    children: list[subprocess.Popen[str]] = []
    pids: list[int] = []
    try:
        # Connect both children before holding a lock with the production budget.
        for _ in range(2):
            child = subprocess.Popen(
                [str(native_probe), "--pid-barrier"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            children.append(child)
            assert child.stdout is not None
            ready = json.loads(child.stdout.readline())
            assert ready["ready"] is True
            pids.append(ready["backend_pid"])
        with psycopg.connect(integration_db) as control:
            blocker = control.info.backend_pid
            if same_command:
                control.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (request["command_id"],))
            else:
                control.execute("SELECT * FROM research_source_history_frontier FOR UPDATE")
            for index, (child, command) in enumerate(zip(children, [request, contender], strict=True)):
                assert child.stdin is not None
                child.stdin.write(json.dumps(command))
                child.stdin.close()
                child.stdin = None
                # The second updater queues on the first updater's tuple lock;
                # waiting for it on the control transaction instead would keep
                # the first operation blocked until its real lock budget expires.
                wait_for_database_lock_barrier(
                    integration_db,
                    child,
                    pids[index],
                    blocker if same_command or index == 0 else pids[0],
                    "advisory" if same_command else "transactionid" if index == 0 else "tuple",
                )
        results = []
        for child in children:
            stdout, stderr = child.communicate(timeout=20)
            assert child.returncode == 0, stderr
            results.append(json.loads(stdout))
        if same_command:
            assert sorted(result["replayed"] for result in results) == [False, True]
            assert results[0]["result"] == results[1]["result"]
        else:
            assert sum("result" in result for result in results) == 1
            assert {"error": "INTEGRATION_PERSISTENCE_CONFLICT"} in results
        with psycopg.connect(integration_db) as connection:
            for table in ["integration", "integration_draft", "product_command_admission", "product_command_receipt"]:
                assert connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (1,)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=20)


def test_actual_commit_ack_loss_keeps_uncertainty_then_recovers_one_exact_effect(
    native_probe: Path, integration_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.backend.tests.postgres_link import CommitAckCut

    request = create_request()
    with CommitAckCut(integration_db) as fault:
        with monkeypatch.context() as child_configuration:
            child_configuration.setenv("ONLYALPHA_POSTGRES_DSN", fault.dsn)
            assert call(native_probe, request) == {"error": "INTEGRATION_PERSISTENCE_UNAVAILABLE"}
        assert fault.done.is_set(), "must observe the server's actual COMMIT before cutting its acknowledgement"
    recovered = call(native_probe, replay_request(request, native_probe))
    assert recovered["replayed"] is True
    assert call(native_probe, request) == recovered
    with psycopg.connect(integration_db) as connection:
        for table in ["integration", "integration_draft", "product_command_admission", "product_command_receipt"]:
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (1,)


def test_existing_native_receipt_replays_in_a_fresh_process_without_plugin_lookup(
    native_probe: Path, integration_db: str
) -> None:
    from .test_integration_postgres import descriptor

    desc = descriptor()
    request = create_request()
    request["type_id"] = desc["type_id"]
    request["descriptor"] = json.dumps(desc)
    replay = replay_request(request, native_probe)
    accepted = call(native_probe, request)
    assert accepted["replayed"] is False
    result = call(native_probe, replay)
    assert result["replayed"] is True
    assert (
        result["result"]["admission"]["command_fingerprint"] == accepted["result"]["admission"]["command_fingerprint"]
    )
    assert result["result"]["receipt"]["outcome_id"] == accepted["result"]["receipt"]["outcome_id"]
    assert call(native_probe, request) == result
