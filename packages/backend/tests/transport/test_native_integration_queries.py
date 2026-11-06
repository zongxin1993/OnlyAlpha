"""Native HTTP/PG contract evidence; controlled historical facts, not UI acceptance."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from packages.backend.tests.application.test_schema_postgres import migration_backend, schema_db

__all__ = ["migration_backend", "schema_db"]

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]
NOW = datetime(2026, 9, 20, 0, 0, 0, 123400, tzinfo=UTC)


@pytest.fixture
def query_db(schema_db: str) -> str:
    return schema_db


def requests(
    probe: Path,
    paths: Sequence[str | dict[str, object]],
    *,
    rows: int = 100,
    work: int = 1_000_000,
    shadow: bool = False,
    missing_relation: str | None = None,
    copy_shadow: bool = True,
) -> list[dict[str, Any]]:
    payload = {
        "rows": rows,
        "work": work,
        "shadow": shadow,
        "missing_relation": missing_relation,
        "copy_shadow": copy_shadow,
        "requests": [{"path": p} if isinstance(p, str) else p for p in paths],
    }
    result = subprocess.run(
        [str(probe)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        timeout=25,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    responses = cast(list[dict[str, Any]], json.loads(result.stdout)["responses"])
    for response in responses:
        response["body"] = json.loads(response["raw"]) if response["raw"] else None
    return responses


def native_record(probe: Path, **payload: object) -> dict[str, Any]:
    result = subprocess.run(
        [str(probe)], input=json.dumps(payload), text=True, capture_output=True, timeout=25, check=False
    )
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


def fingerprint(probe: Path, document: dict[str, Any]) -> str:
    return cast(
        str, native_record(probe, op="integration-fixture-fingerprint", document=json.dumps(document))["fingerprint"]
    )


def descriptor(probe: Path) -> dict[str, Any]:
    # Declared retained input, not a current executable installation or authoring grant.
    field = {
        "advanced": False,
        "default": None,
        "description": "",
        "display_name": "",
        "enum_values": [],
        "exclusive_minimum": False,
        "field_id": "",
        "maximum": None,
        "minimum": None,
        "required": False,
        "secret": False,
        "value_kind": "STRING",
    }
    contract: dict[str, Any] = {
        "schema_version": 1,
        "fields": [
            {**field, "field_id": "api_key", "required": True, "secret": True, "display_name": "API key"},
            {**field, "field_id": "name", "required": True, "display_name": "Name"},
            {
                **field,
                "field_id": "timeout_seconds",
                "value_kind": "DURATION",
                "default": 10.0,
                "minimum": 0.1,
                "display_name": "Timeout",
            },
        ],
    }
    contract["fingerprint"] = fingerprint(probe, contract)
    probe_contract: dict[str, Any] = {
        "probe_version": 1,
        "probe_mode": "DEFAULT_INSTRUMENT",
        "default_probe_instrument": "BTCUSDT",
        "user_selectable_probe_instrument": True,
        "probe_checks": sorted(
            ["CONNECTIVITY", "AUTHENTICATION", "REFERENCE_DATA", "HISTORICAL_DATA", "REALTIME_DATA", "MODEL_DISCOVERY"]
        ),
    }
    probe_contract["fingerprint"] = fingerprint(probe, probe_contract)
    return {
        "schema_version": 1,
        "type_id": "binance.spot.market_data",
        "category": "DATA_SOURCE",
        "display_name": "Binance Spot",
        "description": "Binance Spot market data",
        "provider_id": "binance",
        "implementation_id": "binance",
        "implementation_version": "1.0.0",
        "public_api_version": "1.1",
        "capabilities": ["HISTORICAL_BARS"],
        "configuration_contract": contract,
        "probe_contract": probe_contract,
    }


def insert_revision(connection: psycopg.Connection[Any], ident: str, credential: str, revision: dict[str, Any]) -> None:
    columns = [
        "revision_fingerprint",
        "revision_sequence",
        "type_id",
        "type_descriptor_fingerprint",
        "type_descriptor_document",
        "configuration_fingerprint",
        "configuration_document",
        "runtime_configuration_fingerprint",
        "probe_configuration_fingerprint",
        "probe_configuration_document",
        "secret_binding_fingerprint",
    ]
    connection.execute(
        "INSERT INTO integration_revision(integration_id,"
        + ",".join(columns)
        + ",created_at) VALUES("
        + ",".join(["%s"] * (len(columns) + 2))
        + ")",
        [ident, *[revision[key] for key in columns], NOW],
    )
    connection.execute(
        "INSERT INTO integration_revision_secret_binding(revision_fingerprint,field_id,credential_id,credential_generation) "
        "VALUES(%s,'api_key',%s,3)",
        (revision["revision_fingerprint"], credential),
    )


def retained_row(dsn: str, table: str, key: str, value: str) -> dict[str, Any]:
    assert (table, key) in (("integration_draft", "integration_id"), ("integration_revision", "revision_fingerprint"))
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        result = connection.execute(f"SELECT * FROM {table} WHERE {key}=%s", (value,)).fetchone()
    assert result is not None
    return result


def historical(probe: Path, dsn: str, *, draft: bool = True, revisions: int = 2) -> tuple[str, list[str]]:
    # SQL only establishes retained test facts. Native owners derive and restore every identity.
    ident, credential_id = str(uuid4()), str(uuid4())
    produced = native_record(
        probe,
        op="integration-fixture-records",
        integration_id=ident,
        credential_id=credential_id,
        descriptor_document=json.dumps(descriptor(probe)),
        draft=draft,
        revisions=[
            {
                "revision_sequence": sequence,
                "configuration_document": json.dumps(
                    {
                        "name": "Historical",
                        "timeout_seconds": 2.0,
                        "arbitrary": {"$serde_json::private::Number": 10**70},
                    }
                ),
                "probe_configuration_document": None if sequence == 1 else "{}",
            }
            for sequence in range(1, revisions + 1)
        ],
    )
    fingerprints = [revision["revision_fingerprint"] for revision in produced["revisions"]]
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "INSERT INTO integration(integration_id,type_id,display_name,lifecycle_state,created_at,updated_at) "
            "VALUES(%s,'binance.spot.market_data','Retained source','ACTIVE',%s,%s)",
            (ident, NOW, NOW),
        )
        connection.execute(
            "INSERT INTO product_credential(credential_id,credential_kind,subject_id,secret_name,generation,ciphertext,key_version,created_at,updated_at) "
            "VALUES(%s,'INTEGRATION_SECRET',%s,'api_key',3,%s,1,%s,%s)",
            (credential_id, ident, b"never-a-public-DTO", NOW, NOW),
        )
        for revision in produced["revisions"]:
            insert_revision(connection, ident, credential_id, revision)
        if fingerprints:
            connection.execute(
                "UPDATE integration SET current_revision_fingerprint=%s WHERE integration_id=%s",
                (fingerprints[-1], ident),
            )
        if draft:
            row = produced["draft"]
            columns = [
                "base_revision_fingerprint",
                "type_descriptor_fingerprint",
                "type_descriptor_document",
                "public_configuration_document",
                "probe_configuration_document",
                "draft_version",
                "draft_fingerprint",
            ]
            connection.execute(
                "INSERT INTO integration_draft(integration_id,"
                + ",".join(columns)
                + ",created_at,updated_at) VALUES("
                + ",".join(["%s"] * (len(columns) + 3))
                + ")",
                [ident, *[row[key] for key in columns], NOW, NOW],
            )
            connection.execute(
                "INSERT INTO integration_draft_secret_binding(integration_id,field_id,credential_id,credential_generation) "
                "VALUES(%s,'api_key',%s,3)",
                (ident, credential_id),
            )
        connection.execute("UPDATE product_credential SET generation=7 WHERE credential_id=%s", (credential_id,))
    return ident, fingerprints


def test_native_http_reads_exact_historical_dtos_without_catalog_or_secret_exposure(
    integration_http_probe: Path, query_db: str
) -> None:
    ident, revisions = historical(integration_http_probe, query_db)
    paths: list[str | dict[str, object]] = [
        f"/api/v2/integrations/{ident}",
        f"/api/v2/integrations/{ident}/draft",
        f"/api/v2/integrations/{ident}/revisions",
        *[f"/api/v2/integrations/{ident}/revisions/{fp}" for fp in revisions],
    ]
    # Independent expected wire facts for this controlled historical fixture.
    # No retired HTTP DTO, current executable catalog, secret decryption, or
    # response-derived expected value participates in this comparison.
    draft = retained_row(query_db, "integration_draft", "integration_id", ident)
    timestamp = "2026-09-20T00:00:00.123400Z"
    secret_status = [{"field_id": "api_key", "configured": True, "generation": 3}]
    summaries = []
    retained = []
    for sequence, fingerprint in enumerate(revisions, 1):
        revision = retained_row(query_db, "integration_revision", "revision_fingerprint", fingerprint)
        summary = {
            "revision_fingerprint": fingerprint,
            "revision_sequence": sequence,
            "type_id": "binance.spot.market_data",
            "type_descriptor_fingerprint": revision["type_descriptor_fingerprint"],
            "configuration_fingerprint": revision["configuration_fingerprint"],
            "runtime_configuration_fingerprint": revision["runtime_configuration_fingerprint"],
            "probe_configuration_fingerprint": revision["probe_configuration_fingerprint"],
            "secret_binding_fingerprint": revision["secret_binding_fingerprint"],
            "created_at": timestamp,
        }
        summaries.append(summary)
        retained.append(
            {
                **summary,
                "schema_version": 1,
                "integration_id": ident,
                "type_descriptor": {
                    **revision["type_descriptor_document"],
                    "fingerprint": revision["type_descriptor_fingerprint"],
                },
                "configuration": {
                    "name": "Historical",
                    "timeout_seconds": 2.0,
                    "arbitrary": {"$serde_json::private::Number": 10**70},
                },
                "probe_configuration": None if sequence == 1 else {},
                "secret_bindings": secret_status,
            }
        )
    expected = [
        {
            "schema_version": 1,
            "integration_id": ident,
            "type_id": "binance.spot.market_data",
            "display_name": "Retained source",
            "lifecycle_state": "ACTIVE",
            "current_revision_fingerprint": revisions[-1],
            "created_at": timestamp,
            "updated_at": timestamp,
        },
        {
            "schema_version": 1,
            "integration_id": ident,
            "base_revision_fingerprint": revisions[0],
            "pinned_type_descriptor_fingerprint": draft["type_descriptor_fingerprint"],
            "type_descriptor": {
                **draft["type_descriptor_document"],
                "fingerprint": draft["type_descriptor_fingerprint"],
            },
            "public_configuration": {"name": "Draft", "timeout_seconds": 1.0},
            "probe_configuration": {},
            "draft_version": 2,
            "draft_fingerprint": draft["draft_fingerprint"],
            "secret_statuses": secret_status,
            "created_at": timestamp,
            "updated_at": timestamp,
        },
        {"items": summaries},
        *retained,
    ]
    for _process in range(2):
        actual = requests(integration_http_probe, paths, shadow=True)
        assert [r["status"] for r in actual] == [200] * len(paths)
        assert [r["body"] for r in actual] == expected
        assert actual[0]["body"]["created_at"] == "2026-09-20T00:00:00.123400Z"
        for response in actual:
            assert response["headers"]["cache-control"] == "no-store"
            assert "set-cookie" not in response["headers"]
            assert "never-a-public-DTO" not in response["raw"]
            assert "credential_id" not in response["raw"]
        assert "2.0" in actual[3]["raw"] and "1.0" in actual[1]["raw"]
        assert actual[1]["body"]["secret_statuses"] == [{"field_id": "api_key", "configured": True, "generation": 3}]


def test_native_http_list_exact_filters_and_no_partial_missing_draft(
    integration_http_probe: Path, query_db: str
) -> None:
    assert requests(integration_http_probe, ["/api/v2/integrations"], rows=0)[0]["body"] == {"items": []}
    ident, _ = historical(integration_http_probe, query_db)
    paths: list[str | dict[str, object]] = [
        "/api/v2/integrations",
        "/api/v2/integrations?type_id=binance.spot.market_data",
        "/api/v2/integrations?type_id=",
        "/api/v2/integrations?type_id=NOT%20CANONICAL",
        "/api/v2/integrations?lifecycle_state=DISABLED",
        "/api/v2/integrations?lifecycle_state=wrong",
    ]
    actual = requests(integration_http_probe, paths)
    item = actual[0]["body"]["items"][0]
    assert item["integration_id"] == ident and item["category"] == "DATA_SOURCE" and item["draft_version"] == 2
    assert actual[1]["body"] == actual[0]["body"]
    assert [r["body"] for r in actual[2:5]] == [{"items": []}] * 3
    assert actual[5]["status"] == 400
    with psycopg.connect(query_db) as connection:
        connection.execute("DELETE FROM integration_draft_secret_binding")
        connection.execute("DELETE FROM integration_draft")
    actual = requests(
        integration_http_probe,
        ["/api/v2/integrations", f"/api/v2/integrations/{ident}/draft"],
    )
    assert [r["status"] for r in actual] == [404, 404]
    assert all(r["body"]["error"]["code"] == "INTEGRATION_DRAFT_NOT_FOUND" for r in actual)


def test_native_http_absence_foreign_revision_invalid_and_auth(integration_http_probe: Path, query_db: str) -> None:
    ident, revisions = historical(integration_http_probe, query_db)
    other = str(uuid4())
    with psycopg.connect(query_db) as connection:
        connection.execute(
            "INSERT INTO integration(integration_id,type_id,display_name,lifecycle_state,created_at,updated_at) "
            "VALUES(%s,'uninstalled.type','Other','ACTIVE',%s,%s)",
            (other, NOW, NOW),
        )
    missing = str(uuid4())
    paths: list[str | dict[str, object]] = [
        f"/api/v2/integrations/{missing}",
        f"/api/v2/integrations/{ident}/revisions/{'a' * 64}",
        f"/api/v2/integrations/{other}/revisions/{revisions[0]}",
        "/api/v2/integrations/not-uuid",
        {"path": f"/api/v2/integrations/{ident}", "authenticated": False},
        {"path": f"/api/v2/integrations/{ident}", "method": "HEAD"},
    ]
    actual = requests(integration_http_probe, paths)
    assert [r["status"] for r in actual] == [404, 404, 404, 400, 401, 405]
    assert actual[2]["body"]["error"]["code"] == "INTEGRATION_REVISION_NOT_FOUND"


@pytest.mark.parametrize("rows,work", [(0, 1_000_000), (3, 1_000_000), (100, 50)])
def test_native_http_exhaustion_never_empty_or_partial(
    integration_http_probe: Path, query_db: str, rows: int, work: int
) -> None:
    ident, _ = historical(integration_http_probe, query_db)
    actual = requests(
        integration_http_probe,
        ["/api/v2/integrations", f"/api/v2/integrations/{ident}"],
        rows=rows,
        work=work,
    )
    assert all(r["status"] == 503 for r in actual)
    assert all(r["body"]["error"]["code"] == "INTEGRATION_PERSISTENCE_UNAVAILABLE" for r in actual)


def test_native_http_dangling_history_does_not_become_absence(integration_http_probe: Path, query_db: str) -> None:
    ident, _ = historical(integration_http_probe, query_db)
    with psycopg.connect(query_db) as connection:
        connection.execute("ALTER TABLE integration DISABLE TRIGGER ALL")
        connection.execute("UPDATE integration SET current_revision_fingerprint=%s", ("a" * 64,))
    actual = requests(
        integration_http_probe,
        ["/api/v2/integrations", f"/api/v2/integrations/{ident}/revisions/{'b' * 64}"],
    )
    assert all(r["status"] == 500 for r in actual)
    assert all(r["body"]["error"]["code"] == "INTEGRATION_REVISION_CORRUPT" for r in actual)


def test_native_http_list_shares_one_total_budget_across_owners(integration_http_probe: Path, query_db: str) -> None:
    ids = [historical(integration_http_probe, query_db, revisions=0)[0] for _ in range(2)]
    assert requests(integration_http_probe, ["/api/v2/integrations"], rows=7)[0]["status"] == 503
    result = requests(integration_http_probe, ["/api/v2/integrations"], rows=8)[0]
    assert result["status"] == 200
    assert [item["integration_id"] for item in result["body"]["items"]] == sorted(ids)


def test_historical_descriptor_uses_transport_shape_not_current_authoring_validation(
    integration_http_probe: Path, query_db: str
) -> None:
    ident, _ = historical(integration_http_probe, query_db)
    document = descriptor(integration_http_probe)
    fields = cast(dict[str, Any], document["configuration_contract"])
    for field in fields["fields"]:
        if field["field_id"] == "timeout_seconds":
            field["default"] = "2.0"
    fields["fingerprint"] = fingerprint(integration_http_probe, {k: v for k, v in fields.items() if k != "fingerprint"})
    with psycopg.connect(query_db) as connection:
        row = connection.execute(
            "SELECT credential_id::text FROM product_credential WHERE subject_id=%s", (ident,)
        ).fetchone()
        assert row is not None
        credential_id = row[0]
        connection.execute("UPDATE product_credential SET generation=3")
    fingerprints = []
    for sequence, category in [
        (3, "DATA_SOURCE"),
        (4, "IMPOSSIBLE"),
        (5, "DATA_SOURCE"),
        (6, "DATA_SOURCE"),
        (7, "DATA_SOURCE"),
        (8, "DATA_SOURCE"),
    ]:
        document["category"] = category
        probe = cast(dict[str, Any], document["probe_contract"])
        probe["probe_mode"] = "CONNECT_ONLY" if sequence == 5 else "DEFAULT_INSTRUMENT"
        if sequence == 6:
            for item in fields["fields"]:
                if item["field_id"] == "timeout_seconds":
                    item["minimum"] = {"$serde_json::private::Number": "0.1"}
        if sequence in (7, 8):
            for item in fields["fields"]:
                if item["field_id"] == "timeout_seconds":
                    item["default"] = (
                        10**70 if sequence == 7 else '{"$serde_json::private::RawValue":"ordinary metadata"}'
                    )
                    item["minimum"] = 10**70
                    item["maximum"] = 10**70 + 17
        fields["fingerprint"] = fingerprint(
            integration_http_probe, {k: v for k, v in fields.items() if k != "fingerprint"}
        )
        probe["fingerprint"] = fingerprint(
            integration_http_probe, {k: v for k, v in probe.items() if k != "fingerprint"}
        )
        produced = native_record(
            integration_http_probe,
            op="integration-fixture-records",
            integration_id=ident,
            credential_id=credential_id,
            descriptor_document=json.dumps(document),
            draft=False,
            revisions=[
                {
                    "revision_sequence": sequence,
                    "configuration_document": json.dumps({"name": "Retained", "timeout_seconds": 2.0}),
                    "probe_configuration_document": None,
                }
            ],
        )
        revision = produced["revisions"][0]
        with psycopg.connect(query_db) as connection:
            insert_revision(connection, ident, credential_id, revision)
        fingerprints.append(revision["revision_fingerprint"])
    actual = requests(
        integration_http_probe,
        [f"/api/v2/integrations/{ident}/revisions/{fp}" for fp in fingerprints],
    )
    assert actual[0]["status"] == 200
    assert (
        next(
            f
            for f in actual[0]["body"]["type_descriptor"]["configuration_contract"]["fields"]
            if f["field_id"] == "timeout_seconds"
        )["default"]
        == "2.0"
    )
    assert [item["status"] for item in actual[1:4]] == [500, 500, 500]
    assert all(item["body"]["error"]["code"] == "INTEGRATION_REVISION_CORRUPT" for item in actual[1:4])
    assert [item["status"] for item in actual[4:]] == [200, 200]
    for index, expected in [(4, 10**70), (5, '{"$serde_json::private::RawValue":"ordinary metadata"}')]:
        field = next(
            f
            for f in actual[index]["body"]["type_descriptor"]["configuration_contract"]["fields"]
            if f["field_id"] == "timeout_seconds"
        )
        assert field["default"] == expected
        assert field["minimum"] == 10**70 and field["maximum"] == 10**70 + 17


def test_native_http_absence_resource_semantics(integration_http_probe: Path, query_db: str) -> None:
    ident = str(uuid4())
    actual = requests(
        integration_http_probe,
        [
            f"/api/v2/integrations/{ident}/draft",
            f"/api/v2/integrations/{ident}/revisions",
            f"/api/v2/integrations/{ident}/revisions/{'a' * 64}",
        ],
    )
    assert [r["status"] for r in actual] == [404, 200, 404]
    assert actual[0]["body"]["error"]["code"] == "INTEGRATION_DRAFT_NOT_FOUND"
    assert actual[1]["body"] == {"items": []}
    assert actual[2]["body"]["error"]["code"] == "INTEGRATION_REVISION_NOT_FOUND"


def test_native_http_list_keeps_one_snapshot_during_concurrent_draft_removal(
    integration_http_probe: Path, query_db: str
) -> None:
    from packages.backend.tests.postgres_link import wait_for_database_lock_barrier

    ident, _ = historical(integration_http_probe, query_db)
    with psycopg.connect(query_db) as writer:
        blocker = writer.execute("SELECT pg_backend_pid()").fetchone()
        assert blocker is not None
        writer.execute("LOCK TABLE integration_draft IN ACCESS EXCLUSIVE MODE")
        child = subprocess.Popen(
            [str(integration_http_probe), "--pid-barrier"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert child.stdin is not None and child.stdout is not None and child.stderr is not None
        try:
            child.stdin.write(
                json.dumps(
                    {
                        "rows": 100,
                        "work": 1_000_000,
                        "requests": [{"path": "/api/v2/integrations"}],
                    }
                )
            )
            child.stdin.close()
            ready = json.loads(child.stdout.readline())
            wait_for_database_lock_barrier(query_db, child, ready["backend_pid"], blocker[0], "relation")
            writer.execute(
                "UPDATE integration SET display_name='Concurrent newer' WHERE integration_id=%s",
                (ident,),
            )
            writer.execute(
                "DELETE FROM integration_draft_secret_binding WHERE integration_id=%s",
                (ident,),
            )
            writer.execute("DELETE FROM integration_draft WHERE integration_id=%s", (ident,))
            writer.commit()
            output = child.stdout.read()
            assert child.wait(timeout=20) == 0, child.stderr.read()
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=20)
        response = json.loads(output)["responses"][0]
        assert response["status"] == 200
        item = json.loads(response["raw"])["items"][0]
        assert (
            item["integration_id"] == ident and item["display_name"] == "Retained source" and item["draft_version"] == 2
        )
    assert requests(integration_http_probe, ["/api/v2/integrations"])[0]["status"] == 404


def test_native_integration_routes_do_not_grant_writes_or_deep_paths(
    integration_http_probe: Path, query_db: str
) -> None:
    ident, _ = historical(integration_http_probe, query_db)
    actual = requests(
        integration_http_probe,
        [
            {"path": "/api/v2/integrations", "method": "POST"},
            {"path": f"/api/v2/integrations/{ident}/draft", "method": "PUT"},
            {"path": f"/api/v2/integrations/{ident}/draft/secrets/api_key", "method": "DELETE"},
            f"/api/v2/integrations/{ident}/draft/extra",
            f"/api/v2/integrations/{ident}/probe",
            "/api/v2/market-data/sources",
        ],
    )
    assert [r["status"] for r in actual] == [403] * len(actual)
    assert requests(integration_http_probe, [f"/api/v2/integrations/{ident}/draft"])[0]["body"]["draft_version"] == 2


@pytest.mark.parametrize(
    "relation,copy",
    [
        ("integration", True),
        ("integration", False),
        ("integration_draft", True),
        ("integration_draft_secret_binding", True),
        ("integration_revision", True),
        ("integration_revision_secret_binding", True),
    ],
)
def test_canonical_relation_missing_never_falls_back_to_matching_or_empty_temp(
    integration_http_probe: Path, query_db: str, relation: str, copy: bool
) -> None:
    ident, revisions = historical(integration_http_probe, query_db)
    paths = [
        "/api/v2/integrations",
        f"/api/v2/integrations/{ident}",
        f"/api/v2/integrations/{ident}/draft",
        f"/api/v2/integrations/{ident}/revisions",
        f"/api/v2/integrations/{ident}/revisions/{revisions[0]}",
    ]
    actual = requests(integration_http_probe, paths, missing_relation=relation, copy_shadow=copy)
    assert [item["status"] for item in actual] == [503] * len(paths)
    assert all(item["body"]["error"]["code"] == "INTEGRATION_PERSISTENCE_UNAVAILABLE" for item in actual)
