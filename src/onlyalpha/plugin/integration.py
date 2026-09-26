"""Provider-neutral Integration Type configuration and probe contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum, StrEnum
from typing import Protocol, runtime_checkable

from onlyalpha.canonical import only_canonical_fingerprint

_STABLE_ID = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_TYPE_ID = re.compile(r"^[a-z0-9]+(?:[._][a-z0-9]+)*$")
_FIELD_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_CAPABILITY_ID = re.compile(r"^[A-Z][A-Z0-9_]*(?::[A-Z0-9_.-]+)?$")

OnlyIntegrationScalar = str | int | float | bool


class OnlyIntegrationContractError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class OnlyIntegrationCategory(StrEnum):
    DATA_SOURCE = "DATA_SOURCE"
    BROKER = "BROKER"
    AGENT_PROVIDER = "AGENT_PROVIDER"


class OnlyIntegrationValueKind(StrEnum):
    STRING = "STRING"
    INTEGER = "INTEGER"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    ENUM = "ENUM"
    DURATION = "DURATION"
    PATH = "PATH"
    STRING_INTEGER_MAP = "STRING_INTEGER_MAP"


class OnlyIntegrationProbeMode(StrEnum):
    DEFAULT_INSTRUMENT = "DEFAULT_INSTRUMENT"


class OnlyIntegrationProbeCheck(StrEnum):
    CONNECTIVITY = "CONNECTIVITY"
    AUTHENTICATION = "AUTHENTICATION"
    REFERENCE_DATA = "REFERENCE_DATA"
    HISTORICAL_DATA = "HISTORICAL_DATA"
    REALTIME_DATA = "REALTIME_DATA"
    MODEL_DISCOVERY = "MODEL_DISCOVERY"


@dataclass(frozen=True, slots=True)
class OnlyIntegrationTypeId:
    value: str

    def __post_init__(self) -> None:
        if not _TYPE_ID.fullmatch(self.value) or "latest" in re.split(r"[._]", self.value):
            raise OnlyIntegrationContractError(
                "INTEGRATION_TYPE_CONTRACT_INVALID",
                "type_id must be a stable lowercase identifier without latest",
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OnlyIntegrationConfigurationFieldV1:
    field_id: str
    value_kind: OnlyIntegrationValueKind
    required: bool
    default: OnlyIntegrationScalar | None = None
    secret: bool = False
    advanced: bool = False
    display_name: str = ""
    description: str = ""
    enum_values: tuple[str, ...] = ()
    minimum: int | float | None = None
    maximum: int | float | None = None
    exclusive_minimum: bool = False

    def __post_init__(self) -> None:
        code = "INTEGRATION_CONFIGURATION_CONTRACT_INVALID"
        if not _FIELD_ID.fullmatch(self.field_id) or not self.display_name.strip():
            raise OnlyIntegrationContractError(code, "field_id and display_name are required")
        if not isinstance(self.value_kind, OnlyIntegrationValueKind):
            raise OnlyIntegrationContractError(code, f"invalid value kind for {self.field_id}")
        canonical_enums = tuple(sorted(self.enum_values))
        if len(set(canonical_enums)) != len(canonical_enums) or any(not value for value in canonical_enums):
            raise OnlyIntegrationContractError(code, f"invalid enum values for {self.field_id}")
        object.__setattr__(self, "enum_values", canonical_enums)
        if self.value_kind is OnlyIntegrationValueKind.ENUM:
            if not canonical_enums:
                raise OnlyIntegrationContractError(code, f"enum values are required for {self.field_id}")
        elif canonical_enums:
            raise OnlyIntegrationContractError(code, f"enum values are forbidden for {self.field_id}")
        if self.secret and self.default is not None:
            raise OnlyIntegrationContractError(code, f"secret defaults are forbidden for {self.field_id}")
        if self.default is not None and not _matches_kind(self.default, self.value_kind, canonical_enums):
            raise OnlyIntegrationContractError(code, f"default does not match {self.field_id} value kind")
        numeric = self.value_kind in {
            OnlyIntegrationValueKind.INTEGER,
            OnlyIntegrationValueKind.NUMBER,
            OnlyIntegrationValueKind.DURATION,
        }
        if not numeric and (self.minimum is not None or self.maximum is not None):
            raise OnlyIntegrationContractError(code, f"numeric bounds are forbidden for {self.field_id}")
        if self.exclusive_minimum and self.minimum is None:
            raise OnlyIntegrationContractError(code, f"exclusive minimum requires a bound for {self.field_id}")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise OnlyIntegrationContractError(code, f"invalid bounds for {self.field_id}")
        if self.default is not None and numeric:
            numeric_default = float(self.default)
            if self.minimum is not None and (
                numeric_default < self.minimum or (self.exclusive_minimum and numeric_default == self.minimum)
            ):
                raise OnlyIntegrationContractError(code, f"default is below the minimum for {self.field_id}")
            if self.maximum is not None and numeric_default > self.maximum:
                raise OnlyIntegrationContractError(code, f"default is above the maximum for {self.field_id}")

    def to_dict(self) -> dict[str, object]:
        return {
            "field_id": self.field_id,
            "value_kind": self.value_kind.value,
            "required": self.required,
            "default": self.default,
            "secret": self.secret,
            "advanced": self.advanced,
            "display_name": self.display_name,
            "description": self.description,
            "enum_values": list(self.enum_values),
            "minimum": self.minimum,
            "maximum": self.maximum,
            "exclusive_minimum": self.exclusive_minimum,
        }


@dataclass(frozen=True, slots=True)
class OnlyIntegrationConfigurationContractV1:
    fields: tuple[OnlyIntegrationConfigurationFieldV1, ...]
    schema_version: int = field(default=1, init=False)

    def __post_init__(self) -> None:
        canonical = tuple(sorted(self.fields, key=lambda item: item.field_id))
        if len({item.field_id for item in canonical}) != len(canonical):
            raise OnlyIntegrationContractError("INTEGRATION_CONFIGURATION_CONTRACT_INVALID", "field IDs must be unique")
        object.__setattr__(self, "fields", canonical)

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "fields": [item.to_dict() for item in self.fields],
        }
        if include_fingerprint:
            payload["fingerprint"] = self.fingerprint
        return payload


@dataclass(frozen=True, slots=True)
class OnlyIntegrationProbeContractV1:
    probe_mode: OnlyIntegrationProbeMode
    default_probe_instrument: str | None
    user_selectable_probe_instrument: bool
    probe_checks: tuple[OnlyIntegrationProbeCheck, ...]
    probe_version: int = field(default=1, init=False)

    def __post_init__(self) -> None:
        code = "INTEGRATION_PROBE_CONTRACT_INVALID"
        canonical = tuple(sorted(self.probe_checks, key=lambda item: item.value))
        if len(set(canonical)) != len(canonical):
            raise OnlyIntegrationContractError(code, "probe checks must be unique")
        object.__setattr__(self, "probe_checks", canonical)
        instrument = self.default_probe_instrument
        if instrument is not None and not instrument.strip():
            raise OnlyIntegrationContractError(code, "default probe instrument cannot be blank")
        if not canonical:
            raise OnlyIntegrationContractError(code, "probe checks are required")
        if self.probe_mode is OnlyIntegrationProbeMode.DEFAULT_INSTRUMENT and instrument is None:
            raise OnlyIntegrationContractError(code, "default probe instrument is required")

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "probe_version": self.probe_version,
            "probe_mode": self.probe_mode.value,
            "default_probe_instrument": self.default_probe_instrument,
            "user_selectable_probe_instrument": self.user_selectable_probe_instrument,
            "probe_checks": [item.value for item in self.probe_checks],
        }
        if include_fingerprint:
            payload["fingerprint"] = self.fingerprint
        return payload


@dataclass(frozen=True, slots=True)
class OnlyIntegrationTypeDescriptorV1:
    type_id: OnlyIntegrationTypeId
    category: OnlyIntegrationCategory
    display_name: str
    description: str
    provider_id: str
    implementation_id: str
    implementation_version: str
    public_api_version: str
    capabilities: tuple[str, ...]
    configuration_contract: OnlyIntegrationConfigurationContractV1
    probe_contract: OnlyIntegrationProbeContractV1 | None = None
    schema_version: int = field(default=1, init=False)

    def __post_init__(self) -> None:
        code = "INTEGRATION_TYPE_CONTRACT_INVALID"
        if not self.display_name.strip() or not self.description.strip():
            raise OnlyIntegrationContractError(code, "display_name and description are required")
        for name, value in (("provider_id", self.provider_id), ("implementation_id", self.implementation_id)):
            if not _STABLE_ID.fullmatch(value):
                raise OnlyIntegrationContractError(code, f"{name} must be a stable lowercase identifier")
        if not self.implementation_version.strip() or not self.public_api_version.strip():
            raise OnlyIntegrationContractError(code, "implementation and public API versions are required")
        canonical = tuple(sorted(self.capabilities))
        if len(set(canonical)) != len(canonical) or any(_CAPABILITY_ID.fullmatch(item) is None for item in canonical):
            raise OnlyIntegrationContractError(code, "capabilities must be unique stable identifiers")
        object.__setattr__(self, "capabilities", canonical)

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "type_id": self.type_id.value,
            "category": self.category.value,
            "display_name": self.display_name,
            "description": self.description,
            "provider_id": self.provider_id,
            "implementation_id": self.implementation_id,
            "implementation_version": self.implementation_version,
            "public_api_version": self.public_api_version,
            "capabilities": list(self.capabilities),
            "configuration_contract": self.configuration_contract.to_dict(include_fingerprint=True),
            "probe_contract": None
            if self.probe_contract is None
            else self.probe_contract.to_dict(include_fingerprint=True),
        }
        if include_fingerprint:
            payload["fingerprint"] = self.fingerprint
        return payload


@runtime_checkable
class OnlyIntegrationTypeProvider(Protocol):
    @property
    def integration_type(self) -> OnlyIntegrationTypeDescriptorV1: ...


@runtime_checkable
class OnlyIntegrationPublicConfigurationValidator(Protocol):
    def validate_public_integration_configuration(self, public_configuration: Mapping[str, object]) -> None: ...


@runtime_checkable
class OnlyIntegrationTypeCompatibilityProvider(Protocol):
    @property
    def compatible_type_descriptor_fingerprints(self) -> tuple[str, ...]: ...


def _matches_kind(
    value: OnlyIntegrationScalar,
    kind: OnlyIntegrationValueKind,
    enum_values: tuple[str, ...],
) -> bool:
    if kind in {OnlyIntegrationValueKind.STRING, OnlyIntegrationValueKind.PATH}:
        return isinstance(value, str)
    if kind is OnlyIntegrationValueKind.ENUM:
        return isinstance(value, str) and value in enum_values
    if kind is OnlyIntegrationValueKind.BOOLEAN:
        return isinstance(value, bool)
    if kind is OnlyIntegrationValueKind.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if kind in {OnlyIntegrationValueKind.NUMBER, OnlyIntegrationValueKind.DURATION}:
        return isinstance(value, int | float) and not isinstance(value, bool)
    return False


def only_integration_capability_ids(capabilities: object) -> tuple[str, ...]:
    """Project typed Plugin capabilities into provider-neutral stable IDs."""

    if not is_dataclass(capabilities) or isinstance(capabilities, type):
        raise OnlyIntegrationContractError(
            "INTEGRATION_TYPE_CONTRACT_INVALID", "plugin capabilities must be a typed dataclass"
        )
    projected: list[str] = []
    for item in fields(capabilities):
        value = getattr(capabilities, item.name)
        name = item.name.upper()
        if isinstance(value, bool):
            if value:
                projected.append(name)
        elif isinstance(value, Enum):
            projected.append(f"{name}:{value.value}")
        elif value is not None:
            projected.append(f"{name}:{value}")
    return tuple(sorted(projected))


__all__ = [
    "OnlyIntegrationCategory",
    "OnlyIntegrationConfigurationContractV1",
    "OnlyIntegrationConfigurationFieldV1",
    "OnlyIntegrationContractError",
    "OnlyIntegrationProbeCheck",
    "OnlyIntegrationProbeContractV1",
    "OnlyIntegrationProbeMode",
    "OnlyIntegrationScalar",
    "OnlyIntegrationTypeDescriptorV1",
    "OnlyIntegrationTypeId",
    "OnlyIntegrationTypeProvider",
    "OnlyIntegrationValueKind",
    "only_integration_capability_ids",
]
