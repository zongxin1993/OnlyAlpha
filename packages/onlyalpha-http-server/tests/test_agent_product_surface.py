from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from onlyalpha_http_server.research.catalog_context_routes import create_exact_catalog_context_router
from onlyalpha_http_server.research.catalog_context_schema import (
    LEGACY_EXACT_CATALOG_CONTEXT_PROJECTION_SCHEMA_FINGERPRINT,
)
from onlyalpha_http_server.search.routes import create_search_router
from onlyalpha_http_server.search.schema import (
    SearchCommandResponseDto,
    SearchExperimentResponseDto,
    SearchLedgerResponseDto,
    SearchTerminalResponseDto,
)
from pydantic import ValidationError

SHA = "a" * 64
COMMAND = "00000000-0000-4000-8000-000000000001"


class _CatalogProjection:
    catalog_generation_fingerprint = SHA
    ordered_providers: tuple[object, ...] = ()
    ordered_calculation_capabilities: tuple[object, ...] = ()
    ordered_registered_universes: tuple[object, ...] = ()
    ordered_dataset_field_contracts: tuple[object, ...] = ()
    ordered_statistics_capabilities: tuple[object, ...] = ()
    projection_schema_fingerprint = "b" * 64
    projection_fingerprint = "c" * 64

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "ordered_providers": [],
            "ordered_calculation_capabilities": [],
            "ordered_registered_universes": [],
            "ordered_dataset_field_contracts": [],
            "ordered_statistics_capabilities": [],
            "projection_schema_fingerprint": self.projection_schema_fingerprint,
            "projection_fingerprint": self.projection_fingerprint,
        }


class _Catalog:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def get_exact_catalog_context(self, fingerprint: str) -> _CatalogProjection:
        self.requested.append(fingerprint)
        if fingerprint != SHA:
            raise LookupError(fingerprint)
        return _CatalogProjection()


class _Search:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    @staticmethod
    def _command(command: str) -> SearchCommandResponseDto:
        return SearchCommandResponseDto(
            product_command_id=command,
            experiment_fingerprint=SHA,
            method="SYMBOLIC",
            receipt={},
            ledger={},
            terminal={},
            replayed=False,
        )

    def submit_symbolic(self, command: str, _request) -> SearchCommandResponseDto:  # type: ignore[no-untyped-def]
        self.calls.append(("submit-symbolic", command))
        return self._command(command)

    def submit_parameter(self, command: str, _request) -> SearchCommandResponseDto:  # type: ignore[no-untyped-def]
        self.calls.append(("submit-parameter", command))
        return self._command(command)

    def advance_symbolic(self, command: str, _request) -> SearchCommandResponseDto:  # type: ignore[no-untyped-def]
        self.calls.append(("advance-symbolic", command))
        return self._command(command)

    def advance_parameter(self, command: str, _request) -> SearchCommandResponseDto:  # type: ignore[no-untyped-def]
        self.calls.append(("advance-parameter", command))
        return self._command(command)

    def get_experiment(self, fingerprint: str) -> SearchExperimentResponseDto:
        self.calls.append(("experiment", fingerprint))
        return SearchExperimentResponseDto(experiment_fingerprint=fingerprint, method="SYMBOLIC", experiment={})

    def get_ledger(self, fingerprint: str) -> SearchLedgerResponseDto:
        self.calls.append(("ledger", fingerprint))
        return SearchLedgerResponseDto(experiment_fingerprint=fingerprint, method="SYMBOLIC", ledger={})

    def get_terminal(self, fingerprint: str) -> SearchTerminalResponseDto:
        self.calls.append(("terminal", fingerprint))
        return SearchTerminalResponseDto(
            experiment_fingerprint=fingerprint,
            method="SYMBOLIC",
            terminal_kind="NON_TERMINAL",
            terminal_fact=None,
            stop_reason=None,
        )


def _client(catalog: _Catalog, search: _Search) -> TestClient:
    app = FastAPI()
    app.include_router(create_exact_catalog_context_router(catalog))  # type: ignore[arg-type]
    app.include_router(create_search_router(search))  # type: ignore[arg-type]
    return TestClient(app)


def test_exact_catalog_surface_has_no_latest_current_or_fallback_semantics() -> None:
    catalog = _Catalog()
    client = _client(catalog, _Search())
    response = client.get(f"/api/v2/research/catalog-context/{SHA}")
    assert response.status_code == 200
    assert response.json()["catalog_generation_fingerprint"] == SHA
    assert (
        response.json()["projection_schema_fingerprint"] == LEGACY_EXACT_CATALOG_CONTEXT_PROJECTION_SCHEMA_FINGERPRINT
    )
    assert catalog.requested == [SHA]
    complete = client.get(f"/api/v2/research/catalog-context/exact/{SHA}")
    assert complete.status_code == 200
    assert complete.json()["projection_schema_fingerprint"] != response.json()["projection_schema_fingerprint"]
    assert set(complete.json()) >= {
        "ordered_registered_universes",
        "ordered_dataset_field_contracts",
        "ordered_statistics_capabilities",
    }
    for alias in ("latest", "current", "fallback"):
        assert client.get(f"/api/v2/research/catalog-context/{alias}").status_code == 422
    assert catalog.requested == [SHA, SHA]


