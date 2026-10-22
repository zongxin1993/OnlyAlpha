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

from onlyalpha.application.integration_configuration import (
    OnlyIntegrationId,
    OnlyIntegrationRevision,
    OnlyIntegrationSecretBinding,
    only_integration_json_document,
)
from onlyalpha.persistence.postgres.integration_store import (
    OnlyPostgresIntegrationStore,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from tests.support.integration_configuration import integration_descriptor

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]
NOW = datetime(2026, 9, 20, 0, 0, 0, 123400, tzinfo=UTC)


@pytest.fixture
def query_db(postgres_dsn: str) -> str:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    return postgres_dsn


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
    )
    assert result.returncode == 0, result.stderr
    responses = cast(list[dict[str, Any]], json.loads(result.stdout)["responses"])
    for response in responses:
        response["body"] = json.loads(response["raw"]) if response["raw"] else None
    return responses


def historical(dsn: str, *, draft: bool = True, revisions: int = 2) -> tuple[str, list[str]]:
    # Test preparation creates explicit existing retained facts, not the User Goal.
    # No current plugin installation or secret decryption is involved.
    from dataclasses import replace

    from onlyalpha.plugin.integration import OnlyIntegrationProbeCheck

    descriptor = integration_descriptor()
    assert descriptor.probe_contract is not None
    descriptor = replace(
        descriptor, probe_contract=replace(descriptor.probe_contract, probe_checks=tuple(OnlyIntegrationProbeCheck))
    )
    ident = OnlyIntegrationId(str(uuid4()))
    store = OnlyPostgresIntegrationStore(dsn, now=lambda: NOW)
    store.create_integration(ident, descriptor.type_id, "Retained source")
    credential_id = str(uuid4())
    with psycopg.connect(dsn) as connection:
        connection.execute(
            "INSERT INTO product_credential(credential_id,credential_kind,subject_id,secret_name,generation,ciphertext,key_version,created_at,updated_at) VALUES(%s,'INTEGRATION_SECRET',%s,'api_key',3,%s,1,%s,%s)",
            (credential_id, ident.value, b"never-a-public-DTO", NOW, NOW),
        )
    binding = OnlyIntegrationSecretBinding("api_key", credential_id, 3)
    fingerprints = []
    for sequence in range(1, revisions + 1):
        revision = OnlyIntegrationRevision.from_resolved(
            integration_id=ident,
            revision_sequence=sequence,
            type_id=descriptor.type_id.value,
            type_descriptor_fingerprint=descriptor.fingerprint,
            type_descriptor_document=descriptor.to_dict(include_fingerprint=False),
            configuration_document={
                "name": "Historical",
                "timeout_seconds": 2.0,
                "arbitrary": {"$serde_json::private::Number": 10**70},
            },
            probe_configuration_document=None if sequence == 1 else {},
            secret_bindings=(binding,),
            created_at=NOW,
        )
        store.insert_revision(revision, (binding,))
        store.set_current_revision(ident, revision.revision_fingerprint)
        fingerprints.append(revision.revision_fingerprint)
    if draft:
        store.create_draft(
            ident,
            descriptor,
            {"name": "Draft", "timeout_seconds": 1.0},
            {},
            base_revision_fingerprint=fingerprints[0] if fingerprints else None,
        )
        store.replace_draft_secret_bindings(ident, 1, (binding,))
    with psycopg.connect(dsn) as connection:
        connection.execute("UPDATE product_credential SET generation=7 WHERE credential_id=%s", (credential_id,))
    return ident.value, fingerprints


