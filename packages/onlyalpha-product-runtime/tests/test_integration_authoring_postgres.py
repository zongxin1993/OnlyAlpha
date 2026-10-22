"""Native installed-authoring transaction proofs, never Shipping UI acceptance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from onlyalpha.application.integration_configuration import OnlyIntegrationId, only_integration_json_document
from onlyalpha.persistence.postgres.integration_store import OnlyPostgresIntegrationStore
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority

from .support.integration import call, create_request, edit, owning_facts, publish, reset

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]


@pytest.fixture
def integration_db(postgres_dsn: str) -> str:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    return postgres_dsn


def command(probe: Path, action: str) -> dict[str, Any]:
    request = create_request()
    if action == "create":
        return request
    assert "error" not in call(probe, request)
    if action == "update":
        return edit(request, public='{"count":7}')
    if action == "reset":
        return reset(request, 1)
    if action == "clear":
        return dict(request, action="clear", command_id=str(uuid4()), expected_version=1, field_id="api_key")
    secret = dict(
        request,
        action="set-secret",
        command_id=str(uuid4()),
        expected_version=1,
        field_id="api_key",
        secret="controlled-test-only",
    )
    if action == "set-secret":
        return secret
    assert action == "publish"
    assert "error" not in call(probe, secret)
    return publish(request, 2)


@pytest.mark.parametrize("action", ["create", "update", "reset", "set-secret", "clear", "publish"])
def test_missing_current_authoring_rolls_back_every_provisional_fact(
    native_probe: Path, integration_db: str, action: str
) -> None:
    request = command(native_probe, action)
    before = owning_facts(integration_db)
    assert call(native_probe, dict(request, installed=False)) == {"error": "INTEGRATION_TYPE_UNAVAILABLE"}
    assert owning_facts(integration_db) == before


@pytest.mark.parametrize("action", ["create", "update", "reset", "set-secret", "clear", "publish"])
def test_same_command_replay_precedes_current_catalog_and_validator(
    native_probe: Path, integration_db: str, action: str
) -> None:
    request = command(native_probe, action)
    accepted = call(native_probe, request)
    assert "error" not in accepted
    before = owning_facts(integration_db)
    assert call(
        native_probe, dict(request, installed=False, validator="reject", descriptor="not a declaration")
    ) == dict(accepted, replayed=True)
    assert owning_facts(integration_db) == before


@pytest.mark.parametrize("action", ["update", "publish"])
@pytest.mark.parametrize(
    ("validator", "expected"),
    [
        ("reject", "INTEGRATION_CONFIGURATION_INVALID"),
        ("unavailable", "INTEGRATION_PERSISTENCE_UNAVAILABLE"),
        ("invalid-type", "INTEGRATION_TYPE_CONTRACT_INVALID"),
        ("invalid-probe", "INTEGRATION_TYPE_CONTRACT_INVALID"),
    ],
)
def test_provider_rejection_or_unavailable_has_no_admission_receipt_or_effect(
    native_probe: Path, integration_db: str, action: str, validator: str, expected: str
) -> None:
    request = command(native_probe, action)
    before = owning_facts(integration_db)
    assert call(native_probe, dict(request, validator=validator)) == {"error": expected}
    assert owning_facts(integration_db) == before


def test_publication_validates_the_same_default_filled_configuration_it_commits(
    native_probe: Path, integration_db: str
) -> None:
    request = command(native_probe, "publish")
    before = owning_facts(integration_db)
    assert call(native_probe, dict(request, validator="require-empty")) == {
        "error": "INTEGRATION_CONFIGURATION_INVALID"
    }
    assert owning_facts(integration_db) == before
    accepted = call(native_probe, dict(request, validator="require-defaults"))
    assert "error" not in accepted
    owner = OnlyPostgresIntegrationStore(integration_db)
    revision = owner.load_revision(accepted["result"]["receipt"]["outcome_id"])
    public = only_integration_json_document(revision.configuration_document)
    assert public["count"] == 5 and public["ratio"] == 1.5 and public["choice"] == "a" and public["flag"] is True
    draft = owner.load_draft(OnlyIntegrationId(request["integration_id"]))
    assert only_integration_json_document(draft.public_configuration_document) == public


def test_draft_validates_the_normalized_candidate_instead_of_original_float_spelling(
    native_probe: Path, integration_db: str
) -> None:
    request = command(native_probe, "update")
    request["public"] = '{"count":7,"ratio":-0.0}'
    before = owning_facts(integration_db)
    assert call(native_probe, dict(request, validator="require-float")) == {
        "error": "INTEGRATION_CONFIGURATION_INVALID"
    }
    assert owning_facts(integration_db) == before
    accepted = call(native_probe, dict(request, validator="require-normalized"))
    assert "error" not in accepted
    draft = OnlyPostgresIntegrationStore(integration_db).load_draft(OnlyIntegrationId(request["integration_id"]))
    assert only_integration_json_document(draft.public_configuration_document) == {"count": 7, "ratio": 0}


@pytest.mark.parametrize("action", ["update", "publish"])
def test_actual_draft_row_lock_spans_provider_validation_and_same_candidate_commit(
    native_probe: Path, integration_db: str, action: str
) -> None:
    import socket
    import struct
    import subprocess
    import tempfile
    from threading import Thread

    import psycopg

    from tests.support.postgres_link import CommitAckCut, wait_for_database_lock_barrier

    request = command(native_probe, action)
    process = subprocess.Popen(
        [str(native_probe), "--pid-barrier"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None and process.stdin is not None
        ready = json.loads(process.stdout.readline())
        assert ready["ready"] is True
        with tempfile.TemporaryDirectory(prefix="oa-validator-") as directory:
            path = str(Path(directory) / "barrier.sock")
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(path)
                listener.listen(1)
                listener.settimeout(20)
                process.stdin.write(json.dumps(dict(request, validator="barrier", barrier_path=path)))
                process.stdin.close()
                process.stdin = None
                stream, _ = listener.accept()
                with stream:
                    stream.settimeout(20)
                    size = struct.unpack("!I", CommitAckCut.exact(stream, 4))[0]
                    assert size <= 131072
                    candidate = json.loads(CommitAckCut.exact(stream, size))
                    with psycopg.connect(integration_db) as control:
                        row = control.execute("SELECT pg_backend_pid()").fetchone()
                        assert row is not None
                        control_pid = row[0]
                        control.execute("SET LOCAL statement_timeout='5s'")
                        observed: list[tuple[int, str]] = []
                        errors: list[Exception] = []

                        def compete_for_draft() -> None:
                            try:
                                row = control.execute(
                                    "SELECT draft_version,public_configuration_document::text FROM integration_draft WHERE integration_id=%s::uuid FOR UPDATE",
                                    (request["integration_id"],),
                                ).fetchone()
                                assert row is not None
                                observed.append((row[0], row[1]))
                            except Exception as error:
                                errors.append(error)

                        contender = Thread(target=compete_for_draft)
                        contender.start()
                        try:
                            # This contender bypasses the global Command frontier:
                            # only the actual Draft row lock can block it here.
                            wait_for_database_lock_barrier(
                                integration_db, process, control_pid, ready["backend_pid"], "transactionid"
                            )
                        finally:
                            stream.sendall(b"\x01")
                            contender.join(timeout=20)
                        assert not contender.is_alive() and errors == []
                        assert len(observed) == 1
                        version, document = observed[0]
                        assert version == request["expected_version"] + 1
                        assert json.loads(document) == candidate
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 0, stderr
        accepted = json.loads(stdout)
        assert accepted["replayed"] is False
        draft = OnlyPostgresIntegrationStore(integration_db).load_draft(OnlyIntegrationId(request["integration_id"]))
        assert only_integration_json_document(draft.public_configuration_document) == candidate
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=20)


@pytest.mark.parametrize("action", ["update", "reset", "set-secret", "clear", "publish"])
@pytest.mark.parametrize("replacement", ['"2.0"', "2.00"])
def test_stored_descriptor_scalar_kind_is_proved_even_when_all_metadata_fingerprints_match(
    native_probe: Path, integration_db: str, action: str, replacement: str
) -> None:
    import psycopg

    from onlyalpha.canonical import only_canonical_fingerprint

    request = command(native_probe, action)
    with psycopg.connect(integration_db) as connection:
        row = connection.execute(
            "SELECT type_descriptor_fingerprint,draft_fingerprint,type_descriptor_document::text FROM integration_draft WHERE integration_id=%s::uuid",
            (request["integration_id"],),
        ).fetchone()
        assert row is not None
        descriptor = json.loads(row[2])
        text = json.dumps(descriptor)
        assert text.count('"default": 2.0') == 1
        changed = text.replace('"default": 2.0', '"default": ' + replacement)
        assert only_canonical_fingerprint(json.loads(changed)) == row[0]
        connection.execute(
            "UPDATE integration_draft SET type_descriptor_document=%s::json WHERE integration_id=%s::uuid",
            (changed, request["integration_id"]),
        )
        same = connection.execute(
            "SELECT type_descriptor_fingerprint,draft_fingerprint FROM integration_draft WHERE integration_id=%s::uuid",
            (request["integration_id"],),
        ).fetchone()
        assert same == row[:2]
    before = owning_facts(integration_db)
    result = call(native_probe, request)
    if replacement.startswith('"'):
        assert result == {"error": "INTEGRATION_PERSISTENCE_CONFLICT"}
        assert owning_facts(integration_db) == before
    else:
        assert result["replayed"] is False


@pytest.mark.parametrize("action", ["create", "update"])
def test_same_fingerprint_typed_descriptor_corruption_during_write_rolls_back_before_receipt(
    native_probe: Path, integration_db: str, action: str
) -> None:
    import psycopg

    request = command(native_probe, action)
    descriptor = json.loads(request["descriptor"])
    index = next(
        i for i, field in enumerate(descriptor["configuration_contract"]["fields"]) if field["field_id"] == "delay"
    )
    before = owning_facts(integration_db)
    with psycopg.connect(integration_db) as connection:
        connection.execute(
            "CREATE FUNCTION corrupt_authoring_descriptor() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.type_descriptor_document := jsonb_set(NEW.type_descriptor_document::jsonb, ARRAY['configuration_contract','fields','"
            + str(index)
            + "','default'], to_jsonb('2.0'::text))::json; RETURN NEW; END $$"
        )
        connection.execute(
            "CREATE TRIGGER corrupt_authoring_descriptor BEFORE INSERT OR UPDATE ON integration_draft FOR EACH ROW EXECUTE FUNCTION corrupt_authoring_descriptor()"
        )
    try:
        assert call(native_probe, request) == {"error": "INTEGRATION_PERSISTENCE_CONFLICT"}
        assert owning_facts(integration_db) == before
    finally:
        with psycopg.connect(integration_db) as connection:
            connection.execute("DROP TRIGGER corrupt_authoring_descriptor ON integration_draft")
            connection.execute("DROP FUNCTION corrupt_authoring_descriptor()")


def test_bad_typed_draft_blocks_new_authoring_but_not_receipt_replay_metadata_or_lifecycle(
    native_probe: Path, integration_db: str
) -> None:
    import psycopg

    from .support.integration import lifecycle_request

    request = create_request()
    accepted = call(native_probe, request)
    assert accepted["replayed"] is False
    descriptor = json.loads(request["descriptor"])
    field = next(field for field in descriptor["configuration_contract"]["fields"] if field["field_id"] == "delay")
    assert type(field["default"]) is float and field["default"] == 2.0
    field["default"] = "2.0"
    changed = json.dumps(descriptor)
    with psycopg.connect(integration_db) as connection:
        connection.execute(
            "UPDATE integration_draft SET type_descriptor_document=%s::json WHERE integration_id=%s::uuid",
            (changed, request["integration_id"]),
        )
    before = owning_facts(integration_db)
    assert call(native_probe, edit(request)) == {"error": "INTEGRATION_PERSISTENCE_CONFLICT"}
    assert call(
        native_probe, dict(request, installed=False, descriptor="not a declaration", validator="reject")
    ) == dict(accepted, replayed=True)
    metadata = call(
        native_probe,
        dict(request, op="integration-read", rows=100, work=1_000_000, installed=False, descriptor="not a declaration"),
    )
    assert metadata["integration"]["id"] == request["integration_id"]
    assert owning_facts(integration_db) == before
    disabled = call(
        native_probe,
        dict(lifecycle_request(request, "ACTIVE", "DISABLED"), installed=False, descriptor="not a declaration"),
    )
    assert disabled["replayed"] is False
