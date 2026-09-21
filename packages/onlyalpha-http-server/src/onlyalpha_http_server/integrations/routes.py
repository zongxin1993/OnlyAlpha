"""Thin configured Integration Product HTTP routes."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Header, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from onlyalpha.application.integration_application import (
    OnlyClearIntegrationSecret,
    OnlyCreateIntegration,
    OnlyIntegrationCommandService,
    OnlyIntegrationQueryService,
    OnlyPublishIntegrationRevision,
    OnlyResetIntegrationDraftContract,
    OnlySetIntegrationLifecycle,
    OnlySetIntegrationSecret,
    OnlyUpdateIntegrationDraft,
)
from onlyalpha.application.integration_configuration import (
    OnlyIntegrationError,
    OnlyIntegrationId,
    OnlyIntegrationLifecycleState,
)
from onlyalpha.application.product_command_receipt import OnlyProductCommandId

from ..integration_types.schema import IntegrationTypeDto
from .schema import (
    IntegrationCommandResponseDto,
    IntegrationCreateRequestDto,
    IntegrationDraftContractResetRequestDto,
    IntegrationDraftDto,
    IntegrationDraftUpdateRequestDto,
    IntegrationDto,
    IntegrationErrorDto,
    IntegrationErrorEnvelopeDto,
    IntegrationLifecycleUpdateRequestDto,
    IntegrationListDto,
    IntegrationPublishRequestDto,
    IntegrationRevisionDto,
    IntegrationRevisionListDto,
    IntegrationRevisionSummaryDto,
    IntegrationSecretSetRequestDto,
    IntegrationSummaryDto,
)

INTEGRATION_ROUTE_TAG = "integrations"
_CommandId = Annotated[str, Header(alias="Idempotency-Key")]
_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    400: {"model": IntegrationErrorEnvelopeDto, "description": "Invalid Integration request"},
    404: {"model": IntegrationErrorEnvelopeDto, "description": "Integration resource not found"},
    409: {"model": IntegrationErrorEnvelopeDto, "description": "Integration state conflict"},
    500: {"model": IntegrationErrorEnvelopeDto, "description": "Integration authority corrupt"},
    503: {"model": IntegrationErrorEnvelopeDto, "description": "Integration authority unavailable"},
}

_BAD_REQUEST = {
    "INTEGRATION_REQUEST_INVALID",
    "INTEGRATION_CONFIGURATION_INVALID",
    "INTEGRATION_CONFIGURATION_DOCUMENT_INVALID",
    "INTEGRATION_PROBE_CONFIGURATION_INVALID",
    "INTEGRATION_SECRET_FIELD_INVALID",
    "INTEGRATION_ID_INVALID",
}
_NOT_FOUND = {
    "INTEGRATION_NOT_FOUND",
    "INTEGRATION_DRAFT_NOT_FOUND",
    "INTEGRATION_REVISION_NOT_FOUND",
}
_CORRUPT = {
    "INTEGRATION_REVISION_CORRUPT",
    "PRODUCT_COMMAND_RECEIPT_CORRUPT",
    "PRODUCT_COMMAND_ADMISSION_CORRUPT",
}


def _error(status_code: int, code: str, detail: str) -> JSONResponse:
    body = IntegrationErrorEnvelopeDto(error=IntegrationErrorDto(code=code, detail=detail))
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def _integration_id(value: str) -> OnlyIntegrationId:
    try:
        return OnlyIntegrationId(value)
    except OnlyIntegrationError as error:
        raise OnlyIntegrationError("INTEGRATION_REQUEST_INVALID") from error


def _product_command_id(value: str) -> OnlyProductCommandId:
    try:
        return OnlyProductCommandId(value)
    except ValueError as error:
        raise OnlyIntegrationError("INTEGRATION_REQUEST_INVALID") from error


async def integration_request_validation_error_response(
    _request: Request, _error_value: RequestValidationError
) -> JSONResponse:
    return _error(400, "INTEGRATION_REQUEST_INVALID", "HTTP request validation failed")


async def integration_error_response(_request: Request, error: Exception) -> JSONResponse:
    code = getattr(error, "code", "INTEGRATION_REQUEST_INVALID")
    detail = getattr(error, "detail", "") or "Integration request failed"
    if code in _NOT_FOUND:
        return _error(404, code, "Integration resource not found")
    if code in _CORRUPT:
        return _error(500, code, "Verified Integration Product authority is corrupt")
    if code in {"INTEGRATION_PERSISTENCE_CONFLICT", "PRODUCT_COMMAND_AUTHORITY_UNAVAILABLE"}:
        return _error(503, code, "Required Integration Product authority is unavailable")
    if code in _BAD_REQUEST:
        return _error(400, "INTEGRATION_REQUEST_INVALID" if code == "INTEGRATION_ID_INVALID" else code, detail)
    return _error(409, code, detail)


def create_integration_router(
    commands: OnlyIntegrationCommandService,
    queries: OnlyIntegrationQueryService,
) -> APIRouter:
    router = APIRouter(prefix="/api/v2/integrations", tags=[INTEGRATION_ROUTE_TAG])

    @router.get("", response_model=IntegrationListDto, responses=_ERROR_RESPONSES)
    def list_integrations(
        type_id: str | None = None,
        lifecycle_state: OnlyIntegrationLifecycleState | None = None,
    ) -> IntegrationListDto:
        items = []
        for integration in queries.list_integrations(type_id=type_id, lifecycle_state=lifecycle_state):
            draft = queries.get_draft(integration.integration_id)
            descriptor = IntegrationTypeDto.from_snapshot(
                draft.type_descriptor_document, draft.type_descriptor_fingerprint
            )
            items.append(
                IntegrationSummaryDto(
                    **IntegrationDto.from_model(integration).model_dump(),
                    category=descriptor.category,
                    draft_version=draft.draft_version,
                    pinned_type_descriptor_fingerprint=draft.type_descriptor_fingerprint,
                )
            )
        return IntegrationListDto(items=tuple(items))

    @router.post(
        "",
        response_model=IntegrationCommandResponseDto,
        status_code=status.HTTP_201_CREATED,
        responses=_ERROR_RESPONSES,
    )
    def create_integration(
        request: IntegrationCreateRequestDto,
        response: Response,
        command_id: _CommandId,
    ) -> IntegrationCommandResponseDto:
        integration_id = _integration_id(request.integration_id)
        result = commands.create_integration(
            OnlyCreateIntegration(
                _product_command_id(command_id), integration_id, request.type_id, request.display_name
            )
        )
        response.headers["Location"] = f"/api/v2/integrations/{integration_id.value}"
        return IntegrationCommandResponseDto.from_result(integration_id.value, result)

    @router.get("/{integration_id}", response_model=IntegrationDto, responses=_ERROR_RESPONSES)
    def get_integration(integration_id: str) -> IntegrationDto:
        return IntegrationDto.from_model(queries.get_integration(_integration_id(integration_id)))

    @router.get("/{integration_id}/draft", response_model=IntegrationDraftDto, responses=_ERROR_RESPONSES)
    def get_integration_draft(integration_id: str) -> IntegrationDraftDto:
        identity = _integration_id(integration_id)
        return IntegrationDraftDto.from_model(queries.get_draft(identity), queries.get_draft_secret_status(identity))

    @router.put("/{integration_id}/draft", response_model=IntegrationCommandResponseDto, responses=_ERROR_RESPONSES)
    def update_integration_draft(
        integration_id: str,
        request: IntegrationDraftUpdateRequestDto,
        command_id: _CommandId,
    ) -> IntegrationCommandResponseDto:
        identity = _integration_id(integration_id)
        result = commands.update_integration_draft(
            OnlyUpdateIntegrationDraft(
                _product_command_id(command_id),
                identity,
                request.expected_draft_version,
                cast(dict[str, object], request.public_configuration),
                cast(dict[str, object] | None, request.probe_configuration),
            )
        )
        return IntegrationCommandResponseDto.from_result(integration_id, result)

    @router.put(
        "/{integration_id}/draft/secrets/{field_id}",
        response_model=IntegrationCommandResponseDto,
        responses=_ERROR_RESPONSES,
    )
    def set_integration_secret(
        integration_id: str,
        field_id: str,
        request: IntegrationSecretSetRequestDto,
        command_id: _CommandId,
    ) -> IntegrationCommandResponseDto:
        identity = _integration_id(integration_id)
        result = commands.set_integration_secret(
            OnlySetIntegrationSecret(
                _product_command_id(command_id),
                identity,
                request.expected_draft_version,
                field_id,
                request.secret.get_secret_value(),
            )
        )
        return IntegrationCommandResponseDto.from_result(integration_id, result)

    @router.delete(
        "/{integration_id}/draft/secrets/{field_id}",
        response_model=IntegrationCommandResponseDto,
        responses=_ERROR_RESPONSES,
    )
    def clear_integration_secret(
        integration_id: str,
        field_id: str,
        expected_draft_version: int,
        command_id: _CommandId,
    ) -> IntegrationCommandResponseDto:
        identity = _integration_id(integration_id)
        result = commands.clear_integration_secret(
            OnlyClearIntegrationSecret(_product_command_id(command_id), identity, expected_draft_version, field_id)
        )
        return IntegrationCommandResponseDto.from_result(integration_id, result)

    @router.post(
        "/{integration_id}/draft/contract-reset",
        response_model=IntegrationCommandResponseDto,
        responses=_ERROR_RESPONSES,
    )
    def reset_integration_draft_contract(
        integration_id: str,
        request: IntegrationDraftContractResetRequestDto,
        command_id: _CommandId,
    ) -> IntegrationCommandResponseDto:
        identity = _integration_id(integration_id)
        result = commands.reset_integration_draft_contract(
            OnlyResetIntegrationDraftContract(_product_command_id(command_id), identity, request.expected_draft_version)
        )
        return IntegrationCommandResponseDto.from_result(integration_id, result)

    @router.post(
        "/{integration_id}/revisions", response_model=IntegrationCommandResponseDto, responses=_ERROR_RESPONSES
    )
    def publish_integration_revision(
        integration_id: str,
        request: IntegrationPublishRequestDto,
        response: Response,
        command_id: _CommandId,
    ) -> IntegrationCommandResponseDto:
        identity = _integration_id(integration_id)
        result = commands.publish_integration_revision(
            OnlyPublishIntegrationRevision(_product_command_id(command_id), identity, request.expected_draft_version)
        )
        response.headers["Location"] = (
            f"/api/v2/integrations/{integration_id}/revisions/{result.receipt.outcome_ref.outcome_id}"
        )
        return IntegrationCommandResponseDto.from_result(integration_id, result)

    @router.get("/{integration_id}/revisions", response_model=IntegrationRevisionListDto, responses=_ERROR_RESPONSES)
    def list_integration_revisions(integration_id: str) -> IntegrationRevisionListDto:
        revisions = queries.list_revision_history(_integration_id(integration_id))
        return IntegrationRevisionListDto(
            items=tuple(IntegrationRevisionSummaryDto.from_model(item) for item in revisions)
        )

    @router.get(
        "/{integration_id}/revisions/{revision_fingerprint}",
        response_model=IntegrationRevisionDto,
        responses=_ERROR_RESPONSES,
    )
    def get_integration_revision(integration_id: str, revision_fingerprint: str) -> IntegrationRevisionDto:
        identity = _integration_id(integration_id)
        revision = queries.get_revision(revision_fingerprint)
        if revision.integration_id != identity:
            raise OnlyIntegrationError("INTEGRATION_REVISION_NOT_FOUND")
        return IntegrationRevisionDto.from_revision(revision, queries.get_revision_secret_status(revision_fingerprint))

    @router.put("/{integration_id}/lifecycle", response_model=IntegrationCommandResponseDto, responses=_ERROR_RESPONSES)
    def set_integration_lifecycle(
        integration_id: str,
        request: IntegrationLifecycleUpdateRequestDto,
        command_id: _CommandId,
    ) -> IntegrationCommandResponseDto:
        identity = _integration_id(integration_id)
        result = commands.set_integration_lifecycle(
            OnlySetIntegrationLifecycle(
                _product_command_id(command_id),
                identity,
                OnlyIntegrationLifecycleState(request.expected_lifecycle_state),
                OnlyIntegrationLifecycleState(request.lifecycle_state),
            )
        )
        return IntegrationCommandResponseDto.from_result(integration_id, result)

    return router


__all__ = [
    "INTEGRATION_ROUTE_TAG",
    "create_integration_router",
    "integration_error_response",
    "integration_request_validation_error_response",
]
