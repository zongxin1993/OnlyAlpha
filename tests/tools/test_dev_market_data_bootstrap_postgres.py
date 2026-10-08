"""Durable dev seed recovery through real Product HTTP routes and PostgreSQL."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from onlyalpha_http_server.integrations.routes import create_integration_router
from onlyalpha_http_server.market_data import create_market_data_router
from onlyalpha_plugin_binance.spot.data_source.factory import OnlyBinanceSpotDataSourceFactory

from onlyalpha.application.integration_application import OnlyIntegrationCommandService, OnlyIntegrationQueryService
from onlyalpha.application.integration_runtime import OnlyIntegrationRuntimeResolver
from onlyalpha.application.integration_type_catalog import OnlyIntegrationTypeCatalog
from onlyalpha.application.market_data_product import OnlyMarketDataProductService
from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.market_data.durable import OnlyInMemoryMarketDataCatalog, OnlyInMemoryMarketFactStore
from onlyalpha.persistence.postgres import (
    OnlyPostgresCredentialAuthority,
    OnlyPostgresIntegrationProductStore,
    only_assert_postgres_test_database,
)
from onlyalpha.persistence.postgres.migration import OnlyPostgresMigrationAuthority
from scripts.product_acceptance_client import ProductHttpClient
from scripts.provision_dev_market_data import CREATE_COMMAND_ID, INTEGRATION_ID, TYPE_ID, provision

pytestmark = pytest.mark.postgres


class _HttpClient(ProductHttpClient):
    def __init__(self, http: TestClient, lost_response_path: str | None) -> None:
        super().__init__("http://testserver")
        self.http = http
        self.lost_response_path = lost_response_path
        self.command_responses: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
        expected_status: int = 200,
    ) -> dict[str, Any]:
        response = self.http.request(
            method,
            path,
            json=payload,
            headers={} if idempotency_key is None else {"Idempotency-Key": idempotency_key},
        )
        assert response.status_code == expected_status, response.text
        document: dict[str, Any] = response.json()
        if method == "POST":
            self.command_responses.append(document)
        if method == "POST" and path == self.lost_response_path:
            self.lost_response_path = None
            raise ConnectionError("response lost after HTTP command commit")
        return document


@pytest.mark.parametrize(
    "lost_response_path",
    [
        None,
        "/api/v2/integrations",
        f"/api/v2/integrations/{INTEGRATION_ID}/revisions",
    ],
)
def test_dev_seed_recovery_uses_durable_receipts_and_preserves_disabled_source(
    tmp_path: Path,
    lost_response_path: str | None,
) -> None:
    dsn = os.environ["ONLYALPHA_POSTGRES_DSN"]
    only_assert_postgres_test_database(dsn)
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    OnlyPostgresMigrationAuthority(dsn).migrate()
    master_key = b"k" * 32
    store = OnlyPostgresIntegrationProductStore(dsn, master_key)
    sources = OnlyDataSourceFactoryRegistry()
    sources.register(OnlyBinanceSpotDataSourceFactory())
    catalog = OnlyIntegrationTypeCatalog(sources, OnlyBrokerFactoryRegistry())
    queries = OnlyIntegrationQueryService(store)
    # Only source eligibility is queried: there are deliberately no durable Bar stores
    # or provider connections. Configuration publication must not manufacture data.
    product = OnlyMarketDataProductService(
        resolver=OnlyIntegrationRuntimeResolver(store, OnlyPostgresCredentialAuthority(dsn, master_key), catalog),
        integrations=queries,
        data_sources=sources,
        catalog=OnlyInMemoryMarketDataCatalog(),
        fact_store=OnlyInMemoryMarketFactStore(),
        wal_root=tmp_path,
        clock=OnlyBacktestClock(datetime(2026, 1, 1, tzinfo=UTC)),
        logger=logging.getLogger(__name__),
    )
    app = FastAPI()
    app.include_router(create_integration_router(OnlyIntegrationCommandService(catalog, store, master_key), queries))
    app.include_router(create_market_data_router(product))
    with TestClient(app) as http:
        client = _HttpClient(http, lost_response_path)
        if lost_response_path is not None:
            with pytest.raises(ConnectionError, match="command commit"):
                provision(client)
        outcome = provision(client)
        assert outcome["provisioning"] in {"PUBLISHED", "EXISTING_SOURCE"}
        integration = http.get(f"/api/v2/integrations/{INTEGRATION_ID}").json()
        revision = integration["current_revision_fingerprint"]
        assert integration["type_id"] == TYPE_ID
        assert len(http.get(f"/api/v2/integrations/{INTEGRATION_ID}/revisions").json()["items"]) == 1
        selection = http.get("/api/v2/market-data/sources").json()["sources"]
        assert len(selection) == 1
        assert selection[0]["integration_id"] == INTEGRATION_ID
        assert selection[0]["integration_revision_fingerprint"] == revision
        assert selection[0]["environment"] == "GLOBAL"
        exact = http.get(f"/api/v2/integrations/{INTEGRATION_ID}/revisions/{revision}").json()
        assert exact["configuration"] == {
            field.field_id: field.default
            for field in OnlyBinanceSpotDataSourceFactory().integration_type.configuration_contract.fields
            if field.default is not None
        }
        assert exact["configuration"]["environment"] == "GLOBAL"
        assert exact["configuration"]["endpoint_profile"] == "PUBLIC_MARKET_DATA"
        assert exact["secret_bindings"] == []
        if lost_response_path == "/api/v2/integrations":
            assert any(
                item["command_id"] == CREATE_COMMAND_ID and item["replayed"] for item in client.command_responses
            )
        commands_before = len(client.command_responses)
        assert provision(client) == {"provisioning": "EXISTING_SOURCE", "source_count": 1}
        assert len(client.command_responses) == commands_before
        disabled = http.put(
            f"/api/v2/integrations/{INTEGRATION_ID}/lifecycle",
            headers={"Idempotency-Key": "00000000-0000-4000-8000-000000000901"},
            json={"schema_version": 1, "expected_lifecycle_state": "ACTIVE", "lifecycle_state": "DISABLED"},
        )
        assert disabled.status_code == 200, disabled.text
        assert provision(client) == {"provisioning": "PRESERVED", "integration_id": INTEGRATION_ID}
        assert len(client.command_responses) == commands_before
        assert http.get("/api/v2/market-data/sources").json()["sources"] == []
