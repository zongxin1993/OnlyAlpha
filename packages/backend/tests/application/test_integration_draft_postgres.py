"""Native mutable Draft authority, never a Shipping UI acceptance shortcut."""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest

from onlyalpha.application.integration_configuration import OnlyIntegrationId, only_integration_json_document
from onlyalpha.persistence.postgres.integration_store import OnlyPostgresIntegrationStore
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority

from .support.integration import call, create_request, edit, lifecycle_request, replay_request, reset

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]


@pytest.fixture
def integration_db(postgres_dsn: str) -> str:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    return postgres_dsn


def test_update_then_reset_and_old_replay_preserve_exact_identity(native_probe: Path, integration_db: str) -> None:
    request = create_request()
    assert "error" not in call(native_probe, request)
    update = edit(request, probe='{"instrument":"ETHUSDT"}')
    accepted = call(native_probe, update)
    assert accepted["replayed"] is False
    assert accepted["result"]["admission"]["command_fingerprint"] == replay_request(update)["fingerprint"]
    owner = OnlyPostgresIntegrationStore(integration_db)
    id = OnlyIntegrationId(request["integration_id"])
    draft = owner.load_draft(id)
    assert draft.draft_version == 2 and dict(draft.public_configuration_document) == {"count": 7, "ratio": 0}
    assert dict(draft.probe_configuration_document or {}) == {"instrument": "ETHUSDT"}
    assert draft.base_revision_fingerprint is None
    assert call(native_probe, update) == dict(accepted, replayed=True)
    reset_command = reset(request, 2)
    reset_result = call(native_probe, reset_command)
    assert reset_result["replayed"] is False
    draft = owner.load_draft(id)
    assert (
        draft.draft_version == 3
        and dict(draft.public_configuration_document) == {}
        and draft.probe_configuration_document is None
    )
    assert call(native_probe, replay_request(update)) == dict(accepted, replayed=True)
    assert call(native_probe, reset_command) == dict(reset_result, replayed=True)
    assert call(native_probe, dict(update, expected_version=3)) == {"error": "PRODUCT_COMMAND_CONFLICT"}


@pytest.mark.parametrize("case", ["stale", "type_changed", "unknown", "secret", "bad_probe", "archived", "rows"])
def test_invalid_update_keeps_previous_draft_and_has_no_admission(
    native_probe: Path, integration_db: str, case: str
) -> None:
    request = create_request()
    assert "error" not in call(native_probe, request)
    command = edit(request)
    expected = "INTEGRATION_CONFIGURATION_INVALID"
    if case == "stale":
        command["expected_version"] = 2
        expected = "INTEGRATION_DRAFT_VERSION_CONFLICT"
    elif case == "type_changed":
        descriptor = json.loads(command["descriptor"])
        descriptor["implementation_version"] = "2.0.0"
        command["descriptor"] = json.dumps(descriptor)
        expected = "INTEGRATION_TYPE_CHANGED"
    elif case == "unknown":
        command["public"] = '{"unknown":1}'
    elif case == "secret":
        command["public"] = '{"api_key":"controlled-test-only"}'
    elif case == "bad_probe":
        command["probe"] = '{"other":1}'
        expected = "INTEGRATION_PROBE_CONFIGURATION_INVALID"
    elif case == "archived":
        assert "error" not in call(native_probe, lifecycle_request(request, "ACTIVE", "ARCHIVED"))
        expected = "INTEGRATION_ARCHIVED"
    else:
        command["rows"] = 1
        expected = "INTEGRATION_PERSISTENCE_UNAVAILABLE"
    owner = OnlyPostgresIntegrationStore(integration_db)
    id = OnlyIntegrationId(request["integration_id"])
    before = owner.load_draft(id)
    assert call(native_probe, command) == {"error": expected}
    assert owner.load_draft(id) == before
    assert call(native_probe, replay_request(command)) == {"result": None}


