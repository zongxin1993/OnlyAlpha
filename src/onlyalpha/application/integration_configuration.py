"""Provider-neutral Integration Draft and immutable Revision contracts."""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import NoReturn, cast

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.plugin.integration import OnlyIntegrationTypeDescriptorV1

_FIELD_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


class OnlyIntegrationError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class OnlyIntegrationLifecycleState(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    ARCHIVED = "ARCHIVED"


@dataclass(frozen=True, order=True, slots=True)
class OnlyIntegrationId:
    value: str

    def __post_init__(self) -> None:
        try:
            parsed = uuid.UUID(self.value)
        except (AttributeError, TypeError, ValueError) as exc:
            raise OnlyIntegrationError("INTEGRATION_ID_INVALID") from exc
        if parsed.version != 4 or str(parsed) != self.value:
            raise OnlyIntegrationError("INTEGRATION_ID_INVALID")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OnlyIntegration:
    integration_id: OnlyIntegrationId
    type_id: str
    display_name: str
    lifecycle_state: OnlyIntegrationLifecycleState
    current_revision_fingerprint: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.integration_id, OnlyIntegrationId) or not self.type_id:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "invalid Integration identity")
        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "display_name must be non-empty")
        if not isinstance(self.lifecycle_state, OnlyIntegrationLifecycleState):
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "invalid lifecycle state")
        _fingerprint(self.current_revision_fingerprint, optional=True)
        _utc(self.created_at)
        _utc(self.updated_at)


@dataclass(frozen=True, order=True, slots=True)
class OnlyIntegrationSecretBinding:
    field_id: str
    credential_id: str
    credential_generation: int

    def __post_init__(self) -> None:
        if _FIELD_ID.fullmatch(self.field_id) is None:
            raise OnlyIntegrationError("INTEGRATION_SECRET_BINDING_INVALID", "field_id is invalid")
        try:
            parsed = uuid.UUID(self.credential_id)
        except (AttributeError, TypeError, ValueError) as exc:
            raise OnlyIntegrationError("INTEGRATION_SECRET_BINDING_INVALID", "credential_id is invalid") from exc
        valid_generation = (
            isinstance(self.credential_generation, int)
            and not isinstance(self.credential_generation, bool)
            and self.credential_generation >= 1
        )
        if parsed.version != 4 or str(parsed) != self.credential_id or not valid_generation:
            raise OnlyIntegrationError("INTEGRATION_SECRET_BINDING_INVALID", "credential binding is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "field_id": self.field_id,
            "credential_id": self.credential_id,
            "credential_generation": self.credential_generation,
        }


def only_integration_secret_binding_fingerprint(bindings: tuple[OnlyIntegrationSecretBinding, ...]) -> str:
    canonical = tuple(sorted(bindings, key=lambda item: item.field_id))
    if len({item.field_id for item in canonical}) != len(canonical):
        raise OnlyIntegrationError("INTEGRATION_SECRET_BINDING_INVALID", "field bindings must be unique")
    return only_canonical_fingerprint([item.to_dict() for item in canonical])


@dataclass(frozen=True, slots=True)
class OnlyIntegrationDraft:
    integration_id: OnlyIntegrationId
    base_revision_fingerprint: str | None
    type_descriptor_fingerprint: str
    type_descriptor_document: Mapping[str, object]
    public_configuration_document: Mapping[str, object]
    probe_configuration_document: Mapping[str, object] | None
    draft_version: int
    draft_fingerprint: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        integration_id: OnlyIntegrationId,
        descriptor: OnlyIntegrationTypeDescriptorV1,
        public_configuration: Mapping[str, object],
        probe_configuration: Mapping[str, object] | None,
        created_at: datetime,
        base_revision_fingerprint: str | None = None,
    ) -> OnlyIntegrationDraft:
        descriptor_document = _object(descriptor.to_dict(include_fingerprint=False), "type_descriptor_document")
        public_document = _object(public_configuration, "public_configuration_document")
        probe_document = (
            None if probe_configuration is None else _object(probe_configuration, "probe_configuration_document")
        )
        _reject_secret_fields(descriptor_document, public_document, probe_document)
        _fingerprint(base_revision_fingerprint, optional=True)
        _utc(created_at)
        return cls(
            integration_id,
            base_revision_fingerprint,
            descriptor.fingerprint,
            descriptor_document,
            public_document,
            probe_document,
            1,
            only_integration_draft_fingerprint(
                integration_id,
                base_revision_fingerprint,
                descriptor.fingerprint,
                descriptor_document,
                public_document,
                probe_document,
                (),
            ),
            created_at,
            created_at,
        )

    @classmethod
    def restore(
        cls,
        *,
        integration_id: OnlyIntegrationId,
        base_revision_fingerprint: str | None,
        type_descriptor_fingerprint: str,
        type_descriptor_document: Mapping[str, object],
        public_configuration_document: Mapping[str, object],
        probe_configuration_document: Mapping[str, object] | None,
        draft_version: int,
        draft_fingerprint: str,
        created_at: datetime,
        updated_at: datetime,
        secret_bindings: tuple[OnlyIntegrationSecretBinding, ...],
    ) -> OnlyIntegrationDraft:
        descriptor_document = _object(type_descriptor_document, "type_descriptor_document")
        public_document = _object(public_configuration_document, "public_configuration_document")
        probe_document = (
            None
            if probe_configuration_document is None
            else _object(probe_configuration_document, "probe_configuration_document")
        )
        _fingerprint(base_revision_fingerprint, optional=True)
        _fingerprint(type_descriptor_fingerprint)
        _fingerprint(draft_fingerprint)
        _utc(created_at)
        _utc(updated_at)
        if draft_version < 1 or only_canonical_fingerprint(descriptor_document) != type_descriptor_fingerprint:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Draft evidence is corrupt")
        _reject_secret_fields(descriptor_document, public_document, probe_document)
        expected = only_integration_draft_fingerprint(
            integration_id,
            base_revision_fingerprint,
            type_descriptor_fingerprint,
            descriptor_document,
            public_document,
            probe_document,
            secret_bindings,
        )
        if expected != draft_fingerprint:
            raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "Draft fingerprint is corrupt")
        return cls(
            integration_id,
            base_revision_fingerprint,
            type_descriptor_fingerprint,
            descriptor_document,
            public_document,
            probe_document,
            draft_version,
            draft_fingerprint,
            created_at,
            updated_at,
        )


