"""Actual owning Integration effects must be proven before accepted receipts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg
import pytest

from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority

from .support.integration import (
    call,
    clear,
    configured,
    create_request,
    edit,
    lifecycle_request,
    owning_facts,
    publish,
    replay_request,
    reset,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]


@pytest.fixture
def effect_db(postgres_dsn: str) -> str:
    OnlyPostgresMigrationAuthority(postgres_dsn).migrate()
    return postgres_dsn


@pytest.mark.parametrize(
    "case",
    [
        "create_head",
        "create_draft",
        "lifecycle",
        "update",
        "reset",
        "clear",
        "publish_head",
        "publish_draft",
        "publish_sequence",
        "publish_time",
        "publish_value_type",
    ],
)
def test_an_accepted_receipt_requires_the_actual_complete_command_effect(
    native_probe: Path, effect_db: str, case: str
) -> None:
    if case in ("reset", "clear") or case.startswith("publish"):
        request, _ = configured(native_probe, effect_db)
    else:
        request = create_request()
        if not case.startswith("create"):
            assert call(native_probe, request)["replayed"] is False
    command: dict[str, Any]
    if case.startswith("create"):
        command = request
    elif case == "lifecycle":
        command = lifecycle_request(request, "ACTIVE", "DISABLED")
    elif case == "update":
        command = edit(request)
    elif case == "reset":
        command = reset(request, 3)
    elif case == "clear":
        command = clear(request)
    else:
        if case == "publish_value_type":
            assert (
                call(native_probe, edit(request, version=3, public='{"name":"controlled","timeout_seconds":1.5}'))[
                    "replayed"
                ]
                is False
            )
        command = publish(request, 4 if case == "publish_value_type" else 3)
    table, event, mutation = {
        "create_head": ("integration", "INSERT", "NEW.lifecycle_state='DISABLED'"),
        "create_draft": ("integration_draft", "INSERT", "NEW.draft_version=2"),
        "lifecycle": ("integration", "UPDATE", "NEW.lifecycle_state=OLD.lifecycle_state"),
        "update": ("integration_draft", "UPDATE", "NEW.draft_version=NEW.draft_version+1"),
        "reset": ("integration_draft_secret_binding", "DELETE", "RETURN NULL"),
        "clear": ("integration_draft_secret_binding", "DELETE", "RETURN NULL"),
        "publish_head": ("integration", "UPDATE", "NEW.current_revision_fingerprint=OLD.current_revision_fingerprint"),
        "publish_draft": ("integration_draft", "UPDATE", "NEW.draft_version=NEW.draft_version+1"),
        "publish_sequence": ("integration_revision", "INSERT", "NEW.revision_sequence=NEW.revision_sequence+1"),
        "publish_time": ("integration_revision", "INSERT", "NEW.created_at=NEW.created_at+interval '1 second'"),
        "publish_value_type": (
            "integration_revision",
            "INSERT",
            "NEW.configuration_document=jsonb_set(NEW.configuration_document::jsonb,'{timeout_seconds}','\"1.5\"'::jsonb)::json",
        ),
    }[case]
    before = owning_facts(effect_db)
    with psycopg.connect(effect_db) as connection:
        connection.execute(
            f"CREATE FUNCTION mutate_integration_effect() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {mutation}; RETURN NEW; END $$"
        )
        connection.execute(
            f"CREATE TRIGGER mutate_integration_effect BEFORE {event} ON {table} FOR EACH ROW EXECUTE FUNCTION mutate_integration_effect()"
        )
    expected = (
        "INTEGRATION_REVISION_CORRUPT"
        if case in ("publish_sequence", "publish_time", "publish_value_type")
        else "INTEGRATION_PERSISTENCE_CONFLICT"
    )
    assert call(native_probe, command) == {"error": expected}
    assert call(native_probe, replay_request(command)) == {"result": None}
    assert owning_facts(effect_db) == before


@pytest.mark.parametrize("stored_number", ['"1.5"', "1.50"])
def test_publish_reuse_validates_actual_stored_types_without_rewriting_history(
    native_probe: Path, effect_db: str, stored_number: str
) -> None:
    request, _ = configured(native_probe, effect_db)
    assert (
        call(native_probe, edit(request, version=3, public='{"name":"controlled","timeout_seconds":1.5}'))["replayed"]
        is False
    )
    first = call(native_probe, publish(request, 4))
    fingerprint = first["result"]["receipt"]["outcome_id"]
    with psycopg.connect(effect_db) as connection:
        # Controlled corruption only in the fresh canonical _test schema.
        connection.execute("ALTER TABLE integration_revision DISABLE TRIGGER integration_revision_immutable_trigger")
        connection.execute(
            "UPDATE integration_revision SET configuration_document=%s::json WHERE revision_fingerprint=%s",
            ('{"name":"controlled","timeout_seconds":' + stored_number + "}", fingerprint),
        )
        connection.execute("ALTER TABLE integration_revision ENABLE TRIGGER integration_revision_immutable_trigger")
    before = owning_facts(effect_db)
    command = publish(request, 5)
    result = call(native_probe, command)
    if stored_number.startswith('"'):
        assert result == {"error": "INTEGRATION_REVISION_CORRUPT"}
        assert call(native_probe, replay_request(command)) == {"result": None}
        assert owning_facts(effect_db) == before
    else:
        assert result["replayed"] is False
        assert result["result"]["receipt"]["outcome_id"] == fingerprint
        after = owning_facts(effect_db)
        assert after["integration_revision"] == before["integration_revision"]
        assert after["integration_revision_secret_binding"] == before["integration_revision_secret_binding"]
        with psycopg.connect(effect_db) as connection:
            row = connection.execute(
                "SELECT draft_version FROM integration_draft WHERE integration_id=%s::uuid",
                (request["integration_id"],),
            ).fetchone()
        assert row == (6,)