@pytest.mark.parametrize("action", ["update", "reset"])
def test_existing_bindings_and_history_survive_update_or_only_draft_bindings_clear_on_reset(
    native_probe: Path, integration_db: str, action: str
) -> None:
    from .test_integration_postgres import descriptor, populate

    ident = populate(integration_db)
    desc = descriptor()
    request = create_request()
    request.update(
        integration_id=ident,
        type_id=desc.type_id.value,
        descriptor=json.dumps(only_integration_json_document(desc.to_dict(include_fingerprint=False))),
    )
    owner = OnlyPostgresIntegrationStore(integration_db)
    id = OnlyIntegrationId(ident)
    before = owner.load_draft(id)
    bindings = owner.load_draft_secret_bindings(id)
    with psycopg.connect(integration_db) as connection:
        # Preserve original bindings across current credential rotation.
        connection.execute("UPDATE product_credential SET generation=2")
        history = connection.execute("SELECT * FROM integration_revision ORDER BY revision_sequence").fetchall()
        credentials = connection.execute("SELECT * FROM product_credential ORDER BY credential_id").fetchall()
        published = connection.execute(
            "SELECT * FROM integration_revision_secret_binding ORDER BY revision_fingerprint,field_id"
        ).fetchall()
    if action == "update":
        command = edit(
            request,
            version=before.draft_version,
            public='{"ratio":1.2500,"weights":{"$serde_json::private::Number":1}}',
        )
    else:
        command = reset(request, before.draft_version)
        changed = json.loads(command["descriptor"])
        changed["implementation_version"] = "2.0.0"
        command["descriptor"] = json.dumps(changed)
    result = call(native_probe, command)
    assert result["replayed"] is False
    after = owner.load_draft(id)
    assert after.draft_version == before.draft_version + 1 and after.created_at == before.created_at
    if action == "update":
        assert after.base_revision_fingerprint == before.base_revision_fingerprint
        assert owner.load_draft_secret_bindings(id) == bindings
        assert dict(after.public_configuration_document)["ratio"] == 1.25
        assert after.type_descriptor_fingerprint == before.type_descriptor_fingerprint
    else:
        assert after.base_revision_fingerprint == owner.load_integration(id).current_revision_fingerprint
        assert owner.load_draft_secret_bindings(id) == ()
        assert dict(after.public_configuration_document) == {} and after.probe_configuration_document is None
        assert after.type_descriptor_fingerprint != before.type_descriptor_fingerprint
    with psycopg.connect(integration_db) as connection:
        assert connection.execute("SELECT * FROM integration_revision ORDER BY revision_sequence").fetchall() == history
        assert connection.execute("SELECT * FROM product_credential ORDER BY credential_id").fetchall() == credentials
        assert (
            connection.execute(
                "SELECT * FROM integration_revision_secret_binding ORDER BY revision_fingerprint,field_id"
            ).fetchall()
            == published
        )


