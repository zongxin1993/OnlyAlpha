from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from onlyalpha_http_server.research.catalog_context_routes import create_exact_catalog_context_router
from onlyalpha_http_server.search.routes import create_search_router
from onlyalpha_http_server.search.schema import (
    SearchCommandResponseDto,
    SearchExperimentResponseDto,
    SearchLedgerResponseDto,
    SearchTerminalResponseDto,
)

SHA = "a" * 64
COMMAND = "00000000-0000-4000-8000-000000000001"


class _CatalogProjection:
    catalog_generation_fingerprint = SHA
    ordered_providers: tuple[object, ...] = ()
    ordered_calculation_capabilities: tuple[object, ...] = ()
    projection_schema_fingerprint = "b" * 64
    projection_fingerprint = "c" * 64

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "ordered_providers": [],
            "ordered_calculation_capabilities": [],
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
    assert catalog.requested == [SHA]
    for alias in ("latest", "current", "fallback"):
        assert client.get(f"/api/v2/research/catalog-context/{alias}").status_code == 422
    assert catalog.requested == [SHA]


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