def test_native_http_reads_exact_historical_dtos_without_catalog_or_secret_exposure(
    integration_http_probe: Path, query_db: str
) -> None:
    ident, revisions = historical(query_db)
    paths: list[str | dict[str, object]] = [
        f"/api/v2/integrations/{ident}",
        f"/api/v2/integrations/{ident}/draft",
        f"/api/v2/integrations/{ident}/revisions",
        *[f"/api/v2/integrations/{ident}/revisions/{fp}" for fp in revisions],
    ]
    # Independent expected wire facts for this controlled historical fixture.
    # No retired HTTP DTO, current executable catalog, secret decryption, or
    # response-derived expected value participates in this comparison.
    store = OnlyPostgresIntegrationStore(query_db)
    draft = store.load_draft(OnlyIntegrationId(ident))
    timestamp = "2026-09-20T00:00:00.123400Z"
    secret_status = [{"field_id": "api_key", "configured": True, "generation": 3}]
    summaries = []
    retained = []
    for sequence, fingerprint in enumerate(revisions, 1):
        revision = store.load_revision(fingerprint)
        summary = {
            "revision_fingerprint": fingerprint,
            "revision_sequence": sequence,
            "type_id": "binance.spot.market_data",
            "type_descriptor_fingerprint": revision.type_descriptor_fingerprint,
            "configuration_fingerprint": revision.configuration_fingerprint,
            "runtime_configuration_fingerprint": revision.runtime_configuration_fingerprint,
            "probe_configuration_fingerprint": revision.probe_configuration_fingerprint,
            "secret_binding_fingerprint": revision.secret_binding_fingerprint,
            "created_at": timestamp,
        }
        summaries.append(summary)
        retained.append(
            {
                **summary,
                "schema_version": 1,
                "integration_id": ident,
                "type_descriptor": {
                    **only_integration_json_document(revision.type_descriptor_document),
                    "fingerprint": revision.type_descriptor_fingerprint,
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
            "pinned_type_descriptor_fingerprint": draft.type_descriptor_fingerprint,
            "type_descriptor": {
                **only_integration_json_document(draft.type_descriptor_document),
                "fingerprint": draft.type_descriptor_fingerprint,
            },
            "public_configuration": {"name": "Draft", "timeout_seconds": 1.0},
            "probe_configuration": {},
            "draft_version": 2,
            "draft_fingerprint": draft.draft_fingerprint,
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
    ident, _ = historical(query_db)
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
    ident, revisions = historical(query_db)
    other = str(uuid4())
    from onlyalpha.plugin.integration import OnlyIntegrationTypeId

    OnlyPostgresIntegrationStore(query_db, now=lambda: NOW).create_integration(
        OnlyIntegrationId(other), OnlyIntegrationTypeId("uninstalled.type"), "Other"
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
    ident, _ = historical(query_db)
    actual = requests(
        integration_http_probe,
        ["/api/v2/integrations", f"/api/v2/integrations/{ident}"],
        rows=rows,
        work=work,
    )
    assert all(r["status"] == 503 for r in actual)
    assert all(r["body"]["error"]["code"] == "INTEGRATION_PERSISTENCE_UNAVAILABLE" for r in actual)


def test_native_http_dangling_history_does_not_become_absence(integration_http_probe: Path, query_db: str) -> None:
    ident, _ = historical(query_db)
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
    ids = [historical(query_db, revisions=0)[0] for _ in range(2)]
    assert requests(integration_http_probe, ["/api/v2/integrations"], rows=7)[0]["status"] == 503
    result = requests(integration_http_probe, ["/api/v2/integrations"], rows=8)[0]
    assert result["status"] == 200
    assert [item["integration_id"] for item in result["body"]["items"]] == sorted(ids)


def test_historical_descriptor_uses_transport_shape_not_current_authoring_validation(
    integration_http_probe: Path, query_db: str
) -> None:
    from onlyalpha.canonical import only_canonical_fingerprint

    ident, _ = historical(query_db)
    store = OnlyPostgresIntegrationStore(query_db, now=lambda: NOW)
    descriptor = integration_descriptor()
    document = descriptor.to_dict(include_fingerprint=False)
    fields = cast(dict[str, Any], document["configuration_contract"])
    for field in fields["fields"]:
        if field["field_id"] == "timeout_seconds":
            field["default"] = "2.0"
    fields["fingerprint"] = only_canonical_fingerprint({k: v for k, v in fields.items() if k != "fingerprint"})
    current = store.load_integration(OnlyIntegrationId(ident)).current_revision_fingerprint
    assert current is not None
    binding = store.load_revision_secret_bindings(current)
    with psycopg.connect(query_db) as connection:
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
        fields["fingerprint"] = only_canonical_fingerprint({k: v for k, v in fields.items() if k != "fingerprint"})
        probe["fingerprint"] = only_canonical_fingerprint({k: v for k, v in probe.items() if k != "fingerprint"})
        revision = OnlyIntegrationRevision.from_resolved(
            integration_id=OnlyIntegrationId(ident),
            revision_sequence=sequence,
            type_id=descriptor.type_id.value,
            type_descriptor_fingerprint=only_canonical_fingerprint(document),
            type_descriptor_document=document,
            configuration_document={"name": "Retained", "timeout_seconds": 2.0},
            probe_configuration_document=None,
            secret_bindings=binding,
            created_at=NOW,
        )
        store.insert_revision(revision, binding)
        fingerprints.append(revision.revision_fingerprint)
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
    from tests.support.postgres_link import wait_for_database_lock_barrier

    ident, _ = historical(query_db)
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
    ident, _ = historical(query_db)
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
    ident, revisions = historical(query_db)
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
