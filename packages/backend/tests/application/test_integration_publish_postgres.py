"""Native publication/secret unlinking against canonical PG facts; not UI evidence."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from onlyalpha.application.integration_application import (
    OnlyIntegrationConfigurationResolver,
)
from onlyalpha.application.integration_configuration import OnlyIntegrationId
from onlyalpha.persistence.postgres.integration_store import OnlyPostgresIntegrationStore
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority

from .support.integration import MASTER_KEY, NOW, call, clear, configured, create_request, edit, publish, replay_request

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]


@pytest.fixture
def integration_db(postgres_dsn: str) -> str:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    return postgres_dsn


def test_publish_matches_existing_python_revision_defaults_and_exact_receipt(
    native_probe: Path, integration_db: str
) -> None:
    request, descriptor = configured(native_probe, integration_db)
    owner = OnlyPostgresIntegrationStore(integration_db)
    ident = OnlyIntegrationId(request["integration_id"])
    draft = owner.load_draft(ident)
    bindings = owner.load_draft_secret_bindings(ident)
    expected = (
        OnlyIntegrationConfigurationResolver()
        .resolve_publication(
            ident, descriptor, draft.public_configuration_document, draft.probe_configuration_document, bindings
        )
        .to_revision(1, NOW)
    )
    command = publish(request)
    result = call(native_probe, command)
    assert result["replayed"] is False
    assert result["result"]["receipt"]["outcome_kind"] == "INTEGRATION_REVISION"
    fingerprint = result["result"]["receipt"]["outcome_id"]
    assert fingerprint == expected.revision_fingerprint
    actual = owner.load_revision(fingerprint)
    assert actual == expected
    draft = owner.load_draft(ident)
    assert draft.draft_version == 4 and draft.base_revision_fingerprint == fingerprint
    assert dict(draft.public_configuration_document) == {"name": "Controlled name", "timeout_seconds": 10}
    assert dict(draft.probe_configuration_document or {}) == {"instrument": "BTCUSDT"}
    assert call(native_probe, replay_request(command)) == dict(result, replayed=True)


def test_duplicate_semantic_publication_reuses_original_revision_sequence_time_bytes(
    native_probe: Path, integration_db: str
) -> None:
    request, _ = configured(native_probe, integration_db)
    owner = OnlyPostgresIntegrationStore(integration_db)
    ident = OnlyIntegrationId(request["integration_id"])
    first = publish(request)
    accepted = call(native_probe, first)
    assert "error" not in accepted
    fingerprint = accepted["result"]["receipt"]["outcome_id"]
    before = owner.load_revision(fingerprint)
    second = dict(publish(request, 4), accepted_at="2026-09-21T00:00:00Z")
    reused = call(native_probe, second)
    assert reused["replayed"] is False
    assert reused["result"]["receipt"]["outcome_id"] == fingerprint
    assert owner.load_revision(fingerprint) == before and len(owner.list_revision_history(ident)) == 1
    assert owner.load_draft(ident).draft_version == 5
    assert call(native_probe, first) == dict(accepted, replayed=True)
    assert call(native_probe, edit(request, version=5, public='{"name":"Later name"}'))["replayed"] is False
    later = call(native_probe, publish(request, 6))
    assert later["result"]["receipt"]["outcome_id"] != fingerprint
    assert [r.revision_sequence for r in owner.list_revision_history(ident)] == [1, 2]
    assert call(native_probe, replay_request(first)) == dict(accepted, replayed=True)


@pytest.mark.parametrize("present", [False, True])
def test_clear_only_mutable_binding_and_keep_credential_and_published_history(
    native_probe: Path, integration_db: str, present: bool
) -> None:
    request, _ = configured(native_probe, integration_db)
    owner = OnlyPostgresIntegrationStore(integration_db)
    ident = OnlyIntegrationId(request["integration_id"])
    published = call(native_probe, publish(request))
    assert "error" not in published
    if not present:
        assert "error" not in call(native_probe, clear(request, 4))
    version = 4 if present else 5
    with psycopg.connect(integration_db) as connection:
        before = {
            table: connection.execute(f"SELECT * FROM {table}").fetchall()
            for table in ["product_credential", "integration_revision", "integration_revision_secret_binding"]
        }
    command = clear(request, version)
    result = call(native_probe, command)
    assert result["replayed"] is False
    assert result["result"]["receipt"]["outcome_kind"] == "INTEGRATION"
    assert owner.load_draft(ident).draft_version == version + 1 and owner.load_draft_secret_bindings(ident) == ()
    assert owner.load_integration(ident).current_revision_fingerprint == published["result"]["receipt"]["outcome_id"]
    with psycopg.connect(integration_db) as connection:
        for table, rows in before.items():
            assert connection.execute(f"SELECT * FROM {table}").fetchall() == rows
    assert call(native_probe, command) == dict(result, replayed=True)
    assert call(native_probe, publish(request, version + 1)) == {"error": "INTEGRATION_SECRET_REQUIRED"}


def test_rotated_credential_does_not_invalidate_old_receipt_but_blocks_new_publication(
    native_probe: Path, integration_db: str
) -> None:
    request, _ = configured(native_probe, integration_db)
    first = publish(request)
    accepted = call(native_probe, first)
    assert "error" not in accepted
    with psycopg.connect(integration_db) as connection:
        connection.execute("UPDATE product_credential SET generation=2")
    assert call(native_probe, replay_request(first)) == dict(accepted, replayed=True)
    newer = publish(request, 4)
    assert call(native_probe, newer) == {"error": "INTEGRATION_SECRET_BINDING_INVALID"}
    assert call(native_probe, replay_request(newer)) == {"result": None}


def test_publish_missing_required_secret_never_returns_a_revision(native_probe: Path, integration_db: str) -> None:
    request = create_request()
    assert "error" not in call(native_probe, request)
    assert call(native_probe, publish(request, 1)) == {"error": "INTEGRATION_SECRET_REQUIRED"}


@pytest.mark.parametrize("same_configuration", [True, False])
def test_sequence_capacity_only_blocks_new_revision_not_exact_semantic_reuse(
    native_probe: Path, integration_db: str, same_configuration: bool
) -> None:
    request, _ = configured(native_probe, integration_db)
    first = call(native_probe, publish(request))
    assert "error" not in first
    fingerprint = first["result"]["receipt"]["outcome_id"]
    with psycopg.connect(integration_db) as connection:
        connection.execute("ALTER TABLE integration_revision DISABLE TRIGGER integration_revision_immutable_trigger")
        connection.execute(
            "UPDATE integration_revision SET revision_sequence=2147483647 WHERE revision_fingerprint=%s", (fingerprint,)
        )
        connection.execute("ALTER TABLE integration_revision ENABLE TRIGGER integration_revision_immutable_trigger")
    owner = OnlyPostgresIntegrationStore(integration_db)
    ident = OnlyIntegrationId(request["integration_id"])
    command = publish(request, 4)
    if not same_configuration:
        assert "error" not in call(native_probe, edit(request, version=4, public='{"name":"New identity"}'))
        command = publish(request, 5)
    tables = [
        "integration",
        "integration_draft",
        "integration_revision",
        "integration_revision_secret_binding",
        "product_command_admission",
        "product_command_receipt",
        "research_source_history",
        "research_source_history_frontier",
    ]
    with psycopg.connect(integration_db) as connection:
        before = {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
    result = call(native_probe, command)
    if same_configuration:
        assert result["replayed"] is False
        assert result["result"]["receipt"]["outcome_id"] == fingerprint
        assert owner.load_draft(ident).draft_version == 5
        assert owner.load_revision(fingerprint).revision_sequence == 2147483647
        with psycopg.connect(integration_db) as connection:
            for table in ["integration_revision", "integration_revision_secret_binding"]:
                assert connection.execute(f"SELECT * FROM {table}").fetchall() == before[table]
    else:
        assert result == {"error": "INTEGRATION_PERSISTENCE_CONFLICT"}
        assert call(native_probe, replay_request(command)) == {"result": None}
        with psycopg.connect(integration_db) as connection:
            for table in tables:
                assert connection.execute(f"SELECT * FROM {table}").fetchall() == before[table]


@pytest.mark.parametrize(
    "action,stage",
    [
        ("publish", "revision"),
        ("publish", "published_binding"),
        ("publish", "head"),
        ("publish", "draft"),
        ("publish", "receipt"),
        ("clear", "draft"),
        ("clear", "binding_delete"),
        ("clear", "receipt"),
    ],
)
def test_each_publication_and_unlink_failure_rolls_back_all_owning_facts(
    native_probe: Path, integration_db: str, action: str, stage: str
) -> None:
    request, _ = configured(native_probe, integration_db)
    command = publish(request) if action == "publish" else clear(request)
    tables = [
        "integration",
        "integration_draft",
        "integration_draft_secret_binding",
        "integration_revision",
        "integration_revision_secret_binding",
        "product_credential",
        "product_command_admission",
        "product_command_receipt",
        "research_source_history",
        "research_source_history_frontier",
    ]
    table, event = {
        "revision": ("integration_revision", "INSERT"),
        "published_binding": ("integration_revision_secret_binding", "INSERT"),
        "head": ("integration", "UPDATE"),
        "draft": ("integration_draft", "UPDATE"),
        "receipt": ("product_command_receipt", "INSERT"),
        "binding_delete": ("integration_draft_secret_binding", "DELETE"),
    }[stage]
    with psycopg.connect(integration_db) as connection:
        before = {name: connection.execute(f"SELECT * FROM {name}").fetchall() for name in tables}
        connection.execute(
            "CREATE FUNCTION reject_publish_stage() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'controlled stage failure'; END $$"
        )
        connection.execute(
            f"CREATE TRIGGER reject_publish_stage BEFORE {event} ON {table} FOR EACH ROW EXECUTE FUNCTION reject_publish_stage()"
        )
    assert call(native_probe, command) == {"error": "INTEGRATION_PERSISTENCE_UNAVAILABLE"}
    assert call(native_probe, replay_request(command)) == {"result": None}
    with psycopg.connect(integration_db) as connection:
        for table in tables:
            assert connection.execute(f"SELECT * FROM {table}").fetchall() == before[table]


@pytest.mark.parametrize("fault", ["kind", "subject", "field", "generation"])
def test_publication_rejects_current_slot_mismatch_without_receipt(
    native_probe: Path, integration_db: str, fault: str
) -> None:
    request, _ = configured(native_probe, integration_db)
    with psycopg.connect(integration_db) as connection:
        if fault == "kind":
            connection.execute("UPDATE product_credential SET credential_kind='AGENT_PROVIDER'")
        elif fault == "subject":
            connection.execute("UPDATE product_credential SET subject_id=%s", (str(uuid4()),))
        elif fault == "field":
            connection.execute("UPDATE product_credential SET secret_name='other_key'")
        else:
            connection.execute("UPDATE product_credential SET generation=2")
    command = publish(request)
    assert call(native_probe, command) == {"error": "INTEGRATION_SECRET_BINDING_INVALID"}
    assert call(native_probe, replay_request(command)) == {"result": None}


@pytest.mark.parametrize("action", ["clear", "publish"])
def test_pending_admission_never_repeats_secret_or_revision_effect(
    native_probe: Path, integration_db: str, action: str
) -> None:
    request, _ = configured(native_probe, integration_db)
    command = clear(request) if action == "clear" else publish(request)
    assert call(native_probe, dict(replay_request(command), op="admit")) == {"result": "CREATED"}
    owner = OnlyPostgresIntegrationStore(integration_db)
    ident = OnlyIntegrationId(request["integration_id"])
    before = owner.load_draft(ident)
    assert call(native_probe, command) == {"error": "PRODUCT_COMMAND_OUTCOME_UNKNOWN"}
    assert owner.load_draft(ident) == before and owner.list_revision_history(ident) == ()


@pytest.mark.parametrize("action", ["clear", "publish"])
def test_actual_commit_ack_cut_keeps_one_effect_and_old_receipt(
    native_probe: Path, integration_db: str, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    from tests.support.postgres_link import CommitAckCut

    request, _ = configured(native_probe, integration_db)
    command = clear(request) if action == "clear" else publish(request)
    with CommitAckCut(integration_db) as fault:
        with monkeypatch.context() as config:
            config.setenv("ONLYALPHA_POSTGRES_DSN", fault.dsn)
            assert call(native_probe, command) == {"error": "INTEGRATION_PERSISTENCE_UNAVAILABLE"}
        assert fault.done.is_set(), "the actual committed acknowledgement must be cut"
    recovered = call(native_probe, replay_request(command))
    assert recovered["replayed"] is True
    assert call(native_probe, command) == recovered
    owner = OnlyPostgresIntegrationStore(integration_db)
    ident = OnlyIntegrationId(request["integration_id"])
    assert owner.load_draft(ident).draft_version == 4
    assert len(owner.list_revision_history(ident)) == (1 if action == "publish" else 0)


@pytest.mark.parametrize("action", ["clear", "publish"])
def test_same_version_contenders_at_frontier_have_one_committed_effect(
    native_probe: Path, integration_db: str, action: str
) -> None:
    import subprocess

    from tests.support.postgres_link import wait_for_database_lock_barrier

    request, _ = configured(native_probe, integration_db)
    commands = [publish(request), clear(request) if action == "clear" else publish(request)]
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
            == 4
        )
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=20)


@pytest.mark.parametrize("field", ["name", "absent", "INVALID.FIELD"])
def test_only_declared_secret_fields_can_be_cleared(native_probe: Path, integration_db: str, field: str) -> None:
    request, _ = configured(native_probe, integration_db)
    command = clear(request, field=field)
    assert call(native_probe, command) == {"error": "INTEGRATION_SECRET_FIELD_INVALID"}
    assert call(native_probe, replay_request(command)) == {"result": None}


def test_corrupt_historical_identity_candidate_is_never_adopted_on_reuse(
    native_probe: Path, integration_db: str
) -> None:
    request, _ = configured(native_probe, integration_db)
    first = call(native_probe, publish(request))
    fp = first["result"]["receipt"]["outcome_id"]
    assert "error" not in call(native_probe, edit(request, version=4, public='{"name":"Later name"}'))
    assert "error" not in call(native_probe, publish(request, 5))
    assert "error" not in call(native_probe, edit(request, version=6, public='{"name":"Controlled name"}'))
    with psycopg.connect(integration_db) as connection:
        connection.execute("ALTER TABLE integration_revision DISABLE TRIGGER integration_revision_immutable_trigger")
        connection.execute(
            "UPDATE integration_revision SET configuration_document='{}'::json WHERE revision_fingerprint=%s", (fp,)
        )
        connection.execute("ALTER TABLE integration_revision ENABLE TRIGGER integration_revision_immutable_trigger")
    command = publish(request, 7)
    assert call(native_probe, command) == {"error": "INTEGRATION_REVISION_CORRUPT"}
    assert call(native_probe, replay_request(command)) == {"result": None}


@pytest.mark.parametrize("rows", [0, 1, 2])
def test_publish_budget_exhaustion_never_becomes_partial_result(
    native_probe: Path, integration_db: str, rows: int
) -> None:
    request, _ = configured(native_probe, integration_db)
    command = dict(publish(request), rows=rows)
    assert call(native_probe, command) == {"error": "INTEGRATION_PERSISTENCE_UNAVAILABLE"}
    assert call(native_probe, replay_request(command)) == {"result": None}


@pytest.mark.parametrize("rotated", [False, True])
def test_clear_validates_remaining_bindings_and_can_unlink_the_invalid_one(
    native_probe: Path, integration_db: str, rotated: bool
) -> None:
    request, _ = configured(native_probe, integration_db, extra_secret=True)
    owner = OnlyPostgresIntegrationStore(integration_db)
    ident = OnlyIntegrationId(request["integration_id"])
    if rotated:
        with psycopg.connect(integration_db) as connection:
            connection.execute("UPDATE product_credential SET generation=2 WHERE secret_name='api_secret'")
        rejected = clear(request, 4, field="api_key")
        assert call(native_probe, rejected) == {"error": "INTEGRATION_SECRET_BINDING_INVALID"}
        assert call(native_probe, replay_request(rejected)) == {"result": None}
        command = clear(request, 4, field="api_secret")
        remaining = "api_key"
    else:
        command = clear(request, 4, field="api_key")
        remaining = "api_secret"
    result = call(native_probe, command)
    assert result["replayed"] is False
    assert [binding.field_id for binding in owner.load_draft_secret_bindings(ident)] == [remaining]
    with psycopg.connect(integration_db) as connection:
        assert connection.execute("SELECT count(*) FROM product_credential").fetchone() == (2,)


@pytest.mark.parametrize("reuse", [False, True])
def test_current_credential_share_lock_is_held_through_publication_commit(
    native_probe: Path, integration_db: str, reuse: bool
) -> None:
    import subprocess
    from concurrent.futures import ThreadPoolExecutor

    from psycopg.rows import dict_row

    from onlyalpha.persistence.postgres.config import OnlyPostgresOperationalConnectionOptions
    from onlyalpha.persistence.postgres.credentials import OnlyPostgresCredentialAuthority
    from tests.support.postgres_link import wait_for_database_lock_barrier

    request, _ = configured(native_probe, integration_db)
    if reuse:
        assert call(native_probe, publish(request))["replayed"] is False
    version = 4 if reuse else 3
    command = publish(request, version)
    with psycopg.connect(integration_db) as setup:
        credential_row = setup.execute(
            "SELECT credential_id::text FROM product_credential WHERE secret_name='api_key'"
        ).fetchone()
        assert credential_row is not None
        credential_id = credential_row[0]
        setup.execute(
            "CREATE FUNCTION publication_receipt_barrier() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.command_kind='PUBLISH_INTEGRATION_REVISION' THEN PERFORM pg_advisory_xact_lock(hashtextextended('controlled-publication-receipt',0)); END IF; RETURN NEW; END $$"
        )
        setup.execute(
            "CREATE TRIGGER publication_receipt_barrier BEFORE INSERT ON product_command_receipt FOR EACH ROW EXECUTE FUNCTION publication_receipt_barrier()"
        )
    child = subprocess.Popen(
        [str(native_probe), "--pid-barrier"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None and child.stdin is not None
        ready = json.loads(child.stdout.readline())
        assert ready["ready"] is True
        with psycopg.connect(
            OnlyPostgresOperationalConnectionOptions().apply(integration_db), row_factory=dict_row
        ) as rotating:
            rotating_pid = rotating.info.backend_pid
            authority = OnlyPostgresCredentialAuthority(integration_db, MASTER_KEY, now=lambda: NOW)

            def rotate() -> int:
                with rotating.transaction():
                    return authority._rotate_in_transaction(
                        rotating, credential_id, 1, "controlled-rotated-secret"
                    ).generation

            with ThreadPoolExecutor(max_workers=1) as pool:
                with psycopg.connect(integration_db) as gate:
                    gate.execute("SELECT pg_advisory_xact_lock(hashtextextended('controlled-publication-receipt',0))")
                    child.stdin.write(json.dumps(command))
                    child.stdin.close()
                    child.stdin = None
                    wait_for_database_lock_barrier(
                        integration_db, child, ready["backend_pid"], gate.info.backend_pid, "advisory"
                    )
                    future = pool.submit(rotate)
                    wait_for_database_lock_barrier(
                        integration_db, child, rotating_pid, ready["backend_pid"], "transactionid"
                    )
                    assert not future.done(), "rotation must remain fenced until publication commits"
                assert future.result(timeout=20) == 2
        stdout, stderr = child.communicate(timeout=20)
        assert child.returncode == 0, stderr
        accepted = json.loads(stdout)
        assert accepted["replayed"] is False
        assert call(native_probe, replay_request(command)) == dict(accepted, replayed=True)
        assert call(native_probe, publish(request, version + 1)) == {"error": "INTEGRATION_SECRET_BINDING_INVALID"}
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=20)