@dataclass(frozen=True, slots=True)
class OnlyIntegrationRevision:
    revision_fingerprint: str
    integration_id: OnlyIntegrationId
    revision_sequence: int
    type_id: str
    type_descriptor_fingerprint: str
    type_descriptor_document: Mapping[str, object]
    configuration_fingerprint: str
    configuration_document: Mapping[str, object]
    runtime_configuration_fingerprint: str
    probe_configuration_fingerprint: str | None
    probe_configuration_document: Mapping[str, object] | None
    secret_binding_fingerprint: str
    created_at: datetime

    @classmethod
    def from_draft(
        cls,
        draft: OnlyIntegrationDraft,
        revision_sequence: int,
        runtime_configuration_fingerprint: str,
        secret_bindings: tuple[OnlyIntegrationSecretBinding, ...],
        created_at: datetime,
    ) -> OnlyIntegrationRevision:
        if revision_sequence < 1:
            raise OnlyIntegrationError("INTEGRATION_REVISION_CORRUPT", "revision_sequence must be positive")
        _fingerprint(runtime_configuration_fingerprint)
        _utc(created_at)
        if only_canonical_fingerprint(draft.type_descriptor_document) != draft.type_descriptor_fingerprint:
            raise OnlyIntegrationError("INTEGRATION_REVISION_CORRUPT", "Draft descriptor evidence is corrupt")
        _reject_secret_fields(
            draft.type_descriptor_document,
            draft.public_configuration_document,
            draft.probe_configuration_document,
        )
        type_id = cast(str, draft.type_descriptor_document["type_id"])
        configuration_fingerprint = only_canonical_fingerprint(draft.public_configuration_document)
        probe_fingerprint = (
            None
            if draft.probe_configuration_document is None
            else only_canonical_fingerprint(draft.probe_configuration_document)
        )
        binding_fingerprint = only_integration_secret_binding_fingerprint(secret_bindings)
        payload = {
            "integration_id": draft.integration_id.value,
            "type_id": type_id,
            "type_descriptor_fingerprint": draft.type_descriptor_fingerprint,
            "type_descriptor_document": draft.type_descriptor_document,
            "configuration_fingerprint": configuration_fingerprint,
            "configuration_document": draft.public_configuration_document,
            "runtime_configuration_fingerprint": runtime_configuration_fingerprint,
            "probe_configuration_fingerprint": probe_fingerprint,
            "probe_configuration_document": draft.probe_configuration_document,
            "secret_binding_fingerprint": binding_fingerprint,
        }
        return cls(
            only_canonical_fingerprint(payload),
            draft.integration_id,
            revision_sequence,
            type_id,
            draft.type_descriptor_fingerprint,
            draft.type_descriptor_document,
            configuration_fingerprint,
            draft.public_configuration_document,
            runtime_configuration_fingerprint,
            probe_fingerprint,
            draft.probe_configuration_document,
            binding_fingerprint,
            created_at,
        )

    @classmethod
    def restore(
        cls,
        *,
        revision_fingerprint: str,
        integration_id: OnlyIntegrationId,
        revision_sequence: int,
        type_id: str,
        type_descriptor_fingerprint: str,
        type_descriptor_document: Mapping[str, object],
        configuration_fingerprint: str,
        configuration_document: Mapping[str, object],
        runtime_configuration_fingerprint: str,
        probe_configuration_fingerprint: str | None,
        probe_configuration_document: Mapping[str, object] | None,
        secret_binding_fingerprint: str,
        created_at: datetime,
        secret_bindings: tuple[OnlyIntegrationSecretBinding, ...],
    ) -> OnlyIntegrationRevision:
        descriptor_document = _object(type_descriptor_document, "type_descriptor_document")
        configuration = _object(configuration_document, "configuration_document")
        probe = (
            None
            if probe_configuration_document is None
            else _object(probe_configuration_document, "probe_configuration_document")
        )
        for fingerprint in (
            revision_fingerprint,
            type_descriptor_fingerprint,
            configuration_fingerprint,
            runtime_configuration_fingerprint,
            secret_binding_fingerprint,
        ):
            _fingerprint(fingerprint)
        _fingerprint(probe_configuration_fingerprint, optional=True)
        _utc(created_at)
        if revision_sequence < 1 or descriptor_document.get("type_id") != type_id:
            raise OnlyIntegrationError("INTEGRATION_REVISION_CORRUPT")
        _reject_secret_fields(descriptor_document, configuration, probe)
        binding_fingerprint = only_integration_secret_binding_fingerprint(secret_bindings)
        expected_probe_fingerprint = None if probe is None else only_canonical_fingerprint(probe)
        payload = {
            "integration_id": integration_id.value,
            "type_id": type_id,
            "type_descriptor_fingerprint": type_descriptor_fingerprint,
            "type_descriptor_document": descriptor_document,
            "configuration_fingerprint": configuration_fingerprint,
            "configuration_document": configuration,
            "runtime_configuration_fingerprint": runtime_configuration_fingerprint,
            "probe_configuration_fingerprint": probe_configuration_fingerprint,
            "probe_configuration_document": probe,
            "secret_binding_fingerprint": secret_binding_fingerprint,
        }
        valid = (
            only_canonical_fingerprint(descriptor_document) == type_descriptor_fingerprint
            and only_canonical_fingerprint(configuration) == configuration_fingerprint
            and expected_probe_fingerprint == probe_configuration_fingerprint
            and binding_fingerprint == secret_binding_fingerprint
            and only_canonical_fingerprint(payload) == revision_fingerprint
        )
        if not valid:
            raise OnlyIntegrationError("INTEGRATION_REVISION_CORRUPT")
        return cls(
            revision_fingerprint,
            integration_id,
            revision_sequence,
            type_id,
            type_descriptor_fingerprint,
            descriptor_document,
            configuration_fingerprint,
            configuration,
            runtime_configuration_fingerprint,
            probe_configuration_fingerprint,
            probe,
            secret_binding_fingerprint,
            created_at,
        )


