from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from onlyalpha_http_server import create_research_app
from onlyalpha_http_server.app import _install_exact_product_openapi
from onlyalpha_http_server.integrations.routes import (
    create_integration_router,
    integration_error_response,
    integration_request_validation_error_response,
)
from onlyalpha_plugin_binance.spot.broker_factory import OnlyBinanceSpotBrokerFactory

from onlyalpha.application.integration_configuration import (
    OnlyIntegration,
    OnlyIntegrationDraft,
    OnlyIntegrationError,
    OnlyIntegrationId,
    OnlyIntegrationLifecycleState,
    OnlyIntegrationRevision,
)
from onlyalpha.application.integration_type_catalog import OnlyIntegrationTypeCatalog
from onlyalpha.application.product_command_authority import OnlyProductCommandAuthorityError
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.research.operations.readiness import OnlyResearchReadiness, OnlyResearchReadinessStatus

NOW = datetime(2026, 9, 21, tzinfo=UTC)
INTEGRATION_ID = "00000000-0000-4000-8000-000000000101"
COMMAND_ID = "00000000-0000-4000-8000-000000000201"


class _Commands:
    def __init__(self) -> None:
        self.received: list[object] = []

    def _result(self, command: object, *, revision: bool = False) -> object:
        self.received.append(command)
        return SimpleNamespace(
            receipt=SimpleNamespace(
                command_id=command.command_id,
                outcome_ref=SimpleNamespace(
                    kind=SimpleNamespace(value="INTEGRATION_REVISION" if revision else "INTEGRATION"),
                    outcome_id="f" * 64 if revision else INTEGRATION_ID,
                ),
            ),
            replayed=False,
        )

    def create_integration(self, command: object) -> object:
        return self._result(command)

    def update_integration_draft(self, command: object) -> object:
        return self._result(command)

    def set_integration_secret(self, command: object) -> object:
        return self._result(command)

    def clear_integration_secret(self, command: object) -> object:
        return self._result(command)

    def reset_integration_draft_contract(self, command: object) -> object:
        return self._result(command)

    def publish_integration_revision(self, command: object) -> object:
        return self._result(command, revision=True)

    def set_integration_lifecycle(self, command: object) -> object:
        return self._result(command)


class _Queries:
    def __init__(self) -> None:
        descriptor = OnlyBinanceSpotBrokerFactory().integration_type
        integration_id = OnlyIntegrationId(INTEGRATION_ID)
        self.integration = OnlyIntegration(
            integration_id,
            descriptor.type_id.value,
            "Binance Main",
            OnlyIntegrationLifecycleState.ACTIVE,
            None,
            NOW,
            NOW,
        )
        self.draft = OnlyIntegrationDraft.create(
            integration_id=integration_id,
            descriptor=descriptor,
            public_configuration={},
            probe_configuration=None,
            created_at=NOW,
        )
        self.revision = OnlyIntegrationRevision.from_draft(self.draft, 1, "a" * 64, (), NOW)

    def list_integrations(self, **_: object) -> tuple[OnlyIntegration, ...]:
        return (self.integration,)

    def get_integration(self, _integration_id: OnlyIntegrationId) -> OnlyIntegration:
        return self.integration

    def get_draft(self, _integration_id: OnlyIntegrationId) -> OnlyIntegrationDraft:
        return self.draft

    def get_draft_secret_status(self, _integration_id: OnlyIntegrationId) -> tuple[object, ...]:
        return ()

    def list_revision_history(self, _integration_id: OnlyIntegrationId) -> tuple[OnlyIntegrationRevision, ...]:
        return (self.revision,)

    def get_revision(self, _revision_fingerprint: str) -> OnlyIntegrationRevision:
        return self.revision

    def get_revision_secret_status(self, _revision_fingerprint: str) -> tuple[object, ...]:
        return ()


def _client(queries: _Queries | None = None) -> tuple[_Commands, TestClient]:
    commands = _Commands()
    app = FastAPI()
    app.include_router(create_integration_router(commands, queries or _Queries()))  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, integration_request_validation_error_response)
    app.add_exception_handler(OnlyIntegrationError, integration_error_response)
    app.add_exception_handler(OnlyProductCommandAuthorityError, integration_error_response)
    _install_exact_product_openapi(app)
    return commands, TestClient(app)


