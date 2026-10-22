"""Native encrypted Credential owner against the canonical isolated test database."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from onlyalpha.persistence.postgres.credentials import OnlyPostgresCredentialAuthority
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority

from .support.integration import NOW, call

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]
MASTER_KEY = b"k" * 32
SUBJECT = "b52eb762-34cf-47d4-8cca-56ef93f0d2ac"


@pytest.fixture
def credential_db(postgres_dsn: str) -> str:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    return postgres_dsn


def request(action: str, **values: Any) -> dict[str, Any]:
    return dict(op="credential", command_id=str(uuid4()), action=action, rows=20, work=100_000, **values)


def create(secret: str = "controlled-secret", field: str = "api_key") -> dict[str, Any]:
    return request("create", credential_kind="INTEGRATION_SECRET", subject_id=SUBJECT, secret_name=field, secret=secret)


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def test_native_create_is_readable_by_original_python_and_metadata_is_secret_free(
    native_probe: Path, credential_db: str
) -> None:
    secret = "中文 secret\x00🙂"
    result = call(native_probe, create(secret))
    metadata = result["metadata"]
    assert metadata["generation"] == metadata["key_version"] == 1
    assert metadata["credential_kind"] == "INTEGRATION_SECRET"
    assert metadata["subject_id"] == SUBJECT and metadata["secret_name"] == "api_key"
    owner = OnlyPostgresCredentialAuthority(credential_db, MASTER_KEY, now=lambda: NOW)
    assert owner.read_secret(metadata["credential_id"], 1) == secret
    assert call(native_probe, request("read", credential_id=metadata["credential_id"], generation=1)) == {
        "secret_sha256": digest(secret)
    }
    assert call(native_probe, request("list")) == {"metadata": [metadata]}
    assert "ciphertext" not in metadata and "secret" not in metadata and "plaintext" not in metadata
    with psycopg.connect(credential_db) as connection:
        row = connection.execute("SELECT ciphertext FROM product_credential").fetchone()
        assert row is not None and secret.encode() not in bytes(row[0])
    assert call(native_probe, create()) == {"error": "CREDENTIAL_GENERATION_CONFLICT"}


def test_original_python_ciphertext_rotates_natively_without_new_slot_identity(
    native_probe: Path, credential_db: str
) -> None:
    owner = OnlyPostgresCredentialAuthority(credential_db, MASTER_KEY, now=lambda: NOW)
    old = owner.create("INTEGRATION_SECRET", SUBJECT, "api_key", "historical-secret")
    assert call(native_probe, request("read", credential_id=old.credential_id, generation=1)) == {
        "secret_sha256": digest("historical-secret")
    }
    updated = call(native_probe, request("rotate", credential_id=old.credential_id, generation=1, secret="new-secret"))[
        "metadata"
    ]
    assert updated["credential_id"] == old.credential_id and updated["generation"] == 2
    assert owner.read_secret(old.credential_id, 2) == "new-secret"
    assert call(native_probe, request("read", credential_id=old.credential_id, generation=1)) == {
        "error": "CREDENTIAL_GENERATION_MISMATCH"
    }
    assert call(native_probe, request("rotate", credential_id=old.credential_id, generation=1, secret="stale")) == {
        "error": "CREDENTIAL_GENERATION_CONFLICT"
    }
    assert call(native_probe, request("read", credential_id=str(uuid4()), generation=1)) == {
        "error": "CREDENTIAL_NOT_FOUND"
    }


@pytest.mark.parametrize("dimension", ["credential_kind", "subject_id", "secret_name", "generation", "ciphertext"])
def test_current_ciphertext_requires_complete_original_authenticated_context(
    native_probe: Path, credential_db: str, dimension: str
) -> None:
    metadata = call(native_probe, create())["metadata"]
    with psycopg.connect(credential_db) as connection:
        if dimension == "ciphertext":
            connection.execute(
                "UPDATE product_credential SET ciphertext=set_byte(ciphertext,octet_length(ciphertext)-1,get_byte(ciphertext,octet_length(ciphertext)-1)#1)"
            )
        elif dimension == "generation":
            connection.execute("UPDATE product_credential SET generation=2")
        else:
            values = {"credential_kind": "OTHER_SECRET", "subject_id": "another-owner", "secret_name": "api_secret"}
            from psycopg import sql

            connection.execute(
                sql.SQL("UPDATE product_credential SET {}=%s").format(sql.Identifier(dimension)), (values[dimension],)
            )
    generation = 2 if dimension == "generation" else 1
    assert call(native_probe, request("read", credential_id=metadata["credential_id"], generation=generation)) == {
        "error": "CREDENTIAL_CIPHERTEXT_INVALID"
    }


def test_generation_capacity_and_metadata_budget_never_rewrite_or_truncate(
    native_probe: Path, credential_db: str
) -> None:
    metadata = call(native_probe, create())["metadata"]
    with psycopg.connect(credential_db) as connection:
        connection.execute("UPDATE product_credential SET generation=2147483647")
        before = connection.execute("SELECT row_to_json(c)::text FROM product_credential c").fetchall()
    assert call(
        native_probe,
        request("rotate", credential_id=metadata["credential_id"], generation=2147483647, secret="overflow"),
    ) == {"error": "CREDENTIAL_GENERATION_CONFLICT"}
    with psycopg.connect(credential_db) as connection:
        assert connection.execute("SELECT row_to_json(c)::text FROM product_credential c").fetchall() == before
    limited = request("list")
    limited["rows"] = 0
    assert call(native_probe, limited) == {"error": "CREDENTIAL_PERSISTENCE_UNAVAILABLE"}
    limited = request("read", credential_id=metadata["credential_id"], generation=2147483647)
    limited["work"] = 0
    assert call(native_probe, limited) == {"error": "CREDENTIAL_PERSISTENCE_UNAVAILABLE"}


def test_two_current_generation_writers_have_one_rotation_and_one_stale_conflict(
    native_probe: Path, credential_db: str
) -> None:
    import json
    import subprocess

    from tests.support.postgres_link import wait_for_database_lock_barrier

    metadata = call(native_probe, create())["metadata"]
    children = [
        subprocess.Popen(
            [str(native_probe), "--pid-barrier"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    try:
        ready = []
        for child in children:
            assert child.stdout is not None
            ready.append(json.loads(child.stdout.readline()))
        with psycopg.connect(credential_db) as gate:
            gate.execute(
                "SELECT credential_id FROM product_credential WHERE credential_id=%s FOR UPDATE",
                (metadata["credential_id"],),
            )
            for index, child in enumerate(children):
                assert child.stdin is not None
                child.stdin.write(
                    json.dumps(
                        request(
                            "rotate",
                            credential_id=metadata["credential_id"],
                            generation=1,
                            secret=f"controlled-{index}",
                        )
                    )
                )
                child.stdin.close()
                child.stdin = None
                wait_for_database_lock_barrier(
                    credential_db,
                    child,
                    ready[index]["backend_pid"],
                    gate.info.backend_pid if index == 0 else ready[0]["backend_pid"],
                    "transactionid" if index == 0 else "tuple",
                )
        results = []
        for child in children:
            stdout, stderr = child.communicate(timeout=20)
            assert child.returncode == 0, stderr
            results.append(json.loads(stdout))
        assert results[0]["metadata"]["generation"] == 2
        assert results[1] == {"error": "CREDENTIAL_GENERATION_CONFLICT"}
        assert (
            OnlyPostgresCredentialAuthority(credential_db, MASTER_KEY, now=lambda: NOW).read_secret(
                metadata["credential_id"], 2
            )
            == "controlled-0"
        )
        with psycopg.connect(credential_db) as connection:
            assert connection.execute("SELECT count(*) FROM product_credential").fetchone() == (1,)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=20)


@pytest.mark.parametrize("action", ["create", "rotate"])
def test_written_envelope_is_verified_before_accepting_the_credential_effect(
    native_probe: Path, credential_db: str, action: str
) -> None:
    if action == "rotate":
        previous = call(native_probe, create())["metadata"]
        command = request("rotate", credential_id=previous["credential_id"], generation=1, secret="new-secret")
    else:
        command = create()
    with psycopg.connect(credential_db) as connection:
        before = connection.execute(
            "SELECT row_to_json(c)::text FROM product_credential c ORDER BY credential_id"
        ).fetchall()
        connection.execute(
            "CREATE FUNCTION mutate_credential_write() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.ciphertext=set_byte(NEW.ciphertext,octet_length(NEW.ciphertext)-1,get_byte(NEW.ciphertext,octet_length(NEW.ciphertext)-1)#1); RETURN NEW; END $$"
        )
        connection.execute(
            "CREATE TRIGGER mutate_credential_write BEFORE INSERT OR UPDATE ON product_credential FOR EACH ROW EXECUTE FUNCTION mutate_credential_write()"
        )
    assert call(native_probe, command) == {"error": "CREDENTIAL_PERSISTENCE_CONFLICT"}
    with psycopg.connect(credential_db) as connection:
        assert (
            connection.execute(
                "SELECT row_to_json(c)::text FROM product_credential c ORDER BY credential_id"
            ).fetchall()
            == before
        )
