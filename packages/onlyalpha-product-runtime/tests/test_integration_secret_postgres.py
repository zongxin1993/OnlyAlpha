"""Native Integration secret commands; technical facts, never Shipping UI evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from onlyalpha.application.integration_configuration import OnlyIntegrationId
from onlyalpha.persistence.postgres.credentials import OnlyPostgresCredentialAuthority
from onlyalpha.persistence.postgres.integration_store import OnlyPostgresIntegrationStore
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority

from .support.integration import NOW, call, create_request, owning_facts, replay_request

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]
KEY = b"k" * 32


@pytest.fixture
def secret_db(postgres_dsn: str) -> str:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    return postgres_dsn


def set_secret(request: dict[str, Any], version: int, secret: str, field: str = "api_key") -> dict[str, Any]:
    return dict(
        request, action="set-secret", command_id=str(uuid4()), expected_version=version, field_id=field, secret=secret
    )


def test_native_secret_write_and_exact_replay_never_rotate_twice(native_probe: Path, secret_db: str) -> None:
    request = create_request()
    assert call(native_probe, request)["replayed"] is False
    command = set_secret(request, 1, "中文 secret\x00🙂")
    accepted = call(native_probe, command)
    assert accepted["replayed"] is False
    owner = OnlyPostgresIntegrationStore(secret_db)
    ident = OnlyIntegrationId(request["integration_id"])
    first = owner.load_draft_secret_bindings(ident)[0]
    assert first.credential_generation == 1 and owner.load_draft(ident).draft_version == 2
    assert OnlyPostgresCredentialAuthority(secret_db, KEY).read_secret(first.credential_id, 1) == command["secret"]
    assert call(native_probe, command) == dict(accepted, replayed=True)
    assert call(native_probe, dict(command, secret="different")) == {"error": "PRODUCT_COMMAND_CONFLICT"}
    second = set_secret(request, 2, "controlled-rotated")
    assert call(native_probe, second)["replayed"] is False
    current = owner.load_draft_secret_bindings(ident)[0]
    assert current.credential_id == first.credential_id and current.credential_generation == 2
    assert OnlyPostgresCredentialAuthority(secret_db, KEY).read_secret(first.credential_id, 2) == "controlled-rotated"
    assert call(native_probe, replay_request(command)) == dict(accepted, replayed=True)
    assert call(native_probe, command) == dict(accepted, replayed=True)
    assert owner.load_draft(ident).draft_version == 3
    with psycopg.connect(secret_db) as connection:
        assert connection.execute("SELECT count(*) FROM product_credential").fetchone() == (1,)
        text = connection.execute("SELECT row_to_json(a)::text FROM product_command_admission a").fetchall()
        assert all(command["secret"] not in row[0] and "controlled-rotated" not in row[0] for row in text)


@pytest.mark.parametrize("field", ["count", "missing", "INVALID.FIELD"])
def test_only_current_declared_secret_fields_create_a_slot(native_probe: Path, secret_db: str, field: str) -> None:
    request = create_request()
    assert call(native_probe, request)["replayed"] is False
    command = set_secret(request, 1, "controlled", field)
    assert call(native_probe, command) == {"error": "INTEGRATION_SECRET_FIELD_INVALID"}
    assert call(native_probe, replay_request(command)) == {"result": None}
    with psycopg.connect(secret_db) as connection:
        assert connection.execute("SELECT count(*) FROM product_credential").fetchone() == (0,)


def test_pending_command_keeps_unknown_and_never_creates_or_rotates_a_slot(native_probe: Path, secret_db: str) -> None:
    request = create_request()
    call(native_probe, request)
    command = set_secret(request, 1, "controlled")
    assert call(native_probe, dict(replay_request(command), op="admit")) == {"result": "CREATED"}
    assert call(native_probe, command) == {"error": "PRODUCT_COMMAND_OUTCOME_UNKNOWN"}
    with psycopg.connect(secret_db) as connection:
        assert connection.execute("SELECT count(*) FROM product_credential").fetchone() == (0,)


@pytest.mark.parametrize("rotate", [False, True])
def test_actual_commit_ack_cut_never_repeats_a_secret_effect(
    native_probe: Path, secret_db: str, monkeypatch: pytest.MonkeyPatch, rotate: bool
) -> None:
    from tests.support.postgres_link import CommitAckCut

    request = create_request()
    call(native_probe, request)
    if rotate:
        assert call(native_probe, set_secret(request, 1, "first"))["replayed"] is False
    version = 2 if rotate else 1
    command = set_secret(request, version, "controlled-new")
    with CommitAckCut(secret_db) as fault:
        with monkeypatch.context() as config:
            config.setenv("ONLYALPHA_POSTGRES_DSN", fault.dsn)
            assert call(native_probe, command) == {"error": "INTEGRATION_PERSISTENCE_UNAVAILABLE"}
        assert fault.done.is_set()
    recovered = call(native_probe, replay_request(command))
    assert recovered["replayed"] is True
    assert call(native_probe, command) == recovered
    owner = OnlyPostgresIntegrationStore(secret_db)
    ident = OnlyIntegrationId(request["integration_id"])
    binding = owner.load_draft_secret_bindings(ident)[0]
    assert binding.credential_generation == version and owner.load_draft(ident).draft_version == version + 1
    assert (
        OnlyPostgresCredentialAuthority(secret_db, KEY).read_secret(binding.credential_id, version) == "controlled-new"
    )


@pytest.mark.parametrize("rotate", [False, True])
@pytest.mark.parametrize("stage", ["credential", "draft", "binding", "receipt"])
def test_secret_failure_at_every_write_stage_rolls_back_the_entire_command(
    native_probe: Path, secret_db: str, rotate: bool, stage: str
) -> None:
    request = create_request()
    call(native_probe, request)
    if rotate:
        assert call(native_probe, set_secret(request, 1, "before"))["replayed"] is False
    command = set_secret(request, 2 if rotate else 1, "controlled-after")
    before = owning_facts(secret_db)
    table, event = {
        "credential": ("product_credential", "UPDATE" if rotate else "INSERT"),
        "draft": ("integration_draft", "UPDATE"),
        "binding": ("integration_draft_secret_binding", "UPDATE" if rotate else "INSERT"),
        "receipt": ("product_command_receipt", "INSERT"),
    }[stage]
    with psycopg.connect(secret_db) as connection:
        connection.execute(
            "CREATE FUNCTION reject_secret_write() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'controlled secret write failure'; END $$"
        )
        connection.execute(
            f"CREATE TRIGGER reject_secret_write BEFORE {event} ON {table} FOR EACH ROW EXECUTE FUNCTION reject_secret_write()"
        )
    assert call(native_probe, command) == {"error": "INTEGRATION_PERSISTENCE_UNAVAILABLE"}
    assert call(native_probe, replay_request(command)) == {"result": None}
    assert owning_facts(secret_db) == before


@pytest.mark.parametrize("target", ["api_key", "api_secret"])
def test_target_rotation_can_be_rebound_but_remaining_stale_slot_blocks_all_effects(
    native_probe: Path, secret_db: str, target: str
) -> None:
    from .support.integration import configured, publish

    request, _ = configured(native_probe, secret_db, extra_secret=True)
    assert call(native_probe, publish(request, 4))["replayed"] is False
    owner = OnlyPostgresIntegrationStore(secret_db)
    ident = OnlyIntegrationId(request["integration_id"])
    old_bindings = {binding.field_id: binding for binding in owner.load_draft_secret_bindings(ident)}
    credentials = OnlyPostgresCredentialAuthority(secret_db, KEY, now=lambda: NOW)
    credentials.rotate(old_bindings[target].credential_id, 1, "controlled-current")
    before = owning_facts(secret_db)
    command = set_secret(request, 5, "controlled-new-target")
    result = call(native_probe, command)
    if target == "api_secret":
        assert result == {"error": "INTEGRATION_SECRET_BINDING_INVALID"}
        assert owning_facts(secret_db) == before
    else:
        assert result["replayed"] is False
        bindings = {binding.field_id: binding for binding in owner.load_draft_secret_bindings(ident)}
        assert bindings["api_key"].credential_id == old_bindings["api_key"].credential_id
        assert bindings["api_key"].credential_generation == 3
        assert bindings["api_secret"] == old_bindings["api_secret"]
        after = owning_facts(secret_db)
        for table in ("integration_revision", "integration_revision_secret_binding", "integration"):
            assert after[table] == before[table]
        assert credentials.read_secret(bindings["api_key"].credential_id, 3) == "controlled-new-target"


@pytest.mark.parametrize("capacity", ["draft", "credential"])
def test_sequence_capacity_refuses_a_new_secret_effect_without_rewriting_current_history(
    native_probe: Path, secret_db: str, capacity: str
) -> None:
    request = create_request()
    call(native_probe, request)
    assert call(native_probe, set_secret(request, 1, "before"))["replayed"] is False
    with psycopg.connect(secret_db) as connection:
        if capacity == "draft":
            connection.execute("UPDATE integration_draft SET draft_version=2147483647")
        else:
            connection.execute("UPDATE product_credential SET generation=2147483647")
    before = owning_facts(secret_db)
    command = set_secret(request, 2147483647 if capacity == "draft" else 2, "after")
    expected = "INTEGRATION_DRAFT_VERSION_CONFLICT" if capacity == "draft" else "INTEGRATION_PERSISTENCE_CONFLICT"
    assert call(native_probe, command) == {"error": expected}
    assert call(native_probe, replay_request(command)) == {"result": None}
    assert owning_facts(secret_db) == before


@pytest.mark.parametrize("case", ["archived", "stale", "type", "absent", "budget", "time"])
def test_invalid_secret_admission_leaves_all_current_and_historical_facts_unchanged(
    native_probe: Path, secret_db: str, case: str
) -> None:
    import json

    from .support.integration import lifecycle_request

    request = create_request()
    call(native_probe, request)
    command = set_secret(request, 1, "controlled")
    if case == "archived":
        call(native_probe, lifecycle_request(request, "ACTIVE", "ARCHIVED"))
        expected = "INTEGRATION_ARCHIVED"
    elif case == "stale":
        command["expected_version"] = 2
        expected = "INTEGRATION_DRAFT_VERSION_CONFLICT"
    elif case == "type":
        descriptor = json.loads(command["descriptor"])
        descriptor["implementation_version"] = "2.0.0"
        command["descriptor"] = json.dumps(descriptor)
        expected = "INTEGRATION_TYPE_CHANGED"
    elif case == "absent":
        command["integration_id"] = str(uuid4())
        expected = "INTEGRATION_NOT_FOUND"
    elif case == "budget":
        command["rows"] = 2
        expected = "INTEGRATION_PERSISTENCE_UNAVAILABLE"
    else:
        command["accepted_at"] = "2025-09-20T00:00:00Z"
        expected = "INTEGRATION_PERSISTENCE_CONFLICT"
    before = owning_facts(secret_db)
    assert call(native_probe, command) == {"error": expected}
    assert call(native_probe, replay_request(command)) == {"result": None}
    assert owning_facts(secret_db) == before


def test_same_draft_version_contenders_have_one_new_slot_and_one_stale_command(
    native_probe: Path, secret_db: str
) -> None:
    import json
    import subprocess

    from tests.support.postgres_link import wait_for_database_lock_barrier

    request = create_request()
    call(native_probe, request)
    commands = [set_secret(request, 1, f"controlled-{index}") for index in range(2)]
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
        with psycopg.connect(secret_db) as control:
            control.execute("SELECT * FROM research_source_history_frontier FOR UPDATE")
            for index, (child, command) in enumerate(zip(children, commands, strict=True)):
                assert child.stdin is not None
                child.stdin.write(json.dumps(command))
                child.stdin.close()
                child.stdin = None
                wait_for_database_lock_barrier(
                    secret_db,
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
        owner = OnlyPostgresIntegrationStore(secret_db)
        ident = OnlyIntegrationId(request["integration_id"])
        assert owner.load_draft(ident).draft_version == 2
        assert owner.load_draft_secret_bindings(ident)[0].credential_generation == 1
        with psycopg.connect(secret_db) as connection:
            assert connection.execute("SELECT count(*) FROM product_credential").fetchone() == (1,)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=20)


@pytest.mark.parametrize("rotate", [False, True])
@pytest.mark.parametrize("dimension", ["generation", "credential_id", "field_id"])
def test_actual_secret_binding_relation_is_proved_before_the_receipt(
    native_probe: Path, secret_db: str, rotate: bool, dimension: str
) -> None:
    request = create_request()
    call(native_probe, request)
    if rotate:
        assert call(native_probe, set_secret(request, 1, "before"))["replayed"] is False
    foreign = OnlyPostgresCredentialAuthority(secret_db, KEY, now=lambda: NOW).create(
        "INTEGRATION_SECRET", str(uuid4()), "api_key", "controlled-foreign"
    )
    command = set_secret(request, 2 if rotate else 1, "controlled-new")
    before = owning_facts(secret_db)
    mutation = {
        "generation": "NEW.credential_generation=NEW.credential_generation+1",
        "credential_id": f"NEW.credential_id='{foreign.credential_id}'::uuid",
        "field_id": "NEW.field_id='api_secret'",
    }[dimension]
    with psycopg.connect(secret_db) as connection:
        connection.execute(
            f"CREATE FUNCTION mutate_secret_relation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {mutation}; RETURN NEW; END $$"
        )
        connection.execute(
            "CREATE TRIGGER mutate_secret_relation BEFORE INSERT OR UPDATE ON integration_draft_secret_binding FOR EACH ROW EXECUTE FUNCTION mutate_secret_relation()"
        )
    assert call(native_probe, command) == {"error": "INTEGRATION_PERSISTENCE_CONFLICT"}
    assert call(native_probe, replay_request(command)) == {"result": None}
    assert owning_facts(secret_db) == before
