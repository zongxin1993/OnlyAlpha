"""Independent canonical SQL observations and current Rust-owned fixture records.

These functions are test preparation/observations, not a persistence Authority.
All mutation-under-test still goes through the actual native command process.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .native_probe import call

_JSON_FIELDS = {
    "type_descriptor_document",
    "public_configuration_document",
    "configuration_document",
    "probe_configuration_document",
}


def _plain(row):
    return {key: str(value) if isinstance(value, UUID) else value for key, value in row.items()}


def persisted_row(dsn: str, table: str, field: str, value: str) -> dict[str, Any]:
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        row = connection.execute(
            sql.SQL("SELECT * FROM {} WHERE {}=%s").format(sql.Identifier("public", table), sql.Identifier(field)),
            (value,),
        ).fetchone()
    assert row is not None
    return _plain(row)


def integration_row(dsn, ident):
    return persisted_row(dsn, "integration", "integration_id", ident)


def draft_row(dsn, ident):
    return persisted_row(dsn, "integration_draft", "integration_id", ident)


def revision_row(dsn, fingerprint):
    return persisted_row(dsn, "integration_revision", "revision_fingerprint", fingerprint)


def draft_bindings(dsn, ident):
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        rows = connection.execute(
            "SELECT field_id,credential_id::text AS credential_id,credential_generation FROM public.integration_draft_secret_binding WHERE integration_id=%s ORDER BY field_id",
            (ident,),
        ).fetchall()
    return tuple(dict(row) for row in rows)


def revision_history(dsn, ident):
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        rows = connection.execute(
            "SELECT * FROM public.integration_revision WHERE integration_id=%s ORDER BY revision_sequence", (ident,)
        ).fetchall()
    return tuple(_plain(row) for row in rows)


def fixture_record(
    probe: Path,
    *,
    kind: str,
    ident: str,
    descriptor: dict,
    public: dict,
    probe_configuration,
    bindings,
    created_at,
    **values,
):
    request = {
        "op": "integration-fixture-records",
        "kind": kind,
        "integration_id": ident,
        "type_id": descriptor["type_id"],
        "descriptor": json.dumps(descriptor),
        "public": json.dumps(public),
        "probe": None if probe_configuration is None else json.dumps(probe_configuration),
        "bindings": list(bindings),
        "created_at": created_at.isoformat(),
        **values,
    }
    record = call(probe, request)
    assert "error" not in record
    return record


def decoded_record(record):
    return {
        key: json.loads(value)
        if key in _JSON_FIELDS and value is not None
        else datetime.fromisoformat(value)
        if key in {"created_at", "updated_at"}
        else value
        for key, value in record.items()
    }


def insert_fixture_record(connection, table, record):
    assert table in {"integration_draft", "integration_revision"}
    keys = list(record)
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier("public", table),
        sql.SQL(",").join(map(sql.Identifier, keys)),
        sql.SQL(",").join(sql.SQL("%s::json") if key in _JSON_FIELDS else sql.SQL("%s") for key in keys),
    )
    connection.execute(query, tuple(record[key] for key in keys))


def credential_rotate(probe, ident, generation, secret):
    result = call(
        probe,
        {
            "op": "credential",
            "command_id": str(uuid4()),
            "action": "rotate",
            "rows": 20,
            "work": 100_000,
            "credential_id": ident,
            "generation": generation,
            "secret": secret,
        },
    )
    assert "error" not in result, result
    return result["metadata"]


def credential_create(probe, kind, subject, field, secret):
    result = call(
        probe,
        {
            "op": "credential",
            "command_id": str(uuid4()),
            "action": "create",
            "rows": 20,
            "work": 100_000,
            "credential_kind": kind,
            "subject_id": subject,
            "secret_name": field,
            "secret": secret,
        },
    )
    assert "error" not in result, result
    return result["metadata"]