def test_create_and_read_integration_project_only_application_authority() -> None:
    commands, client = _client()

    created = client.post(
        "/api/v2/integrations",
        headers={"Idempotency-Key": COMMAND_ID},
        json={
            "schema_version": 1,
            "integration_id": INTEGRATION_ID,
            "type_id": "binance.spot.broker",
            "display_name": "Binance Main",
        },
    )

    assert created.status_code == 201, created.text
    assert created.headers["location"] == f"/api/v2/integrations/{INTEGRATION_ID}"
    assert created.json() == {
        "schema_version": 1,
        "command_id": COMMAND_ID,
        "integration_id": INTEGRATION_ID,
        "replayed": False,
        "outcome_kind": "INTEGRATION",
        "outcome_id": INTEGRATION_ID,
    }
    command = commands.received[0]
    assert command.command_id.value == COMMAND_ID  # type: ignore[attr-defined]
    assert command.integration_id.value == INTEGRATION_ID  # type: ignore[attr-defined]

    listed = client.get("/api/v2/integrations")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["category"] == "BROKER"

    draft = client.get(f"/api/v2/integrations/{INTEGRATION_ID}/draft")
    assert draft.status_code == 200
    assert draft.json()["type_descriptor"]["type_id"] == "binance.spot.broker"
    assert draft.json()["secret_statuses"] == []


def test_draft_secret_publish_revision_and_lifecycle_routes_are_thin() -> None:
    commands, client = _client()
    path = f"/api/v2/integrations/{INTEGRATION_ID}"
    headers = {"Idempotency-Key": COMMAND_ID}

    assert (
        client.put(
            f"{path}/draft",
            headers=headers,
            json={
                "schema_version": 1,
                "expected_draft_version": 1,
                "public_configuration": {"recv_window": 5000},
                "probe_configuration": None,
            },
        ).status_code
        == 200
    )
    secret = client.put(
        f"{path}/draft/secrets/api_key",
        headers=headers,
        json={"schema_version": 1, "expected_draft_version": 1, "secret": "NEVER_ECHO_THIS_SECRET"},
    )
    assert secret.status_code == 200
    assert "NEVER_ECHO_THIS_SECRET" not in secret.text
    assert (
        client.delete(
            f"{path}/draft/secrets/api_key",
            headers=headers,
            params={"expected_draft_version": 1},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"{path}/draft/contract-reset",
            headers=headers,
            json={"schema_version": 1, "expected_draft_version": 1},
        ).status_code
        == 200
    )
    published = client.post(
        f"{path}/revisions",
        headers=headers,
        json={"schema_version": 1, "expected_draft_version": 1},
    )
    assert published.status_code == 200
    assert published.headers["location"] == f"{path}/revisions/{'f' * 64}"
    assert (
        client.put(
            f"{path}/lifecycle",
            headers=headers,
            json={
                "schema_version": 1,
                "expected_lifecycle_state": "ACTIVE",
                "lifecycle_state": "DISABLED",
            },
        ).status_code
        == 200
    )

    history = client.get(f"{path}/revisions")
    assert history.status_code == 200
    revision_fingerprint = history.json()["items"][0]["revision_fingerprint"]
    revision = client.get(f"{path}/revisions/{revision_fingerprint}")
    assert revision.status_code == 200
    assert revision.json()["type_descriptor"]["type_id"] == "binance.spot.broker"
    assert revision.json()["secret_bindings"] == []

    received = commands.received
    assert received[0].public_configuration == {"recv_window": 5000}  # type: ignore[attr-defined]
    assert received[1].plaintext_secret == "NEVER_ECHO_THIS_SECRET"  # type: ignore[attr-defined]
    assert received[2].field_id == "api_key"  # type: ignore[attr-defined]
    assert received[-1].lifecycle_state is OnlyIntegrationLifecycleState.DISABLED  # type: ignore[attr-defined]


