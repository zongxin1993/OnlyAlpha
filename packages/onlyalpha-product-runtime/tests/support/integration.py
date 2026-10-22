"""Shared canonical PostgreSQL Integration test inputs and effect snapshots."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import psycopg

from onlyalpha.application.integration_application import (
    _admission,
    only_integration_secret_commitment,
)
from onlyalpha.application.integration_configuration import (
    OnlyIntegrationId,
    only_integration_json_document,
)
from onlyalpha.application.product_command_receipt import OnlyProductCommandId, OnlyProductCommandKind
from onlyalpha.persistence.postgres.integration_product_store import OnlyPostgresIntegrationProductStore
from tests.support.integration_configuration import integration_descriptor as _descriptor

_TABLES = (
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
)


MASTER_KEY = b"k" * 32


NOW = datetime(2026, 9, 20, tzinfo=UTC)


def create_request() -> dict[str, Any]:
    descriptor = json.loads((Path(__file__).parents[1] / "fixtures/integration_resolver.json").read_text())[0][
        "descriptor"
    ]
    return {
        "op": "integration-write",
        "action": "create",
        "command_id": str(uuid4()),
        "integration_id": str(uuid4()),
        "type_id": json.loads(descriptor)["type_id"],
        "display_name": "Data source",
        "descriptor": descriptor,
        "accepted_at": "2026-09-20T00:00:00Z",
    }


def call(probe: Path, request: dict[str, Any]) -> dict[str, Any]:
    result = subprocess.run([str(probe)], input=json.dumps(request), text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


def replay_request(request: dict[str, Any]) -> dict[str, Any]:
    if request["action"] == "create":
        kind = OnlyProductCommandKind.CREATE_INTEGRATION
        payload = {k: request[k] for k in ("integration_id", "type_id", "display_name")}
    elif request["action"] in ("update", "reset", "clear", "publish"):
        from onlyalpha.application.integration_application import (
            OnlyUpdateIntegrationDraft,
            _command_document_identity_json,
        )

        kind = {
            "update": OnlyProductCommandKind.UPDATE_INTEGRATION_DRAFT,
            "reset": OnlyProductCommandKind.RESET_INTEGRATION_DRAFT_CONTRACT,
            "clear": OnlyProductCommandKind.CLEAR_INTEGRATION_SECRET,
            "publish": OnlyProductCommandKind.PUBLISH_INTEGRATION_REVISION,
        }[request["action"]]
        payload = {"integration_id": request["integration_id"], "expected_draft_version": request["expected_version"]}
        if request["action"] == "clear":
            payload["field_id"] = request["field_id"]
        if request["action"] == "update":
            command = OnlyUpdateIntegrationDraft(
                OnlyProductCommandId(request["command_id"]),
                OnlyIntegrationId(request["integration_id"]),
                request["expected_version"],
                json.loads(request["public"]),
                None if request["probe"] is None else json.loads(request["probe"]),
            )
            payload.update(
                public_configuration_json=_command_document_identity_json(command.public_configuration),
                probe_configuration_json=_command_document_identity_json(command.probe_configuration),
            )
    elif request["action"] == "set-secret":
        from onlyalpha.application.integration_application import only_integration_secret_commitment

        kind = OnlyProductCommandKind.SET_INTEGRATION_SECRET
        payload = {
            "integration_id": request["integration_id"],
            "expected_draft_version": request["expected_version"],
            "field_id": request["field_id"],
            "secret_commitment": only_integration_secret_commitment(
                b"k" * 32, OnlyIntegrationId(request["integration_id"]), request["field_id"], request["secret"]
            ),
        }
    else:
        kind = OnlyProductCommandKind.SET_INTEGRATION_LIFECYCLE
        payload = {
            "integration_id": request["integration_id"],
            "expected_lifecycle_state": request["expected"],
            "lifecycle_state": request["target"],
        }
    admission = _admission(OnlyProductCommandId(request["command_id"]), kind, payload)
    return {
        "op": "integration-write",
        "action": "replay",
        "command_id": request["command_id"],
        "integration_id": request["integration_id"],
        "kind": kind.value,
        "fingerprint": admission.command_fingerprint,
    }


def lifecycle_request(request: dict[str, Any], expected: str, target: str) -> dict[str, Any]:
    return dict(request, action="lifecycle", command_id=str(uuid4()), expected=expected, target=target)


def edit(
    request: dict[str, Any], *, version: int = 1, public: str = '{"count":7,"ratio":-0.0}', probe: str | None = None
) -> dict[str, Any]:
    return dict(request, action="update", command_id=str(uuid4()), expected_version=version, public=public, probe=probe)


def reset(request: dict[str, Any], version: int) -> dict[str, Any]:
    return dict(request, action="reset", command_id=str(uuid4()), expected_version=version)


def configured(probe: Path, dsn: str, *, extra_secret: bool = False) -> tuple[dict[str, Any], Any]:
    descriptor = _descriptor()
    fields = ["api_key"]
    if extra_secret:
        from dataclasses import replace

        from onlyalpha.plugin.integration import (
            OnlyIntegrationConfigurationContractV1,
            OnlyIntegrationConfigurationFieldV1,
            OnlyIntegrationValueKind,
        )

        descriptor = replace(
            descriptor,
            configuration_contract=OnlyIntegrationConfigurationContractV1(
                fields=descriptor.configuration_contract.fields
                + (
                    OnlyIntegrationConfigurationFieldV1(
                        "api_secret",
                        OnlyIntegrationValueKind.STRING,
                        required=False,
                        secret=True,
                        display_name="Second secret",
                    ),
                )
            ),
        )
        fields.append("api_secret")
    request = create_request()
    request.update(
        type_id=descriptor.type_id.value,
        descriptor=json.dumps(only_integration_json_document(descriptor.to_dict(include_fingerprint=False))),
    )
    assert "error" not in call(probe, request)
    assert "error" not in call(probe, edit(request, public='{"name":"Controlled name"}'))
    # Supply pre-existing encrypted slots; secret authoring is not this fixture
    # user goal. Actual native secret commands have their own tests.
    ident = OnlyIntegrationId(request["integration_id"])
    for version, field in enumerate(fields, start=2):
        secret = "controlled-test-only"
        admission = _admission(
            OnlyProductCommandId(str(uuid4())),
            OnlyProductCommandKind.SET_INTEGRATION_SECRET,
            {
                "integration_id": ident.value,
                "expected_draft_version": version,
                "field_id": field,
                "secret_commitment": only_integration_secret_commitment(MASTER_KEY, ident, field, secret),
            },
        )
        OnlyPostgresIntegrationProductStore(dsn, MASTER_KEY, now=lambda: NOW).set_secret_with_receipt(
            admission, ident, version, descriptor, field, secret
        )
    return request, descriptor


def publish(request: dict[str, Any], version: int = 3) -> dict[str, Any]:
    return dict(request, action="publish", command_id=str(uuid4()), expected_version=version)


def clear(request: dict[str, Any], version: int = 3, field: str = "api_key") -> dict[str, Any]:
    return dict(request, action="clear", command_id=str(uuid4()), expected_version=version, field_id=field)


def owning_facts(dsn: str) -> dict[str, list[tuple[Any, ...]]]:
    with psycopg.connect(dsn) as connection:
        return {
            name: connection.execute(
                f"SELECT row_to_json(t)::text FROM {name} t ORDER BY row_to_json(t)::text"
            ).fetchall()
            for name in _TABLES
        }