def test_exact_catalog_readiness_route_is_additive_and_not_an_agent_operation() -> None:
    client = _client(_Catalog(), _Search())
    paths = client.get("/openapi.json").json()["paths"]
    route = paths["/api/v2/research/catalog-context/exact/{catalog_generation_fingerprint}/readiness"]["get"]
    assert route["operationId"] == "get_exact_catalog_readiness_v2"
    assert "x-onlyalpha-agent-operation" not in route
    assert paths["/api/v2/research/catalog-context/{catalog_generation_fingerprint}"]["get"]["operationId"] == (
        "get_exact_catalog_context_v2"
    )
    complete = paths["/api/v2/research/catalog-context/exact/{catalog_generation_fingerprint}"]["get"]
    assert complete["operationId"] == "get_complete_exact_catalog_context_v2"
    assert complete["x-onlyalpha-agent-operation"]["tool_class"] == "EXACT_CATALOG_CONTEXT_QUERY"


def test_exact_catalog_legacy_schema_and_response_fields_remain_frozen() -> None:
    assert LEGACY_EXACT_CATALOG_CONTEXT_PROJECTION_SCHEMA_FINGERPRINT == (
        "169a7c181f87fdd4293165866d8eede19f1f54db12dec44c78d19c922c800a24"
    )
    client = _client(_Catalog(), _Search())
    legacy = client.get(f"/api/v2/research/catalog-context/{SHA}").json()
    assert set(legacy) == {
        "schema_version",
        "catalog_generation_fingerprint",
        "ordered_providers",
        "ordered_calculation_capabilities",
        "projection_schema_fingerprint",
        "projection_fingerprint",
    }
    complete = client.get(f"/api/v2/research/catalog-context/exact/{SHA}").json()
    assert set(complete) == set(legacy) | {
        "ordered_registered_universes",
        "ordered_dataset_field_contracts",
        "ordered_statistics_capabilities",
    }
    assert complete == _CatalogProjection().to_dict()


def test_exact_catalog_readiness_http_projection_is_strict_and_generation_bound() -> None:
    from onlyalpha_http_server.research.catalog_context_schema import ExactCatalogReadinessProjectionResponseDto
    from onlyalpha_plugin_indicators.provider import quant_asset_provider

    from onlyalpha.application.catalog_context import (
        OnlyExactCatalogCalculationReadinessCapabilityV1,
        only_project_exact_catalog_context,
        only_project_exact_catalog_readiness,
    )
    from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration

    provider = quant_asset_provider()
    generation = OnlyQuantAssetCatalogGeneration((provider,))
    context = only_project_exact_catalog_context(
        generation.generation_fingerprint,
        generation.descriptor(),
        dataset_field_contracts=(),
        registered_universes=(),
        statistics_capabilities=(),
    )
    registrations = {
        (item.type_definition.type_id, item.type_definition.semantic_version, item.backend): item
        for item in provider.calculation_registrations
    }
    rows = tuple(
        OnlyExactCatalogCalculationReadinessCapabilityV1(
            generation.generation_fingerprint,
            item.provider_id,
            item.provider_version,
            item.provider_kind,
            item.kind,
            item.type_id,
            item.semantic_version,
            item.backend,
            item.implementation_fingerprint,
            registrations[item.type_id, item.semantic_version, item.backend].readiness_contract_versions,
        )
        for item in context.ordered_calculation_capabilities
    )
    projection = only_project_exact_catalog_readiness(context, rows)

    class Catalog(_Catalog):
        def get_exact_catalog_readiness(self, fingerprint: str):  # type: ignore[no-untyped-def]
            assert fingerprint == projection.catalog_generation_fingerprint
            self.requested.append(fingerprint)
            return projection

    catalog = Catalog()
    client = _client(catalog, _Search())
    response = client.get(f"/api/v2/research/catalog-context/exact/{generation.generation_fingerprint}/readiness")
    assert response.status_code == 200
    assert response.json() == projection.to_dict()
    assert catalog.requested == [generation.generation_fingerprint]
    assert [
        (item.type_id, item.backend.value, item.readiness_contract_versions)
        for item in rows
        if item.readiness_contract_versions
    ] == [("onlyalpha.indicator.sma", "RESEARCH", (1,))]
    for key, value in (("unknown", True), ("schema_version", True), ("projection_fingerprint", "f" * 64)):
        payload = projection.to_dict()
        payload[key] = value
        with pytest.raises(ValidationError):
            ExactCatalogReadinessProjectionResponseDto.model_validate_json(json.dumps(payload))


def test_search_query_is_exact_and_commands_echo_the_same_product_command_id() -> None:
    search = _Search()
    client = _client(_Catalog(), search)
    query = client.get(f"/api/v2/research/search/experiments/{SHA}")
    assert query.status_code == 200
    assert query.json()["experiment_fingerprint"] == SHA

    request = {
        "schema_version": 1,
        "method": "SYMBOLIC",
        "operation": "ADVANCE_ONE_SYMBOLIC_OCCURRENCE",
        "experiment_fingerprint": SHA,
        "expected_state": {},
    }
    command = client.post(
        "/api/v2/research/search/symbolic-experiments/advance",
        headers={"Idempotency-Key": COMMAND},
        json=request,
    )
    assert command.status_code == 202
    assert command.headers["Idempotency-Key"] == COMMAND
    assert command.json()["product_command_id"] == COMMAND
    assert search.calls == [("experiment", SHA), ("advance-symbolic", COMMAND)]


def test_search_command_without_product_command_identity_is_rejected_before_service() -> None:
    search = _Search()
    client = _client(_Catalog(), search)
    response = client.post(
        "/api/v2/research/search/symbolic-experiments/advance",
        json={
            "schema_version": 1,
            "method": "SYMBOLIC",
            "operation": "ADVANCE_ONE_SYMBOLIC_OCCURRENCE",
            "experiment_fingerprint": SHA,
            "expected_state": {},
        },
    )
    assert response.status_code == 422
    assert search.calls == []