def test_validation_is_strict_400_and_never_echoes_secret() -> None:
    _, client = _client()
    path = f"/api/v2/integrations/{INTEGRATION_ID}/draft/secrets/api_key"

    missing_key = client.put(
        path,
        json={"schema_version": 1, "expected_draft_version": 1, "secret": "NEVER_ECHO_THIS_SECRET"},
    )
    assert missing_key.status_code == 400
    assert missing_key.json()["error"]["code"] == "INTEGRATION_REQUEST_INVALID"
    assert "NEVER_ECHO_THIS_SECRET" not in missing_key.text

    wrong_type = client.put(
        path,
        headers={"Idempotency-Key": COMMAND_ID},
        json={
            "schema_version": 1,
            "expected_draft_version": "1",
            "secret": "NEVER_ECHO_THIS_SECRET",
            "unknown": True,
        },
    )
    assert wrong_type.status_code == 400
    assert wrong_type.json()["error"]["code"] == "INTEGRATION_REQUEST_INVALID"
    assert "NEVER_ECHO_THIS_SECRET" not in wrong_type.text

    openapi = client.get("/openapi.json").json()
    route = path.replace(INTEGRATION_ID, "{integration_id}").replace("api_key", "{field_id}")
    operation = openapi["paths"][route]["put"]
    assert "422" not in operation["responses"]
    secret_schema = openapi["components"]["schemas"]["IntegrationSecretSetRequestDto"]["properties"]["secret"]
    assert secret_schema["writeOnly"] is True
    assert "default" not in secret_schema and "example" not in secret_schema


@pytest.mark.parametrize(
    ("code", "status", "detail"),
    (
        ("INTEGRATION_NOT_FOUND", 404, "Integration resource not found"),
        ("INTEGRATION_REVISION_CORRUPT", 500, "Verified Integration Product authority is corrupt"),
        ("INTEGRATION_PERSISTENCE_CONFLICT", 503, "Required Integration Product authority is unavailable"),
    ),
)
def test_integration_errors_are_stable_and_sanitized(code: str, status: int, detail: str) -> None:
    class FailingQueries(_Queries):
        def get_integration(self, _integration_id: OnlyIntegrationId) -> OnlyIntegration:
            raise OnlyIntegrationError(code, "psycopg constraint SECRET_INTERNAL")

    _, client = _client(FailingQueries())
    response = client.get(f"/api/v2/integrations/{INTEGRATION_ID}")

    assert response.status_code == status
    assert response.json() == {"schema_version": 1, "error": {"code": code, "detail": detail}}
    assert "psycopg" not in response.text and "SECRET_INTERNAL" not in response.text


def test_corrupt_persisted_descriptor_uses_sanitized_integration_error() -> None:
    queries = _Queries()
    object.__setattr__(queries.draft, "type_descriptor_document", {"schema_version": 1})
    _, client = _client(queries)

    response = client.get(f"/api/v2/integrations/{INTEGRATION_ID}/draft")

    assert response.status_code == 500
    assert response.json() == {
        "schema_version": 1,
        "error": {
            "code": "INTEGRATION_REVISION_CORRUPT",
            "detail": "Verified Integration Product authority is corrupt",
        },
    }


def test_integration_control_plane_is_independent_of_research_readiness() -> None:
    class Definitions:
        universe_resolver = None

    class NotReady:
        def inspect(self) -> OnlyResearchReadiness:
            return OnlyResearchReadiness(OnlyResearchReadinessStatus.NOT_READY, (), "NO_WORKER")

    app = create_research_app(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        OnlyCalculationRegistry(),
        Definitions(),  # type: ignore[arg-type]
        NotReady(),  # type: ignore[arg-type]
        integration_types=OnlyIntegrationTypeCatalog(OnlyDataSourceFactoryRegistry(), OnlyBrokerFactoryRegistry()),
        integration_commands=_Commands(),  # type: ignore[arg-type]
        integration_queries=_Queries(),  # type: ignore[arg-type]
    )
    client = TestClient(app)

    assert client.get("/api/v2/integrations").status_code == 200
    assert client.get("/api/v2/research/runs").status_code == 503
    invalid = client.post(
        "/api/v2/integrations",
        headers={"Idempotency-Key": "not-a-uuid"},
        json={
            "schema_version": 1,
            "integration_id": INTEGRATION_ID,
            "type_id": "binance.spot.broker",
            "display_name": "Binance Main",
        },
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INTEGRATION_REQUEST_INVALID"


def test_integration_control_plane_rejects_partial_authority_wiring() -> None:
    definitions = SimpleNamespace(universe_resolver=None)

    with pytest.raises(TypeError, match="Type, Command, and Query authorities"):
        create_research_app(
            SimpleNamespace(),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            OnlyCalculationRegistry(),
            definitions,  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            integration_types=OnlyIntegrationTypeCatalog(OnlyDataSourceFactoryRegistry(), OnlyBrokerFactoryRegistry()),
        )
