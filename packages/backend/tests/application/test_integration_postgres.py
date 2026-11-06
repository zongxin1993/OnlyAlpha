"""Native reads of canonical Integration history; technical, not UI acceptance."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest

from .support.integration_rows import fixture_record, insert_fixture_record, revision_history
from .test_schema_postgres import migration_backend as migration_backend
from .test_schema_postgres import schema_db as schema_db

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]
NOW = datetime(2026, 9, 20, tzinfo=UTC)
VECTORS = json.loads((Path(__file__).parent / "fixtures/integration_configuration.json").read_text())


@pytest.fixture
def integration_db(schema_db: str) -> str:
    return schema_db


def read(probe: Path, integration_id: str, *, rows: int = 100, work: int = 1_000_000) -> dict[str, Any]:
    payload = {
        "op": "integration-read",
        "command_id": str(uuid4()),
        "integration_id": integration_id,
        "rows": rows,
        "work": work,
    }
    result = subprocess.run([str(probe)], input=json.dumps(payload), text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


def test_missing_and_unpublished_identity(native_probe: Path, integration_db: str) -> None:
    ident = str(uuid4())
    assert read(native_probe, ident) == {"integration": None}
    with psycopg.connect(integration_db) as connection:
        connection.execute(
            "INSERT INTO integration(integration_id,type_id,display_name,lifecycle_state,created_at,updated_at) VALUES(%s,'controlled.source','Data source','ACTIVE',%s,%s)",
            (ident, NOW, NOW),
        )
    assert read(native_probe, ident) == {
        "integration": {
            "id": ident,
            "type_id": "controlled.source",
            "display_name": "Data source",
            "lifecycle": "ACTIVE",
            "current": None,
            "draft": None,
            "history": [],
        }
    }


def descriptor() -> dict[str, Any]:
    return json.loads(VECTORS[0]["descriptor"])


def populate(dsn: str, probe: Path, count: int = 3) -> str:
    # Controlled historical rows, produced with current Rust record constructors.
    # They establish the precondition; the independent reader is under test.
    ident = VECTORS[0]["integration_id"]
    binding = VECTORS[0]["bindings"][0]
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "INSERT INTO integration(integration_id,type_id,display_name,lifecycle_state,created_at,updated_at) VALUES(%s,%s,'Data source','ACTIVE',%s,%s)",
            (ident, "controlled.source", NOW, NOW),
        )
        connection.execute(
            "INSERT INTO product_credential(credential_id,credential_kind,subject_id,secret_name,generation,ciphertext,key_version,created_at,updated_at) VALUES(%s,'INTEGRATION_SECRET',%s,'api_key',1,%s,1,%s,%s)",
            (binding["credential_id"], ident, b"controlled-metadata", NOW, NOW),
        )
        for sequence, value in enumerate(VECTORS[:count], start=1):
            revision = fixture_record(
                probe,
                kind="revision",
                ident=ident,
                descriptor=json.loads(value["descriptor"]),
                public=json.loads(value["public"]),
                probe_configuration=None if value["probe"] is None else json.loads(value["probe"]),
                bindings=[binding],
                created_at=NOW,
                revision_sequence=sequence,
            )
            assert revision["revision_fingerprint"] == value["revision_fingerprint"]
            insert_fixture_record(connection, "integration_revision", revision)
            connection.execute(
                "INSERT INTO integration_revision_secret_binding(revision_fingerprint,field_id,credential_id,credential_generation) VALUES(%s,%s,%s,%s)",
                (
                    revision["revision_fingerprint"],
                    binding["field_id"],
                    binding["credential_id"],
                    binding["credential_generation"],
                ),
            )
            connection.execute(
                "UPDATE integration SET current_revision_fingerprint=%s WHERE integration_id=%s",
                (revision["revision_fingerprint"], ident),
            )
        draft = fixture_record(
            probe,
            kind="draft",
            ident=ident,
            descriptor=descriptor(),
            public=json.loads(VECTORS[0]["public"]),
            probe_configuration={},
            bindings=[binding],
            created_at=NOW,
            draft_version=2,
            base_revision_fingerprint=VECTORS[0]["revision_fingerprint"],
        )
        insert_fixture_record(connection, "integration_draft", draft)
        connection.execute(
            "INSERT INTO integration_draft_secret_binding(integration_id,field_id,credential_id,credential_generation) VALUES(%s,%s,%s,%s)",
            (ident, binding["field_id"], binding["credential_id"], binding["credential_generation"]),
        )
    return ident


def expected_snapshot(dsn: str, ident: str) -> dict[str, Any]:
    from psycopg.rows import dict_row

    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        owner = connection.execute("SELECT * FROM integration WHERE integration_id=%s", (ident,)).fetchone()
        assert owner is not None
        draft = connection.execute(
            "SELECT draft_fingerprint,draft_version,public_configuration_document::text FROM integration_draft WHERE integration_id=%s",
            (ident,),
        ).fetchone()
        assert draft is not None
        binding = VECTORS[0]["bindings"][0]
        bindings = [{"field": binding["field_id"], "credential_id": binding["credential_id"], "generation": 1}]
        history = connection.execute(
            "SELECT revision_fingerprint,revision_sequence,configuration_document::text,probe_configuration_document::text FROM integration_revision WHERE integration_id=%s ORDER BY revision_sequence",
            (ident,),
        ).fetchall()
        return {
            "integration": {
                "id": ident,
                "type_id": owner["type_id"],
                "display_name": owner["display_name"],
                "lifecycle": owner["lifecycle_state"],
                "current": owner["current_revision_fingerprint"],
                "draft": {
                    "fingerprint": draft["draft_fingerprint"],
                    "version": draft["draft_version"],
                    "public": draft["public_configuration_document"],
                    "bindings": bindings,
                },
                "history": [
                    {
                        "fingerprint": row["revision_fingerprint"],
                        "sequence": row["revision_sequence"],
                        "public": row["configuration_document"],
                        "probe": row["probe_configuration_document"],
                        "bindings": bindings,
                    }
                    for row in history
                ],
            }
        }


def test_canonical_history_and_json_types_survive_fresh_native_readers(native_probe: Path, integration_db: str) -> None:
    ident = populate(integration_db, native_probe)
    expected = expected_snapshot(integration_db, ident)
    assert read(native_probe, ident) == expected
    # A current credential rotation cannot silently rewrite historical identity
    # or make old immutable bindings unreadable. Runtime admission is separate.
    with psycopg.connect(integration_db) as connection:
        connection.execute("UPDATE product_credential SET generation=2")
    assert read(native_probe, ident) == expected
    assert [item["revision_fingerprint"] for item in revision_history(integration_db, ident)] == [
        item["revision_fingerprint"] for item in VECTORS
    ]


@pytest.mark.parametrize("rows,work", [(0, 1_000_000), (8, 1_000_000), (100, 100)])
def test_resource_exhaustion_is_unavailable_not_partial_or_missing(
    native_probe: Path, integration_db: str, rows: int, work: int
) -> None:
    ident = populate(integration_db, native_probe)
    assert read(native_probe, ident, rows=rows, work=work) == {"error": "INTEGRATION_PERSISTENCE_UNAVAILABLE"}
    assert read(native_probe, ident, rows=9) == expected_snapshot(integration_db, ident)


@pytest.mark.parametrize(
    "case",
    [
        "draft-hash",
        "draft-json",
        "revision-hash",
        "revision-json",
        "revision-binding",
        "draft-binding",
        "duplicate-json",
        "owner-type",
        "current-reference",
        "base-reference",
    ],
)
def test_corrupt_history_never_becomes_absent_or_an_accepted_snapshot(
    native_probe: Path, integration_db: str, case: str
) -> None:
    ident = populate(integration_db, native_probe)
    with psycopg.connect(integration_db) as connection:
        # Fault injection is restricted to the fresh canonical _test schema.
        connection.execute("ALTER TABLE integration_revision DISABLE TRIGGER integration_revision_immutable_trigger")
        connection.execute(
            "ALTER TABLE integration_revision_secret_binding DISABLE TRIGGER integration_revision_secret_binding_immutable_trigger"
        )
        if case == "draft-hash":
            connection.execute("UPDATE integration_draft SET draft_fingerprint=%s", ("a" * 64,))
        elif case == "draft-json":
            connection.execute(
                "UPDATE integration_draft SET public_configuration_document=%s::json",
                ('{"ratio":{"$serde_json::private::RawValue":"1.25"}}',),
            )
        elif case == "revision-hash":
            connection.execute("UPDATE integration_revision SET configuration_fingerprint=%s", ("a" * 64,))
        elif case in {"revision-json", "duplicate-json"}:
            raw = (
                '{"ratio":1,"ratio":1.25}'
                if case == "duplicate-json"
                else '{"ratio":{"$serde_json::private::RawValue":"1.25"}}'
            )
            connection.execute("UPDATE integration_revision SET configuration_document=%s::json", (raw,))
        elif case == "revision-binding":
            connection.execute("UPDATE integration_revision_secret_binding SET credential_generation=2")
        elif case == "draft-binding":
            connection.execute("UPDATE integration_draft_secret_binding SET credential_generation=2")
        elif case == "owner-type":
            connection.execute("ALTER TABLE integration DISABLE TRIGGER integration_type_id_immutable_trigger")
            connection.execute("UPDATE integration SET type_id='other.source'")
        elif case == "current-reference":
            connection.execute("ALTER TABLE integration DISABLE TRIGGER ALL")
            connection.execute("UPDATE integration SET current_revision_fingerprint=%s", ("b" * 64,))
        else:
            connection.execute("ALTER TABLE integration_draft DISABLE TRIGGER ALL")
            connection.execute("UPDATE integration_draft SET base_revision_fingerprint=%s", ("b" * 64,))
    assert read(native_probe, ident)["error"] in {"INTEGRATION_PERSISTENCE_CONFLICT", "INTEGRATION_REVISION_CORRUPT"}


def test_repeatable_read_keeps_head_draft_bindings_and_history_in_one_snapshot(
    native_probe: Path, integration_db: str
) -> None:
    from psycopg.rows import dict_row

    from packages.backend.tests.postgres_link import wait_for_database_lock_barrier

    ident = populate(integration_db, native_probe)
    expected = expected_snapshot(integration_db, ident)
    child: subprocess.Popen[str] | None = None
    try:
        with psycopg.connect(integration_db, row_factory=dict_row) as control:
            control.execute("LOCK TABLE integration_draft IN ACCESS EXCLUSIVE MODE")
            child = subprocess.Popen(
                [str(native_probe), "--pid-barrier"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert child.stdout is not None and child.stdin is not None
            ready = json.loads(child.stdout.readline())
            child.stdin.write(
                json.dumps(
                    {
                        "op": "integration-read",
                        "command_id": str(uuid4()),
                        "integration_id": ident,
                        "rows": 100,
                        "work": 1_000_000,
                    }
                )
            )
            child.stdin.close()
            child.stdin = None
            wait_for_database_lock_barrier(
                integration_db, child, ready["backend_pid"], control.info.backend_pid, "relation"
            )
            control.execute(
                "UPDATE integration SET current_revision_fingerprint=%s WHERE integration_id=%s",
                (VECTORS[0]["revision_fingerprint"], ident),
            )
            changed = fixture_record(
                native_probe,
                kind="draft",
                ident=ident,
                descriptor=descriptor(),
                public={"ratio": 4.5},
                probe_configuration=None,
                bindings=[VECTORS[0]["bindings"][0]],
                created_at=NOW,
                draft_version=3,
                base_revision_fingerprint=VECTORS[1]["revision_fingerprint"],
            )
            control.execute(
                "UPDATE integration_draft SET base_revision_fingerprint=%s,type_descriptor_fingerprint=%s,type_descriptor_document=%s::json,public_configuration_document=%s::json,probe_configuration_document=NULL,draft_version=%s,draft_fingerprint=%s WHERE integration_id=%s",
                (
                    changed["base_revision_fingerprint"],
                    changed["type_descriptor_fingerprint"],
                    changed["type_descriptor_document"],
                    changed["public_configuration_document"],
                    changed["draft_version"],
                    changed["draft_fingerprint"],
                    ident,
                ),
            )
        stdout, stderr = child.communicate(timeout=20)
        assert child.returncode == 0, stderr
        assert json.loads(stdout) == expected
        assert read(native_probe, ident) == expected_snapshot(integration_db, ident)
        assert read(native_probe, ident) != expected
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=20)


def list_metadata(
    probe: Path, *, type_id: str | None = None, lifecycle: str | None = None, rows: int = 100
) -> dict[str, Any]:
    result = subprocess.run(
        [str(probe)],
        input=json.dumps(
            {
                "op": "integration-list",
                "command_id": str(uuid4()),
                "type_id": type_id,
                "lifecycle": lifecycle,
                "rows": rows,
            }
        ),
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


def test_list_metadata_uses_exact_filters_and_stable_order_without_requiring_installed_plugins(
    native_probe: Path, integration_db: str
) -> None:
    assert list_metadata(native_probe, rows=0) == {"integrations": []}
    expected = []
    for index, ident in enumerate(sorted((str(uuid4()) for _ in range(3)), reverse=True), start=1):
        type_id = "controlled.source" if index != 2 else "uninstalled.broker"
        lifecycle = ["ACTIVE", "DISABLED", "ARCHIVED"][index - 1]
        created_at = NOW if index == 1 else NOW + timedelta(days=1)

        with psycopg.connect(integration_db) as connection:
            connection.execute(
                "INSERT INTO integration(integration_id,type_id,display_name,lifecycle_state,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s)",
                (ident, type_id, str(index), lifecycle, created_at, created_at),
            )
        expected.append(
            {"id": ident, "type_id": type_id, "display_name": str(index), "lifecycle": lifecycle, "current": None}
        )
    # Earliest high UUID first; the two later rows tie on time and sort by UUID.
    expected = [expected[0], expected[2], expected[1]]
    assert list_metadata(native_probe, rows=3) == {"integrations": expected}
    assert list_metadata(native_probe, rows=2) == {"error": "INTEGRATION_PERSISTENCE_UNAVAILABLE"}
    assert list_metadata(native_probe, type_id="uninstalled.broker", lifecycle="DISABLED") == {
        "integrations": [expected[2]]
    }
    assert list_metadata(native_probe, type_id="controlled.source") == {"integrations": [expected[0], expected[1]]}
    assert list_metadata(native_probe, lifecycle="ARCHIVED") == {"integrations": [expected[1]]}
    assert list_metadata(native_probe, type_id="missing.type") == {"integrations": []}
    with psycopg.connect(integration_db) as connection:
        connection.execute(
            "UPDATE integration SET display_name=%s WHERE integration_id=%s", ("\u00a0", expected[0]["id"])
        )
    assert list_metadata(native_probe) == {"error": "INTEGRATION_PERSISTENCE_CONFLICT"}
    assert list_metadata(native_probe, type_id="uninstalled.broker") == {"integrations": [expected[2]]}
