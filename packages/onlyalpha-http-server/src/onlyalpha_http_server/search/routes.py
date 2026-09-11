"""Thin Search Product HTTP routes over one typed application boundary."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Path, Response

from .schema import (
    OnlySearchProductHttpBoundary,
    ParameterSearchSubmitRequestDto,
    SearchAdvanceRequestDto,
    SearchCommandResponseDto,
    SearchErrorEnvelopeDto,
    SearchExperimentResponseDto,
    SearchLedgerResponseDto,
    SearchTerminalResponseDto,
    SymbolicSearchSubmitRequestDto,
)

SEARCH_ROUTE_TAG = "search-product"
_ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": SearchErrorEnvelopeDto} for status in (400, 404, 409, 500, 503)
}
_COMMAND_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_ERRORS,
    202: {
        "headers": {
            "Idempotency-Key": {
                "description": "Exact admitted Product Command identity",
                "schema": {"type": "string"},
            }
        }
    },
}
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key")]
SearchExperimentPath = Annotated[
    str,
    Path(
        pattern=r"^[0-9a-f]{64}$",
        json_schema_extra={
            "x-onlyalpha-reference-kind": "SEARCH_EXPERIMENT",
            "x-onlyalpha-reference-schema-version": 1,
            "x-onlyalpha-reference-locator-kind": "SHA256",
        },
    ),
]


def _operation(
    tool_class: str,
    recovery_class: str,
    *,
    command: bool,
    identities: list[str],
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "schema_version": 1,
        "tool_class": tool_class,
        "recovery_class": recovery_class,
        "requires_product_command_id": command,
        "product_command_id_transport": {"in": "header", "name": "Idempotency-Key"} if command else None,
        "identity_requirements": identities,
        "owning_authority_references": [
            {
                "reference_kind": "SEARCH_EXPERIMENT",
                "reference_schema_version": 1,
                "locator_kind": "SHA256",
                "response_field": "experiment_fingerprint",
            }
        ],
    }
    if command:
        metadata["response_effect_semantics"] = {
            "202": "COMMITTED_RESPONSE",
            "400": "DEFINITIVE_PRE_ADMISSION_REJECTION",
            "404": "DEFINITIVE_PRE_ADMISSION_REJECTION",
            "409": "DEFINITIVE_PRE_ADMISSION_REJECTION",
            "422": "DEFINITIVE_PRE_ADMISSION_REJECTION",
            "500": "EFFECT_UNKNOWN",
            "502": "EFFECT_UNKNOWN",
            "503": "EFFECT_UNKNOWN",
            "504": "EFFECT_UNKNOWN",
        }
    return {"x-onlyalpha-agent-operation": metadata}


def create_search_router(service: OnlySearchProductHttpBoundary) -> APIRouter:
    router = APIRouter(prefix="/api/v2/research/search", tags=[SEARCH_ROUTE_TAG])

    @router.post(
        "/symbolic-experiments",
        operation_id="submit_symbolic_search_experiment_v2",
        status_code=202,
        response_model=SearchCommandResponseDto,
        responses=_COMMAND_RESPONSES,
        openapi_extra=_operation(
            "SYMBOLIC_SEARCH",
            "IDEMPOTENT_COMMAND",
            command=True,
            identities=[
                "catalog_generation_fingerprint",
                "dataset_snapshot_fingerprint",
                "runtime_generation_fingerprint",
            ],
        ),
    )
    def submit_symbolic(
        request: SymbolicSearchSubmitRequestDto,
        response: Response,
        product_command_id: IdempotencyKey,
    ) -> SearchCommandResponseDto:
        result = service.submit_symbolic(product_command_id, request)
        response.headers["Idempotency-Key"] = product_command_id
        return result

    @router.post(
        "/parameter-experiments",
        operation_id="submit_parameter_search_experiment_v2",
        status_code=202,
        response_model=SearchCommandResponseDto,
        responses=_COMMAND_RESPONSES,
        openapi_extra=_operation(
            "PARAMETER_SEARCH",
            "IDEMPOTENT_COMMAND",
            command=True,
            identities=[
                "catalog_generation_fingerprint",
                "dataset_snapshot_fingerprint",
                "runtime_generation_fingerprint",
            ],
        ),
    )
    def submit_parameter(
        request: ParameterSearchSubmitRequestDto,
        response: Response,
        product_command_id: IdempotencyKey,
    ) -> SearchCommandResponseDto:
        result = service.submit_parameter(product_command_id, request)
        response.headers["Idempotency-Key"] = product_command_id
        return result

    @router.post(
        "/symbolic-experiments/advance",
        operation_id="advance_symbolic_search_experiment_v2",
        status_code=202,
        response_model=SearchCommandResponseDto,
        responses=_COMMAND_RESPONSES,
        openapi_extra=_operation(
            "SYMBOLIC_SEARCH", "IDEMPOTENT_COMMAND", command=True, identities=["experiment_fingerprint"]
        ),
    )
    def advance_symbolic(
        request: SearchAdvanceRequestDto,
        response: Response,
        product_command_id: IdempotencyKey,
    ) -> SearchCommandResponseDto:
        result = service.advance_symbolic(product_command_id, request)
        response.headers["Idempotency-Key"] = product_command_id
        return result

    @router.post(
        "/parameter-experiments/advance",
        operation_id="advance_parameter_search_experiment_v2",
        status_code=202,
        response_model=SearchCommandResponseDto,
        responses=_COMMAND_RESPONSES,
        openapi_extra=_operation(
            "PARAMETER_SEARCH", "IDEMPOTENT_COMMAND", command=True, identities=["experiment_fingerprint"]
        ),
    )
    def advance_parameter(
        request: SearchAdvanceRequestDto,
        response: Response,
        product_command_id: IdempotencyKey,
    ) -> SearchCommandResponseDto:
        result = service.advance_parameter(product_command_id, request)
        response.headers["Idempotency-Key"] = product_command_id
        return result

    @router.get(
        "/experiments/{experiment_fingerprint}",
        operation_id="get_search_experiment_v2",
        response_model=SearchExperimentResponseDto,
        responses=_ERRORS,
        openapi_extra=_operation(
            "SEARCH_QUERY", "MUTABLE_OBSERVATION_QUERY", command=False, identities=["experiment_fingerprint"]
        ),
    )
    def get_experiment(experiment_fingerprint: SearchExperimentPath) -> SearchExperimentResponseDto:
        return service.get_experiment(experiment_fingerprint)

    @router.get(
        "/experiments/{experiment_fingerprint}/ledger",
        operation_id="get_search_iteration_ledger_v2",
        response_model=SearchLedgerResponseDto,
        responses=_ERRORS,
        openapi_extra=_operation(
            "SEARCH_QUERY", "MUTABLE_OBSERVATION_QUERY", command=False, identities=["experiment_fingerprint"]
        ),
    )
    def get_ledger(experiment_fingerprint: SearchExperimentPath) -> SearchLedgerResponseDto:
        return service.get_ledger(experiment_fingerprint)

    @router.get(
        "/experiments/{experiment_fingerprint}/terminal",
        operation_id="get_search_terminal_v2",
        response_model=SearchTerminalResponseDto,
        responses=_ERRORS,
        openapi_extra=_operation(
            "SEARCH_QUERY", "MUTABLE_OBSERVATION_QUERY", command=False, identities=["experiment_fingerprint"]
        ),
    )
    def get_terminal(experiment_fingerprint: SearchExperimentPath) -> SearchTerminalResponseDto:
        return service.get_terminal(experiment_fingerprint)

    return router


__all__ = ["SEARCH_ROUTE_TAG", "create_search_router"]
