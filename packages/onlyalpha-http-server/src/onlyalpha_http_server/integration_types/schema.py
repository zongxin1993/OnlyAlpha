"""Typed transport projection for Integration Type contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from onlyalpha.application.integration_configuration import OnlyIntegrationError
from onlyalpha.plugin.integration import (
    OnlyIntegrationCategory,
    OnlyIntegrationConfigurationContractV1,
    OnlyIntegrationConfigurationFieldV1,
    OnlyIntegrationProbeCheck,
    OnlyIntegrationProbeContractV1,
    OnlyIntegrationProbeMode,
    OnlyIntegrationScalar,
    OnlyIntegrationTypeDescriptorV1,
    OnlyIntegrationValueKind,
)

_SHA = r"^[0-9a-f]{64}$"


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class IntegrationConfigurationFieldDto(_Dto):
    field_id: str
    value_kind: OnlyIntegrationValueKind
    required: bool
    default: OnlyIntegrationScalar | None
    secret: bool
    advanced: bool
    display_name: str
    description: str
    enum_values: tuple[str, ...]
    minimum: int | float | None
    maximum: int | float | None
    exclusive_minimum: bool

    @classmethod
    def from_model(cls, value: OnlyIntegrationConfigurationFieldV1) -> IntegrationConfigurationFieldDto:
        return cls(
            field_id=value.field_id,
            value_kind=value.value_kind,
            required=value.required,
            default=value.default,
            secret=value.secret,
            advanced=value.advanced,
            display_name=value.display_name,
            description=value.description,
            enum_values=value.enum_values,
            minimum=value.minimum,
            maximum=value.maximum,
            exclusive_minimum=value.exclusive_minimum,
        )


class IntegrationConfigurationContractDto(_Dto):
    schema_version: Literal[1]
    fields: tuple[IntegrationConfigurationFieldDto, ...]
    fingerprint: str = Field(pattern=_SHA)

    @classmethod
    def from_model(cls, value: OnlyIntegrationConfigurationContractV1) -> IntegrationConfigurationContractDto:
        return cls(
            schema_version=1,
            fields=tuple(IntegrationConfigurationFieldDto.from_model(item) for item in value.fields),
            fingerprint=value.fingerprint,
        )


class IntegrationProbeContractDto(_Dto):
    probe_version: Literal[1]
    probe_mode: OnlyIntegrationProbeMode
    default_probe_instrument: str | None
    user_selectable_probe_instrument: bool
    probe_checks: tuple[OnlyIntegrationProbeCheck, ...]
    fingerprint: str = Field(pattern=_SHA)

    @classmethod
    def from_model(cls, value: OnlyIntegrationProbeContractV1) -> IntegrationProbeContractDto:
        return cls(
            probe_version=1,
            probe_mode=value.probe_mode,
            default_probe_instrument=value.default_probe_instrument,
            user_selectable_probe_instrument=value.user_selectable_probe_instrument,
            probe_checks=value.probe_checks,
            fingerprint=value.fingerprint,
        )


class IntegrationTypeDto(_Dto):
    schema_version: Literal[1]
    type_id: str
    category: OnlyIntegrationCategory
    display_name: str
    description: str
    provider_id: str
    implementation_id: str
    implementation_version: str
    public_api_version: str
    capabilities: tuple[str, ...]
    configuration_contract: IntegrationConfigurationContractDto
    probe_contract: IntegrationProbeContractDto | None
    fingerprint: str = Field(pattern=_SHA)

    @classmethod
    def from_model(cls, value: OnlyIntegrationTypeDescriptorV1) -> IntegrationTypeDto:
        return cls(
            schema_version=1,
            type_id=value.type_id.value,
            category=value.category,
            display_name=value.display_name,
            description=value.description,
            provider_id=value.provider_id,
            implementation_id=value.implementation_id,
            implementation_version=value.implementation_version,
            public_api_version=value.public_api_version,
            capabilities=value.capabilities,
            configuration_contract=IntegrationConfigurationContractDto.from_model(value.configuration_contract),
            probe_contract=None
            if value.probe_contract is None
            else IntegrationProbeContractDto.from_model(value.probe_contract),
            fingerprint=value.fingerprint,
        )

    @classmethod
    def from_snapshot(cls, document: Mapping[str, object], fingerprint: str) -> IntegrationTypeDto:
        try:
            return cls.model_validate({**document, "fingerprint": fingerprint}, strict=False)
        except ValidationError as error:
            raise OnlyIntegrationError("INTEGRATION_REVISION_CORRUPT") from error


class IntegrationTypeListDto(_Dto):
    items: tuple[IntegrationTypeDto, ...]


class IntegrationTypeErrorDto(_Dto):
    code: str
    detail: str


class IntegrationTypeErrorEnvelopeDto(_Dto):
    error: IntegrationTypeErrorDto


__all__ = [
    "IntegrationTypeDto",
    "IntegrationTypeErrorDto",
    "IntegrationTypeErrorEnvelopeDto",
    "IntegrationTypeListDto",
]