def only_integration_draft_fingerprint(
    integration_id: OnlyIntegrationId,
    base_revision_fingerprint: str | None,
    type_descriptor_fingerprint: str,
    type_descriptor_document: Mapping[str, object],
    public_configuration_document: Mapping[str, object],
    probe_configuration_document: Mapping[str, object] | None,
    secret_bindings: tuple[OnlyIntegrationSecretBinding, ...],
) -> str:
    return only_canonical_fingerprint(
        {
            "integration_id": integration_id.value,
            "base_revision_fingerprint": base_revision_fingerprint,
            "type_descriptor_fingerprint": type_descriptor_fingerprint,
            "type_descriptor_document": type_descriptor_document,
            "public_configuration_document": public_configuration_document,
            "probe_configuration_document": probe_configuration_document,
            "secret_binding_fingerprint": only_integration_secret_binding_fingerprint(secret_bindings),
        }
    )


def only_integration_json_document(value: Mapping[str, object]) -> dict[str, object]:
    """Project one frozen canonical document back to plain JSON containers."""

    return cast(dict[str, object], _thaw_json(value))


def _invalid_document(detail: str) -> NoReturn:
    raise OnlyIntegrationError("INTEGRATION_CONFIGURATION_DOCUMENT_INVALID", detail)


def _freeze_json(value: object, name: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _invalid_document(f"{name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            _invalid_document(f"{name} keys must be strings")
        return MappingProxyType({key: _freeze_json(item, name) for key, item in sorted(value.items())})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, name) for item in value)
    _invalid_document(f"{name} must contain JSON values")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _object(value: object, name: str) -> Mapping[str, object]:
    frozen = _freeze_json(value, name)
    if not isinstance(frozen, Mapping):
        _invalid_document(f"{name} must be an object")
    return cast(Mapping[str, object], frozen)


def _reject_secret_fields(
    descriptor_document: Mapping[str, object],
    *documents: Mapping[str, object] | None,
) -> None:
    configuration = descriptor_document.get("configuration_contract")
    if not isinstance(configuration, Mapping):
        _invalid_document("type descriptor configuration contract is missing")
    fields = configuration.get("fields")
    if not isinstance(fields, tuple):
        _invalid_document("type descriptor fields are invalid")
    secret_ids = {
        field.get("field_id") for field in fields if isinstance(field, Mapping) and field.get("secret") is True
    }
    if any(document is not None and secret_ids & document.keys() for document in documents):
        _invalid_document("configuration contains a declared secret field")


def _fingerprint(value: str | None, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, str) or _FINGERPRINT.fullmatch(value) is None:
        raise OnlyIntegrationError("INTEGRATION_REVISION_CORRUPT", "fingerprint must be lower-case SHA-256")


def _utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise OnlyIntegrationError("INTEGRATION_PERSISTENCE_CONFLICT", "timestamp must be timezone-aware UTC")


__all__ = [name for name in globals() if name.startswith(("Only", "only_"))]