@pytest.mark.parametrize("action", ["update", "reset"])
def test_receipt_failure_rolls_back_draft_bindings_and_source_frontier(
    native_probe: Path, integration_db: str, action: str
) -> None:
    from .test_integration_postgres import descriptor, populate

    ident = populate(integration_db)
    desc = descriptor()
    request = create_request()
    request.update(
        integration_id=ident,
        type_id=desc.type_id.value,
        descriptor=json.dumps(only_integration_json_document(desc.to_dict(include_fingerprint=False))),
    )
    command = edit(request, version=2, public='{"ratio":2.0}') if action == "update" else reset(request, 2)
    tables = [
        "integration",
        "integration_draft",
        "integration_draft_secret_binding",
        "product_command_admission",
        "product_command_receipt",
        "research_source_history",
        "research_source_history_frontier",
    ]
    with psycopg.connect(integration_db) as connection:
        before = {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
        connection.execute(
            "CREATE FUNCTION reject_draft_receipt() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'controlled failure'; END $$"
        )
        connection.execute(
            "CREATE TRIGGER reject_draft_receipt BEFORE INSERT ON product_command_receipt FOR EACH ROW EXECUTE FUNCTION reject_draft_receipt()"
        )
    assert call(native_probe, command) == {"error": "INTEGRATION_PERSISTENCE_UNAVAILABLE"}
    with psycopg.connect(integration_db) as connection:
        for table in tables:
            assert connection.execute(f"SELECT * FROM {table}").fetchall() == before[table]


@pytest.mark.parametrize("action", ["update", "reset"])
@pytest.mark.parametrize("fault", ["version_max", "old_time", "corrupt_draft"])
def test_invalid_version_time_and_corrupt_draft_never_get_repaired_or_leave_admission(
    native_probe: Path, integration_db: str, action: str, fault: str
) -> None:
    request = create_request()
    assert "error" not in call(native_probe, request)
    expected = "INTEGRATION_PERSISTENCE_CONFLICT"
    version = 1
    with psycopg.connect(integration_db) as connection:
        if fault == "version_max":
            version = 2147483647
            connection.execute("UPDATE integration_draft SET draft_version=%s", (version,))
            expected = "INTEGRATION_DRAFT_VERSION_CONFLICT"
        elif fault == "corrupt_draft":
            connection.execute("UPDATE integration_draft SET draft_fingerprint=%s", ("0" * 64,))
        before = connection.execute("SELECT * FROM integration_draft").fetchall()
    command = edit(request, version=version) if action == "update" else reset(request, version)
    if fault == "old_time":
        command["accepted_at"] = "2026-09-19T00:00:00Z"
    assert call(native_probe, command) == {"error": expected}
    assert call(native_probe, replay_request(command)) == {"result": None}
    with psycopg.connect(integration_db) as connection:
        assert connection.execute("SELECT * FROM integration_draft").fetchall() == before


@pytest.mark.parametrize("action", ["update", "reset"])
def test_admission_only_draft_command_is_unknown_and_does_not_repeat_work(
    native_probe: Path, integration_db: str, action: str
) -> None:
    request = create_request()
    assert "error" not in call(native_probe, request)
    command = edit(request) if action == "update" else reset(request, 1)
    assert call(native_probe, dict(replay_request(command), op="admit")) == {"result": "CREATED"}
    before = OnlyPostgresIntegrationStore(integration_db).load_draft(OnlyIntegrationId(request["integration_id"]))
    assert call(native_probe, command) == {"error": "PRODUCT_COMMAND_OUTCOME_UNKNOWN"}
    assert call(native_probe, replay_request(command)) == {"error": "PRODUCT_COMMAND_OUTCOME_UNKNOWN"}
    assert (
        OnlyPostgresIntegrationStore(integration_db).load_draft(OnlyIntegrationId(request["integration_id"])) == before
    )


@pytest.mark.parametrize("action", ["update", "reset"])
def test_actual_draft_commit_ack_loss_recovers_original_command_once(
    native_probe: Path, integration_db: str, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from tests.support.postgres_link import CommitAckCut

    request = create_request()
    assert "error" not in call(native_probe, request)
    command = edit(request) if action == "update" else reset(request, 1)
    with CommitAckCut(integration_db) as fault:
        with monkeypatch.context() as config:
            config.setenv("ONLYALPHA_POSTGRES_DSN", fault.dsn)
            assert call(native_probe, command) == {"error": "INTEGRATION_PERSISTENCE_UNAVAILABLE"}
        assert fault.done.is_set(), "actual COMMIT must precede the cut acknowledgement"
    recovered = call(native_probe, replay_request(command))
    assert recovered["replayed"] is True
    assert call(native_probe, command) == recovered
    assert (
        OnlyPostgresIntegrationStore(integration_db)
        .load_draft(OnlyIntegrationId(request["integration_id"]))
        .draft_version
        == 2
    )


@pytest.mark.parametrize("second_action", ["update", "reset"])
def test_same_version_writers_at_actual_frontier_lock_have_one_success(
    native_probe: Path, integration_db: str, second_action: str
) -> None:
    import subprocess

    from tests.support.postgres_link import wait_for_database_lock_barrier

    request = create_request()
    assert "error" not in call(native_probe, request)
    commands = [edit(request), edit(request) if second_action == "update" else reset(request, 1)]
    children: list[subprocess.Popen[str]] = []
    pids = []
    try:
        for _ in commands:
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
            control.execute("SELECT * FROM research_source_history_frontier FOR UPDATE")
            for index, (child, command) in enumerate(zip(children, commands, strict=True)):
                assert child.stdin is not None
                child.stdin.write(json.dumps(command))
                child.stdin.close()
                child.stdin = None
                wait_for_database_lock_barrier(
                    integration_db,
                    child,
                    pids[index],
                    control.info.backend_pid if index == 0 else pids[0],
                    "transactionid" if index == 0 else "tuple",
                )
        results = []
        for child in children:
            stdout, stderr = child.communicate(timeout=20)
            assert child.returncode == 0, stderr
            results.append(json.loads(stdout))
        assert sum("result" in result for result in results) == 1
        assert {"error": "INTEGRATION_DRAFT_VERSION_CONFLICT"} in results
        assert (
            OnlyPostgresIntegrationStore(integration_db)
            .load_draft(OnlyIntegrationId(request["integration_id"]))
            .draft_version
            == 2
        )
        with psycopg.connect(integration_db) as connection:
            assert connection.execute("SELECT count(*) FROM product_command_admission").fetchone() == (2,)
            assert connection.execute("SELECT count(*) FROM product_command_receipt").fetchone() == (2,)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=20)


@pytest.mark.parametrize("action", ["update", "reset"])
def test_unrelated_installed_type_cannot_replace_the_owning_integration_type(
    native_probe: Path, integration_db: str, action: str
) -> None:
    request = create_request()
    assert "error" not in call(native_probe, request)
    command = edit(request) if action == "update" else reset(request, 1)
    descriptor = json.loads(command["descriptor"])
    descriptor["type_id"] = "other.source"
    command["descriptor"] = json.dumps(descriptor)
    # The supplied installed set contains only another type. Exact owning-type
    # lookup cannot substitute it, and the formal missing-type code applies.
    from .support.integration import owning_facts

    before = owning_facts(integration_db)
    assert call(native_probe, command) == {"error": "INTEGRATION_TYPE_UNAVAILABLE"}
    assert call(native_probe, replay_request(command)) == {"result": None}
    assert owning_facts(integration_db) == before
