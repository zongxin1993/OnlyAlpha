from __future__ import annotations

import os

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from onlyalpha_http_server.app import _install_exact_product_openapi
from onlyalpha_http_server.integration_types.routes import create_integration_type_router
from onlyalpha_http_server.integrations.routes import (
    create_integration_router,
    integration_error_response,
    integration_request_validation_error_response,
)

from onlyalpha.application.integration_application import (
    OnlyIntegrationCommandService,
    OnlyIntegrationQueryService,
)
from onlyalpha.application.integration_type_catalog import OnlyIntegrationTypeCatalogError
from onlyalpha.persistence.postgres import (
    MASTER_KEY_BYTES,
    OnlyPostgresIntegrationProductStore,
    only_assert_postgres_test_database,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from onlyalpha.plugin.integration import (
    OnlyIntegrationCategory,
    OnlyIntegrationConfigurationContractV1,
    OnlyIntegrationConfigurationFieldV1,
    OnlyIntegrationTypeDescriptorV1,
    OnlyIntegrationTypeId,
    OnlyIntegrationValueKind,
)

pytestmark = pytest.mark.postgres
INTEGRATION_ID = "00000000-0000-4000-8000-000000000301"
SECRET = "NEVER_ECHO_THIS_SECRET"


class _Catalog:
    def __init__(self, descriptor: OnlyIntegrationTypeDescriptorV1) -> None:
        self.descriptor: OnlyIntegrationTypeDescriptorV1 | None = descriptor

    def list(self, category: OnlyIntegrationCategory | None = None) -> tuple[OnlyIntegrationTypeDescriptorV1, ...]:
        if self.descriptor is None or (category is not None and self.descriptor.category is not category):
            return ()
        return (self.descriptor,)

    def require(self, type_id: str) -> OnlyIntegrationTypeDescriptorV1:
        if self.descriptor is None or self.descriptor.type_id.value != type_id:
            raise OnlyIntegrationTypeCatalogError("INTEGRATION_TYPE_NOT_FOUND", "Integration Type is not available")
        return self.descriptor


def _descriptor() -> OnlyIntegrationTypeDescriptorV1:
    return OnlyIntegrationTypeDescriptorV1(
        type_id=OnlyIntegrationTypeId("test.local.market_data"),
        category=OnlyIntegrationCategory.DATA_SOURCE,
        display_name="Local Test Data",
        description="Deterministic local HTTP acceptance descriptor.",
        provider_id="test",
        implementation_id="test.local",
        implementation_version="1.0.0",
        public_api_version="1.1",
        capabilities=("HISTORICAL_BARS",),
        configuration_contract=OnlyIntegrationConfigurationContractV1(
            fields=(
                OnlyIntegrationConfigurationFieldV1(
                    "endpoint",
                    OnlyIntegrationValueKind.STRING,
                    required=True,
                    display_name="Endpoint",
                ),
                OnlyIntegrationConfigurationFieldV1(
                    "api_key",
                    OnlyIntegrationValueKind.STRING,
                    required=True,
                    secret=True,
                    display_name="API key",
                ),
            )
        ),
        probe_contract=None,
    )


@pytest.fixture
def postgres_dsn() -> str:
    dsn = os.environ.get("ONLYALPHA_POSTGRES_DSN")
    if not dsn:
        pytest.fail("ONLYALPHA_POSTGRES_DSN is required for the canonical Compose PostgreSQL lane")
    only_assert_postgres_test_database(dsn)
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    OnlyPostgresMigrationAuthority(dsn).migrate()
    return dsn


def _client(postgres_dsn: str) -> tuple[_Catalog, TestClient]:
    catalog = _Catalog(_descriptor())
    store = OnlyPostgresIntegrationProductStore(postgres_dsn, b"k" * MASTER_KEY_BYTES)
    app = FastAPI()
    app.include_router(create_integration_type_router(catalog))  # type: ignore[arg-type]
    app.include_router(
        create_integration_router(
            OnlyIntegrationCommandService(catalog, store, b"k" * MASTER_KEY_BYTES),  # type: ignore[arg-type]
            OnlyIntegrationQueryService(store),
        )
    )
    app.add_exception_handler(RequestValidationError, integration_request_validation_error_response)
    from onlyalpha.application.integration_configuration import OnlyIntegrationError
    from onlyalpha.application.product_command_authority import OnlyProductCommandAuthorityError

    app.add_exception_handler(OnlyIntegrationError, integration_error_response)
    app.add_exception_handler(OnlyProductCommandAuthorityError, integration_error_response)
    _install_exact_product_openapi(app)
    return catalog, TestClient(app)


def _key(sequence: int) -> dict[str, str]:
    return {"Idempotency-Key": f"00000000-0000-4000-8000-{sequence:012d}"}


def test_real_postgres_http_integration_golden_flow(postgres_dsn: str) -> None:
    catalog, client = _client(postgres_dsn)
    base = f"/api/v2/integrations/{INTEGRATION_ID}"
    responses = []

    assert client.get("/api/v2/integration-types").json()["items"][0]["type_id"] == "test.local.market_data"
    create_body = {
        "schema_version": 1,
        "integration_id": INTEGRATION_ID,
        "type_id": "test.local.market_data",
        "display_name": "Local Main",
    }
    created = client.post("/api/v2/integrations", headers=_key(1), json=create_body)
    responses.append(created)
    assert created.status_code == 201
    assert client.post("/api/v2/integrations", headers=_key(1), json=create_body).json()["replayed"] is True
    conflict = client.post("/api/v2/integrations", headers=_key(1), json={**create_body, "display_name": "Different"})
    assert (conflict.status_code, conflict.json()["error"]["code"]) == (409, "PRODUCT_COMMAND_CONFLICT")

    assert client.get(base).status_code == 200
    assert client.get(f"{base}/draft").json()["draft_version"] == 1
    update_body = {
        "schema_version": 1,
        "expected_draft_version": 1,
        "public_configuration": {"endpoint": "local"},
        "probe_configuration": None,
    }
    updated = client.put(f"{base}/draft", headers=_key(2), json=update_body)
    responses.append(updated)
    assert updated.status_code == 200
    assert client.put(f"{base}/draft", headers=_key(2), json=update_body).json()["replayed"] is True
    update_conflict = client.put(
        f"{base}/draft",
        headers=_key(2),
        json={**update_body, "public_configuration": {"endpoint": "different"}},
    )
    assert (update_conflict.status_code, update_conflict.json()["error"]["code"]) == (
        409,
        "PRODUCT_COMMAND_CONFLICT",
    )
    stale = client.put(f"{base}/draft", headers=_key(3), json=update_body)
    assert (stale.status_code, stale.json()["error"]["code"]) == (409, "INTEGRATION_DRAFT_VERSION_CONFLICT")

    secret_body = {"schema_version": 1, "expected_draft_version": 2, "secret": SECRET}
    secret = client.put(f"{base}/draft/secrets/api_key", headers=_key(4), json=secret_body)
    responses.append(secret)
    assert secret.status_code == 200
    assert client.put(f"{base}/draft/secrets/api_key", headers=_key(4), json=secret_body).json()["replayed"] is True
    secret_conflict = client.put(
        f"{base}/draft/secrets/api_key",
        headers=_key(4),
        json={**secret_body, "secret": "different-secret"},
    )
    assert (secret_conflict.status_code, secret_conflict.json()["error"]["code"]) == (
        409,
        "PRODUCT_COMMAND_CONFLICT",
    )

    clear_url = f"{base}/draft/secrets/api_key"
    cleared = client.delete(clear_url, headers=_key(5), params={"expected_draft_version": 3})
    assert cleared.status_code == 200
    assert client.delete(clear_url, headers=_key(5), params={"expected_draft_version": 3}).json()["replayed"] is True
    clear_conflict = client.delete(f"{base}/draft/secrets/other", headers=_key(5), params={"expected_draft_version": 3})
    assert (clear_conflict.status_code, clear_conflict.json()["error"]["code"]) == (
        409,
        "PRODUCT_COMMAND_CONFLICT",
    )

    reset_body = {"schema_version": 1, "expected_draft_version": 4}
    reset = client.post(f"{base}/draft/contract-reset", headers=_key(6), json=reset_body)
    assert reset.status_code == 200
    assert client.post(f"{base}/draft/contract-reset", headers=_key(6), json=reset_body).json()["replayed"] is True
    reset_conflict = client.post(
        f"{base}/draft/contract-reset",
        headers=_key(6),
        json={**reset_body, "expected_draft_version": 5},
    )
    assert (reset_conflict.status_code, reset_conflict.json()["error"]["code"]) == (
        409,
        "PRODUCT_COMMAND_CONFLICT",
    )

    restored_update = {**update_body, "expected_draft_version": 5}
    assert client.put(f"{base}/draft", headers=_key(7), json=restored_update).status_code == 200
    restored_secret = {**secret_body, "expected_draft_version": 6}
    assert client.put(f"{base}/draft/secrets/api_key", headers=_key(8), json=restored_secret).status_code == 200

    publish_body = {"schema_version": 1, "expected_draft_version": 7}
    published = client.post(f"{base}/revisions", headers=_key(9), json=publish_body)
    responses.append(published)
    assert published.status_code == 200
    revision = published.json()["outcome_id"]
    assert client.post(f"{base}/revisions", headers=_key(9), json=publish_body).json()["replayed"] is True
    publish_conflict = client.post(
        f"{base}/revisions",
        headers=_key(9),
        json={**publish_body, "expected_draft_version": 8},
    )
    assert (publish_conflict.status_code, publish_conflict.json()["error"]["code"]) == (
        409,
        "PRODUCT_COMMAND_CONFLICT",
    )

    assert client.get(base).json()["current_revision_fingerprint"] == revision
    assert client.get(f"{base}/revisions").json()["items"][0]["revision_fingerprint"] == revision
    exact = client.get(f"{base}/revisions/{revision}")
    responses.append(exact)
    assert exact.status_code == 200
    assert exact.json()["secret_bindings"] == [{"field_id": "api_key", "configured": True, "generation": 2}]

    lifecycle_body = {
        "schema_version": 1,
        "expected_lifecycle_state": "ACTIVE",
        "lifecycle_state": "DISABLED",
    }
    lifecycle = client.put(f"{base}/lifecycle", headers=_key(10), json=lifecycle_body)
    responses.append(lifecycle)
    assert lifecycle.status_code == 200
    assert client.put(f"{base}/lifecycle", headers=_key(10), json=lifecycle_body).json()["replayed"] is True
    lifecycle_conflict = client.put(
        f"{base}/lifecycle",
        headers=_key(10),
        json={**lifecycle_body, "lifecycle_state": "ARCHIVED"},
    )
    assert (lifecycle_conflict.status_code, lifecycle_conflict.json()["error"]["code"]) == (
        409,
        "PRODUCT_COMMAND_CONFLICT",
    )

    catalog.descriptor = None
    assert client.get("/api/v2/integrations").status_code == 200
    assert client.get(base).status_code == 200
    assert client.get(f"{base}/draft").status_code == 200
    assert client.get(f"{base}/revisions/{revision}").status_code == 200
    unavailable = client.put(
        f"{base}/draft",
        headers=_key(11),
        json={**update_body, "expected_draft_version": 8},
    )
    assert (unavailable.status_code, unavailable.json()["error"]["code"]) == (
        409,
        "INTEGRATION_TYPE_UNAVAILABLE",
    )

    foreign = client.get(f"/api/v2/integrations/00000000-0000-4000-8000-000000000399/revisions/{revision}")
    assert (foreign.status_code, foreign.json()["error"]["code"]) == (
        404,
        "INTEGRATION_REVISION_NOT_FOUND",
    )

    archived = client.put(
        f"{base}/lifecycle",
        headers=_key(12),
        json={
            "schema_version": 1,
            "expected_lifecycle_state": "DISABLED",
            "lifecycle_state": "ARCHIVED",
        },
    )
    assert archived.status_code == 200
    assert client.get(base).status_code == 200
    assert client.get(f"{base}/draft").status_code == 200
    assert client.get(f"{base}/revisions").status_code == 200
    assert client.get(f"{base}/revisions/{revision}").status_code == 200
    archived_mutations = (
        client.put(
            f"{base}/draft",
            headers=_key(13),
            json={**update_body, "expected_draft_version": 8},
        ),
        client.put(
            f"{base}/draft/secrets/api_key",
            headers=_key(14),
            json={**secret_body, "expected_draft_version": 8},
        ),
        client.delete(
            f"{base}/draft/secrets/api_key",
            headers=_key(15),
            params={"expected_draft_version": 8},
        ),
        client.post(
            f"{base}/draft/contract-reset",
            headers=_key(16),
            json={"schema_version": 1, "expected_draft_version": 8},
        ),
        client.post(
            f"{base}/revisions",
            headers=_key(17),
            json={"schema_version": 1, "expected_draft_version": 8},
        ),
    )
    assert {(item.status_code, item.json()["error"]["code"]) for item in archived_mutations} == {
        (409, "INTEGRATION_ARCHIVED")
    }

    assert all(SECRET not in response.text for response in responses)
    with psycopg.connect(postgres_dsn) as connection:
        product_facts = connection.execute(
            "SELECT row_to_json(a)::text, row_to_json(r)::text "
            "FROM product_command_admission a JOIN product_command_receipt r USING (command_id)"
        ).fetchall()
        ciphertexts = connection.execute("SELECT encode(ciphertext, 'hex') FROM product_credential").fetchall()
    assert SECRET not in repr(product_facts)
    assert SECRET.encode().hex() not in repr(ciphertexts)
