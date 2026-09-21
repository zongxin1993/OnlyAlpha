"""Strict DTOs for configured Integration Product routes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr

from onlyalpha.application.integration_application import (
    OnlyIntegrationCommandResult,
    OnlyIntegrationSecretStatus,
)
from onlyalpha.application.integration_configuration import (
    OnlyIntegration,
    OnlyIntegrationDraft,
    OnlyIntegrationLifecycleState,
    OnlyIntegrationRevision,
    only_integration_json_document,
)
from onlyalpha.application.integration_probe import (
    OnlyIntegrationOperationalStatus,
    OnlyIntegrationProbeAttempt,
)
from onlyalpha.plugin.integration import OnlyIntegrationCategory
from onlyalpha.plugin.integration_probe import OnlyIntegrationProbeResult
from onlyalpha_http_server.integration_types.schema import IntegrationTypeDto

_SHA = r"^[0-9a-f]{64}$"


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class IntegrationCreateRequestDto(_Dto):
    schema_version: Literal[1]
    integration_id: str
    type_id: str
    display_name: str


class IntegrationCommandResponseDto(_Dto):
    schema_version: Literal[1] = 1
    command_id: str
    integration_id: str
    replayed: bool
    outcome_kind: str
    outcome_id: str

    @classmethod
    def from_result(cls, integration_id: str, value: OnlyIntegrationCommandResult) -> IntegrationCommandResponseDto:
        return cls(
            command_id=value.receipt.command_id.value,
            integration_id=integration_id,
            replayed=value.replayed,
            outcome_kind=value.receipt.outcome_ref.kind.value,
            outcome_id=value.receipt.outcome_ref.outcome_id,
        )


class IntegrationDto(_Dto):
    schema_version: Literal[1] = 1
    integration_id: str
    type_id: str
    display_name: str
    lifecycle_state: OnlyIntegrationLifecycleState
    current_revision_fingerprint: str | None = Field(default=None, pattern=_SHA)
    created_at: str
    updated_at: str

    @classmethod
    def from_model(cls, value: OnlyIntegration) -> IntegrationDto:
        return cls(
            integration_id=value.integration_id.value,
            type_id=value.type_id,
            display_name=value.display_name,
            lifecycle_state=value.lifecycle_state,
            current_revision_fingerprint=value.current_revision_fingerprint,
            created_at=_timestamp(value.created_at),
            updated_at=_timestamp(value.updated_at),
        )


class IntegrationSummaryDto(IntegrationDto):
    category: OnlyIntegrationCategory
    draft_version: int
    pinned_type_descriptor_fingerprint: str = Field(pattern=_SHA)


class IntegrationListDto(_Dto):
    items: tuple[IntegrationSummaryDto, ...]


class IntegrationSecretStatusDto(_Dto):
    field_id: str
    configured: bool
    generation: int | None


class IntegrationDraftDto(_Dto):
    schema_version: Literal[1] = 1
    integration_id: str
    base_revision_fingerprint: str | None = Field(default=None, pattern=_SHA)
    pinned_type_descriptor_fingerprint: str = Field(pattern=_SHA)
    type_descriptor: IntegrationTypeDto
    public_configuration: dict[str, JsonValue]
    probe_configuration: dict[str, JsonValue] | None
    draft_version: int
    draft_fingerprint: str = Field(pattern=_SHA)
    secret_statuses: tuple[IntegrationSecretStatusDto, ...]
    created_at: str
    updated_at: str

    @classmethod
    def from_model(
        cls,
        value: OnlyIntegrationDraft,
        secret_statuses: tuple[OnlyIntegrationSecretStatus, ...],
    ) -> IntegrationDraftDto:
        return cls(
            integration_id=value.integration_id.value,
            base_revision_fingerprint=value.base_revision_fingerprint,
            pinned_type_descriptor_fingerprint=value.type_descriptor_fingerprint,
            type_descriptor=IntegrationTypeDto.from_snapshot(
                value.type_descriptor_document, value.type_descriptor_fingerprint
            ),
            public_configuration=cast(
                dict[str, JsonValue], only_integration_json_document(value.public_configuration_document)
            ),
            probe_configuration=None
            if value.probe_configuration_document is None
            else cast(dict[str, JsonValue], only_integration_json_document(value.probe_configuration_document)),
            draft_version=value.draft_version,
            draft_fingerprint=value.draft_fingerprint,
            secret_statuses=tuple(
                IntegrationSecretStatusDto(
                    field_id=item.field_id,
                    configured=item.configured,
                    generation=item.generation,
                )
                for item in secret_statuses
            ),
            created_at=_timestamp(value.created_at),
            updated_at=_timestamp(value.updated_at),
        )


class IntegrationDraftUpdateRequestDto(_Dto):
    schema_version: Literal[1]
    expected_draft_version: int = Field(ge=1)
    public_configuration: dict[str, JsonValue]
    probe_configuration: dict[str, JsonValue] | None


class IntegrationSecretSetRequestDto(_Dto):
    schema_version: Literal[1]
    expected_draft_version: int = Field(ge=1)
    secret: SecretStr = Field(json_schema_extra={"writeOnly": True})


class IntegrationDraftContractResetRequestDto(_Dto):
    schema_version: Literal[1]
    expected_draft_version: int = Field(ge=1)


class IntegrationPublishRequestDto(_Dto):
    schema_version: Literal[1]
    expected_draft_version: int = Field(ge=1)


class IntegrationLifecycleUpdateRequestDto(_Dto):
    schema_version: Literal[1]
    expected_lifecycle_state: Literal["ACTIVE", "DISABLED", "ARCHIVED"]
    lifecycle_state: Literal["ACTIVE", "DISABLED", "ARCHIVED"]


class IntegrationProbeRequestDto(_Dto):
    schema_version: Literal[1]
    expected_revision_fingerprint: str = Field(pattern=_SHA)


class IntegrationProbeCheckDto(_Dto):
    check: str
    status: str
    latency_ms: int
    failure_kind: str | None
    error_code: str | None
    detail: str
    observations: tuple[str, ...]


class IntegrationProbeAttemptDto(_Dto):
    schema_version: Literal[1] = 1
    probe_attempt_id: str
    integration_id: str
    revision_fingerprint: str = Field(pattern=_SHA)
    type_id: str
    type_descriptor_fingerprint: str = Field(pattern=_SHA)
    probe_contract_fingerprint: str = Field(pattern=_SHA)
    probe_configuration_fingerprint: str | None = Field(default=None, pattern=_SHA)
    runtime_configuration_fingerprint: str = Field(pattern=_SHA)
    started_at: str
    completed_at: str
    overall_status: str
    probe_instrument: str | None
    checks: tuple[IntegrationProbeCheckDto, ...]

    @classmethod
    def from_model(cls, value: OnlyIntegrationProbeAttempt) -> IntegrationProbeAttemptDto:
        result = OnlyIntegrationProbeResult.restore(value.result_document, value.result_fingerprint)
        return cls(
            probe_attempt_id=value.probe_attempt_id,
            integration_id=value.integration_id.value,
            revision_fingerprint=value.revision_fingerprint,
            type_id=value.type_id,
            type_descriptor_fingerprint=value.type_descriptor_fingerprint,
            probe_contract_fingerprint=value.probe_contract_fingerprint,
            probe_configuration_fingerprint=value.probe_configuration_fingerprint,
            runtime_configuration_fingerprint=value.runtime_configuration_fingerprint,
            started_at=_timestamp(value.started_at),
            completed_at=_timestamp(value.completed_at),
            overall_status=value.overall_status.value,
            probe_instrument=result.probe_instrument,
            checks=tuple(
                IntegrationProbeCheckDto(
                    check=item.check.value,
                    status=item.status.value,
                    latency_ms=item.latency_ms,
                    failure_kind=None if item.failure_kind is None else item.failure_kind.value,
                    error_code=item.error_code,
                    detail=item.detail,
                    observations=item.observations,
                )
                for item in result.checks
            ),
        )


class IntegrationProbeAttemptListDto(_Dto):
    items: tuple[IntegrationProbeAttemptDto, ...]


class IntegrationOperationalStatusDto(_Dto):
    schema_version: Literal[1] = 1
    integration_id: str
    revision_fingerprint: str | None = Field(default=None, pattern=_SHA)
    status: str
    probe_attempt_id: str | None
    checked_at: str | None
    probe_supported: bool

    @classmethod
    def from_model(cls, value: OnlyIntegrationOperationalStatus) -> IntegrationOperationalStatusDto:
        return cls(
            integration_id=value.integration_id.value,
            revision_fingerprint=value.revision_fingerprint,
            status=value.status.value,
            probe_attempt_id=value.probe_attempt_id,
            checked_at=None if value.checked_at is None else _timestamp(value.checked_at),
            probe_supported=value.probe_supported,
        )


class IntegrationRevisionSummaryDto(_Dto):
    revision_fingerprint: str = Field(pattern=_SHA)
    revision_sequence: int
    type_id: str
    type_descriptor_fingerprint: str = Field(pattern=_SHA)
    configuration_fingerprint: str = Field(pattern=_SHA)
    runtime_configuration_fingerprint: str = Field(pattern=_SHA)
    probe_configuration_fingerprint: str | None = Field(default=None, pattern=_SHA)
    secret_binding_fingerprint: str = Field(pattern=_SHA)
    created_at: str

    @classmethod
    def from_model(cls, value: OnlyIntegrationRevision) -> IntegrationRevisionSummaryDto:
        return cls(
            revision_fingerprint=value.revision_fingerprint,
            revision_sequence=value.revision_sequence,
            type_id=value.type_id,
            type_descriptor_fingerprint=value.type_descriptor_fingerprint,
            configuration_fingerprint=value.configuration_fingerprint,
            runtime_configuration_fingerprint=value.runtime_configuration_fingerprint,
            probe_configuration_fingerprint=value.probe_configuration_fingerprint,
            secret_binding_fingerprint=value.secret_binding_fingerprint,
            created_at=_timestamp(value.created_at),
        )


class IntegrationRevisionListDto(_Dto):
    items: tuple[IntegrationRevisionSummaryDto, ...]


class IntegrationRevisionDto(IntegrationRevisionSummaryDto):
    schema_version: Literal[1] = 1
    integration_id: str
    type_descriptor: IntegrationTypeDto
    configuration: dict[str, JsonValue]
    probe_configuration: dict[str, JsonValue] | None
    secret_bindings: tuple[IntegrationSecretStatusDto, ...]

    @classmethod
    def from_revision(
        cls,
        value: OnlyIntegrationRevision,
        secret_bindings: tuple[OnlyIntegrationSecretStatus, ...],
    ) -> IntegrationRevisionDto:
        return cls(
            **IntegrationRevisionSummaryDto.from_model(value).model_dump(),
            integration_id=value.integration_id.value,
            type_descriptor=IntegrationTypeDto.from_snapshot(
                value.type_descriptor_document, value.type_descriptor_fingerprint
            ),
            configuration=cast(dict[str, JsonValue], only_integration_json_document(value.configuration_document)),
            probe_configuration=None
            if value.probe_configuration_document is None
            else cast(dict[str, JsonValue], only_integration_json_document(value.probe_configuration_document)),
            secret_bindings=tuple(
                IntegrationSecretStatusDto(
                    field_id=item.field_id,
                    configured=item.configured,
                    generation=item.generation,
                )
                for item in secret_bindings
            ),
        )


class IntegrationErrorDto(_Dto):
    code: str
    detail: str


class IntegrationErrorEnvelopeDto(_Dto):
    schema_version: Literal[1] = 1
    error: IntegrationErrorDto


__all__ = [name for name in globals() if name.startswith("Integration")]
