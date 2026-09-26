"""Product-level Integration configuration resolution and command contracts."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Protocol, cast

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.plugin.integration import (
    OnlyIntegrationConfigurationFieldV1,
    OnlyIntegrationProbeMode,
    OnlyIntegrationTypeDescriptorV1,
    OnlyIntegrationValueKind,
)

from .integration_configuration import (
    OnlyIntegration,
    OnlyIntegrationDraft,
    OnlyIntegrationError,
    OnlyIntegrationId,
    OnlyIntegrationLifecycleState,
    OnlyIntegrationRevision,
    OnlyIntegrationSecretBinding,
    only_integration_runtime_configuration_fingerprint,
    only_integration_secret_binding_fingerprint,
)
from .product_command_receipt import (
    OnlyProductCommandAdmissionV1,
    OnlyProductCommandId,
    OnlyProductCommandKind,
    OnlyProductCommandOutcomeKind,
    OnlyProductCommandReceipt,
    only_product_command_fingerprint,
)

_COMMITMENT_INFO = b"ONLYALPHA_INTEGRATION_SECRET_COMMAND_COMMITMENT_V1"


@dataclass(frozen=True, slots=True)
class OnlyCreateIntegration:
    command_id: OnlyProductCommandId
    integration_id: OnlyIntegrationId
    type_id: str
    display_name: str

    def __post_init__(self) -> None:
        if not self.type_id or not self.display_name.strip():
            raise OnlyIntegrationError("INTEGRATION_CONFIGURATION_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyUpdateIntegrationDraft:
    command_id: OnlyProductCommandId
    integration_id: OnlyIntegrationId
    expected_draft_version: int
    public_configuration: Mapping[str, object]
    probe_configuration: Mapping[str, object] | None

    def __post_init__(self) -> None:
        _expected_version(self.expected_draft_version)
        object.__setattr__(self, "public_configuration", _freeze_document(self.public_configuration))
        if self.probe_configuration is not None:
            object.__setattr__(self, "probe_configuration", _freeze_document(self.probe_configuration))


@dataclass(frozen=True, slots=True)
class OnlySetIntegrationSecret:
    command_id: OnlyProductCommandId
    integration_id: OnlyIntegrationId
    expected_draft_version: int
    field_id: str
    plaintext_secret: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.command_id, OnlyProductCommandId)
            or not isinstance(self.integration_id, OnlyIntegrationId)
            or not isinstance(self.expected_draft_version, int)
            or isinstance(self.expected_draft_version, bool)
            or self.expected_draft_version < 1
            or not isinstance(self.field_id, str)
            or not self.field_id
            or not isinstance(self.plaintext_secret, str)
            or not self.plaintext_secret
        ):
            raise OnlyIntegrationError("INTEGRATION_CONFIGURATION_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyClearIntegrationSecret:
    command_id: OnlyProductCommandId
    integration_id: OnlyIntegrationId
    expected_draft_version: int
    field_id: str

    def __post_init__(self) -> None:
        _expected_version(self.expected_draft_version)
        if not self.field_id:
            raise OnlyIntegrationError("INTEGRATION_SECRET_FIELD_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyResetIntegrationDraftContract:
    command_id: OnlyProductCommandId
    integration_id: OnlyIntegrationId
    expected_draft_version: int

    def __post_init__(self) -> None:
        _expected_version(self.expected_draft_version)


@dataclass(frozen=True, slots=True)
class OnlyPublishIntegrationRevision:
    command_id: OnlyProductCommandId
    integration_id: OnlyIntegrationId
    expected_draft_version: int

    def __post_init__(self) -> None:
        _expected_version(self.expected_draft_version)


@dataclass(frozen=True, slots=True)
class OnlySetIntegrationLifecycle:
    command_id: OnlyProductCommandId
    integration_id: OnlyIntegrationId
    expected_lifecycle_state: OnlyIntegrationLifecycleState
    lifecycle_state: OnlyIntegrationLifecycleState

    def __post_init__(self) -> None:
        if not isinstance(self.expected_lifecycle_state, OnlyIntegrationLifecycleState) or not isinstance(
            self.lifecycle_state, OnlyIntegrationLifecycleState
        ):
            raise OnlyIntegrationError("INTEGRATION_LIFECYCLE_CONFLICT")


@dataclass(frozen=True, slots=True)
class OnlyIntegrationCommandResult:
    receipt: OnlyProductCommandReceipt
    replayed: bool


@dataclass(frozen=True, slots=True)
class OnlyIntegrationSecretStatus:
    field_id: str
    configured: bool
    generation: int | None


class OnlyIntegrationTypeCatalogReader(Protocol):
    def require(self, type_id: str) -> OnlyIntegrationTypeDescriptorV1: ...


class OnlyIntegrationProductStore(Protocol):
    def load_integration(self, integration_id: OnlyIntegrationId) -> OnlyIntegration: ...

    def load_draft(self, integration_id: OnlyIntegrationId) -> OnlyIntegrationDraft: ...

    def replay_command(
        self,
        admission: OnlyProductCommandAdmissionV1,
        integration_id: OnlyIntegrationId,
        outcome_kind: OnlyProductCommandOutcomeKind,
    ) -> OnlyIntegrationCommandResult | None: ...

    def create_integration_with_receipt(
        self,
        admission: OnlyProductCommandAdmissionV1,
        integration_id: OnlyIntegrationId,
        descriptor: OnlyIntegrationTypeDescriptorV1,
        display_name: str,
    ) -> OnlyIntegrationCommandResult: ...

    def update_draft_with_receipt(
        self,
        admission: OnlyProductCommandAdmissionV1,
        integration_id: OnlyIntegrationId,
        expected_draft_version: int,
        descriptor: OnlyIntegrationTypeDescriptorV1,
        public_configuration: Mapping[str, object],
        probe_configuration: Mapping[str, object] | None,
    ) -> OnlyIntegrationCommandResult: ...

    def set_secret_with_receipt(
        self,
        admission: OnlyProductCommandAdmissionV1,
        integration_id: OnlyIntegrationId,
        expected_draft_version: int,
        descriptor: OnlyIntegrationTypeDescriptorV1,
        field_id: str,
        plaintext_secret: str,
    ) -> OnlyIntegrationCommandResult: ...

    def clear_secret_with_receipt(
        self,
        admission: OnlyProductCommandAdmissionV1,
        integration_id: OnlyIntegrationId,
        expected_draft_version: int,
        descriptor: OnlyIntegrationTypeDescriptorV1,
        field_id: str,
    ) -> OnlyIntegrationCommandResult: ...

    def reset_draft_contract_with_receipt(
        self,
        admission: OnlyProductCommandAdmissionV1,
        integration_id: OnlyIntegrationId,
        expected_draft_version: int,
        descriptor: OnlyIntegrationTypeDescriptorV1,
    ) -> OnlyIntegrationCommandResult: ...

    def publish_with_receipt(
        self,
        admission: OnlyProductCommandAdmissionV1,
        integration_id: OnlyIntegrationId,
        expected_draft_version: int,
        descriptor: OnlyIntegrationTypeDescriptorV1,
    ) -> OnlyIntegrationCommandResult: ...

    def set_lifecycle_with_receipt(
        self,
        admission: OnlyProductCommandAdmissionV1,
        integration_id: OnlyIntegrationId,
        expected_lifecycle_state: OnlyIntegrationLifecycleState,
        lifecycle_state: OnlyIntegrationLifecycleState,
    ) -> OnlyIntegrationCommandResult: ...


class OnlyIntegrationQueryStore(Protocol):
    def list_integrations(
        self,
        type_id: str | None,
        lifecycle_state: OnlyIntegrationLifecycleState | None,
    ) -> tuple[OnlyIntegration, ...]: ...

    def load_integration(self, integration_id: OnlyIntegrationId) -> OnlyIntegration: ...

    def load_draft(self, integration_id: OnlyIntegrationId) -> OnlyIntegrationDraft: ...

    def load_draft_secret_bindings(
        self, integration_id: OnlyIntegrationId
    ) -> tuple[OnlyIntegrationSecretBinding, ...]: ...

    def load_revision(self, revision_fingerprint: str) -> OnlyIntegrationRevision: ...

    def list_revision_history(self, integration_id: OnlyIntegrationId) -> tuple[OnlyIntegrationRevision, ...]: ...

    def load_revision_secret_bindings(self, revision_fingerprint: str) -> tuple[OnlyIntegrationSecretBinding, ...]: ...


class OnlyIntegrationCommandService:
    """The sole Product/Application authority for Integration mutations."""

    def __init__(
        self,
        catalog: OnlyIntegrationTypeCatalogReader,
        store: OnlyIntegrationProductStore,
        master_key: bytes,
    ) -> None:
        if len(master_key) != 32:
            raise ValueError("CREDENTIAL_MASTER_KEY_INVALID")
        self._catalog = catalog
        self._store = store
        self._master_key = bytes(master_key)
        self._resolver = OnlyIntegrationConfigurationResolver()

    def create_integration(self, command: OnlyCreateIntegration) -> OnlyIntegrationCommandResult:
        admission = _admission(
            command.command_id,
            OnlyProductCommandKind.CREATE_INTEGRATION,
            {
                "integration_id": command.integration_id.value,
                "type_id": command.type_id,
                "display_name": command.display_name,
            },
        )
        replay = self._store.replay_command(
            admission, command.integration_id, OnlyProductCommandOutcomeKind.INTEGRATION
        )
        if replay is not None:
            return replay
        descriptor = self._require_descriptor(command.type_id)
        return self._store.create_integration_with_receipt(
            admission, command.integration_id, descriptor, command.display_name
        )

    def update_integration_draft(self, command: OnlyUpdateIntegrationDraft) -> OnlyIntegrationCommandResult:
        admission = _admission(
            command.command_id,
            OnlyProductCommandKind.UPDATE_INTEGRATION_DRAFT,
            {
                "integration_id": command.integration_id.value,
                "expected_draft_version": command.expected_draft_version,
                "public_configuration_json": _command_document_identity_json(command.public_configuration),
                "probe_configuration_json": _command_document_identity_json(command.probe_configuration),
            },
        )
        replay = self._store.replay_command(
            admission, command.integration_id, OnlyProductCommandOutcomeKind.INTEGRATION
        )
        if replay is not None:
            return replay
        descriptor = self._current_descriptor(command.integration_id)
        public, probe = self._resolver.validate_draft(
            descriptor, command.public_configuration, command.probe_configuration
        )
        self._validate_provider_configuration(descriptor, public)
        return self._store.update_draft_with_receipt(
            admission,
            command.integration_id,
            command.expected_draft_version,
            descriptor,
            public,
            probe,
        )

    def set_integration_secret(self, command: OnlySetIntegrationSecret) -> OnlyIntegrationCommandResult:
        commitment = only_integration_secret_commitment(
            self._master_key, command.integration_id, command.field_id, command.plaintext_secret
        )
        admission = _admission(
            command.command_id,
            OnlyProductCommandKind.SET_INTEGRATION_SECRET,
            {
                "integration_id": command.integration_id.value,
                "expected_draft_version": command.expected_draft_version,
                "field_id": command.field_id,
                "secret_commitment": commitment,
            },
        )
        replay = self._store.replay_command(
            admission, command.integration_id, OnlyProductCommandOutcomeKind.INTEGRATION
        )
        if replay is not None:
            return replay
        descriptor = self._current_descriptor(command.integration_id)
        _require_secret_field(descriptor, command.field_id)
        return self._store.set_secret_with_receipt(
            admission,
            command.integration_id,
            command.expected_draft_version,
            descriptor,
            command.field_id,
            command.plaintext_secret,
        )

    def clear_integration_secret(self, command: OnlyClearIntegrationSecret) -> OnlyIntegrationCommandResult:
        admission = _admission(
            command.command_id,
            OnlyProductCommandKind.CLEAR_INTEGRATION_SECRET,
            {
                "integration_id": command.integration_id.value,
                "expected_draft_version": command.expected_draft_version,
                "field_id": command.field_id,
            },
        )
        replay = self._store.replay_command(
            admission, command.integration_id, OnlyProductCommandOutcomeKind.INTEGRATION
        )
        if replay is not None:
            return replay
        descriptor = self._current_descriptor(command.integration_id)
        _require_secret_field(descriptor, command.field_id)
        return self._store.clear_secret_with_receipt(
            admission, command.integration_id, command.expected_draft_version, descriptor, command.field_id
        )

    def reset_integration_draft_contract(
        self, command: OnlyResetIntegrationDraftContract
    ) -> OnlyIntegrationCommandResult:
        admission = _admission(
            command.command_id,
            OnlyProductCommandKind.RESET_INTEGRATION_DRAFT_CONTRACT,
            {
                "integration_id": command.integration_id.value,
                "expected_draft_version": command.expected_draft_version,
            },
        )
        replay = self._store.replay_command(
            admission, command.integration_id, OnlyProductCommandOutcomeKind.INTEGRATION
        )
        if replay is not None:
            return replay
        descriptor = self._current_descriptor(command.integration_id, verify_pinned=False)
        return self._store.reset_draft_contract_with_receipt(
            admission, command.integration_id, command.expected_draft_version, descriptor
        )

    def publish_integration_revision(self, command: OnlyPublishIntegrationRevision) -> OnlyIntegrationCommandResult:
        admission = _admission(
            command.command_id,
            OnlyProductCommandKind.PUBLISH_INTEGRATION_REVISION,
            {
                "integration_id": command.integration_id.value,
                "expected_draft_version": command.expected_draft_version,
            },
        )
        replay = self._store.replay_command(
            admission, command.integration_id, OnlyProductCommandOutcomeKind.INTEGRATION_REVISION
        )
        if replay is not None:
            return replay
        descriptor = self._current_descriptor(command.integration_id)
        draft = self._store.load_draft(command.integration_id)
        public = dict(draft.public_configuration_document)
        for contract in descriptor.configuration_contract.fields:
            if not contract.secret and contract.field_id not in public and contract.default is not None:
                public[contract.field_id] = contract.default
        self._validate_provider_configuration(descriptor, public)
        return self._store.publish_with_receipt(
            admission, command.integration_id, command.expected_draft_version, descriptor
        )

    def set_integration_lifecycle(self, command: OnlySetIntegrationLifecycle) -> OnlyIntegrationCommandResult:
        admission = _admission(
            command.command_id,
            OnlyProductCommandKind.SET_INTEGRATION_LIFECYCLE,
            {
                "integration_id": command.integration_id.value,
                "expected_lifecycle_state": command.expected_lifecycle_state.value,
                "lifecycle_state": command.lifecycle_state.value,
            },
        )
        return self._store.set_lifecycle_with_receipt(
            admission,
            command.integration_id,
            command.expected_lifecycle_state,
            command.lifecycle_state,
        )

    def _current_descriptor(
        self, integration_id: OnlyIntegrationId, *, verify_pinned: bool = True
    ) -> OnlyIntegrationTypeDescriptorV1:
        integration = self._store.load_integration(integration_id)
        if integration.lifecycle_state is OnlyIntegrationLifecycleState.ARCHIVED:
            raise OnlyIntegrationError("INTEGRATION_ARCHIVED")
        descriptor = self._require_descriptor(integration.type_id)
        if verify_pinned:
            draft = self._store.load_draft(integration_id)
            if draft.type_descriptor_fingerprint != descriptor.fingerprint:
                raise OnlyIntegrationError("INTEGRATION_TYPE_CHANGED")
        return descriptor

    def _require_descriptor(self, type_id: str) -> OnlyIntegrationTypeDescriptorV1:
        try:
            return self._catalog.require(type_id)
        except LookupError as exc:
            raise OnlyIntegrationError("INTEGRATION_TYPE_UNAVAILABLE") from exc

    def _validate_provider_configuration(
        self, descriptor: OnlyIntegrationTypeDescriptorV1, public_configuration: Mapping[str, object]
    ) -> None:
        validate = getattr(self._catalog, "validate_public_configuration", None)
        if not callable(validate):
            return
        try:
            validate(descriptor.type_id.value, dict(public_configuration))
        except ValueError as exc:
            raise OnlyIntegrationError("INTEGRATION_CONFIGURATION_INVALID", str(exc)) from exc


class OnlyIntegrationQueryService:
    """Stable Product reads that never require an installed Integration Type."""

    def __init__(self, store: OnlyIntegrationQueryStore) -> None:
        self._store = store

    def get_integration(self, integration_id: OnlyIntegrationId) -> OnlyIntegration:
        return self._store.load_integration(integration_id)

    def list_integrations(
        self,
        *,
        type_id: str | None = None,
        lifecycle_state: OnlyIntegrationLifecycleState | None = None,
    ) -> tuple[OnlyIntegration, ...]:
        return tuple(
            sorted(
                self._store.list_integrations(type_id, lifecycle_state),
                key=lambda item: (item.created_at, item.integration_id.value),
            )
        )

    def get_draft(self, integration_id: OnlyIntegrationId) -> OnlyIntegrationDraft:
        return self._store.load_draft(integration_id)

    def get_draft_secret_status(self, integration_id: OnlyIntegrationId) -> tuple[OnlyIntegrationSecretStatus, ...]:
        return tuple(
            OnlyIntegrationSecretStatus(item.field_id, True, item.credential_generation)
            for item in self._store.load_draft_secret_bindings(integration_id)
        )

    def get_current_revision(self, integration_id: OnlyIntegrationId) -> OnlyIntegrationRevision | None:
        fingerprint = self._store.load_integration(integration_id).current_revision_fingerprint
        return None if fingerprint is None else self._store.load_revision(fingerprint)

    def get_revision(self, revision_fingerprint: str) -> OnlyIntegrationRevision:
        return self._store.load_revision(revision_fingerprint)

    def get_revision_secret_status(self, revision_fingerprint: str) -> tuple[OnlyIntegrationSecretStatus, ...]:
        return tuple(
            OnlyIntegrationSecretStatus(item.field_id, True, item.credential_generation)
            for item in self._store.load_revision_secret_bindings(revision_fingerprint)
        )

    def list_revision_history(self, integration_id: OnlyIntegrationId) -> tuple[OnlyIntegrationRevision, ...]:
        return self._store.list_revision_history(integration_id)


@dataclass(frozen=True, slots=True)
class OnlyIntegrationResolvedPublication:
    integration_id: OnlyIntegrationId
    type_id: str
    type_descriptor_fingerprint: str
    type_descriptor_document: Mapping[str, object]
    public_configuration: Mapping[str, object]
    configuration_fingerprint: str
    probe_configuration: Mapping[str, object] | None
    probe_configuration_fingerprint: str | None
    secret_bindings: tuple[OnlyIntegrationSecretBinding, ...]
    secret_binding_fingerprint: str
    runtime_configuration_fingerprint: str

    def to_revision(self, revision_sequence: int, created_at: datetime) -> OnlyIntegrationRevision:
        return OnlyIntegrationRevision.from_resolved(
            integration_id=self.integration_id,
            revision_sequence=revision_sequence,
            type_id=self.type_id,
            type_descriptor_fingerprint=self.type_descriptor_fingerprint,
            type_descriptor_document=self.type_descriptor_document,
            configuration_document=self.public_configuration,
            probe_configuration_document=self.probe_configuration,
            secret_bindings=self.secret_bindings,
            created_at=created_at,
        )


class OnlyIntegrationConfigurationResolver:
    """Validate mutable Draft input and resolve one canonical publication."""

    def validate_draft(
        self,
        descriptor: OnlyIntegrationTypeDescriptorV1,
        public_configuration: Mapping[str, object],
        probe_configuration: Mapping[str, object] | None,
    ) -> tuple[Mapping[str, object], Mapping[str, object] | None]:
        fields = {item.field_id: item for item in descriptor.configuration_contract.fields}
        unknown = public_configuration.keys() - fields.keys()
        if unknown:
            raise OnlyIntegrationError("INTEGRATION_CONFIGURATION_INVALID", "unknown public field")
        normalized: dict[str, object] = {}
        for field_id, value in public_configuration.items():
            contract = fields[field_id]
            if contract.secret:
                raise OnlyIntegrationError("INTEGRATION_CONFIGURATION_INVALID", "secret field is not public")
            normalized[field_id] = _normalize_value(contract, value)
        return _freeze_document(normalized), _validate_probe(descriptor, probe_configuration, publish=False)

    def resolve_publication(
        self,
        integration_id: OnlyIntegrationId,
        descriptor: OnlyIntegrationTypeDescriptorV1,
        public_configuration: Mapping[str, object],
        probe_configuration: Mapping[str, object] | None,
        secret_bindings: tuple[OnlyIntegrationSecretBinding, ...],
    ) -> OnlyIntegrationResolvedPublication:
        public, _ = self.validate_draft(descriptor, public_configuration, probe_configuration)
        resolved = dict(public)
        secret_fields: dict[str, OnlyIntegrationConfigurationFieldV1] = {}
        for contract in descriptor.configuration_contract.fields:
            if contract.secret:
                secret_fields[contract.field_id] = contract
            elif contract.field_id not in resolved:
                if contract.default is not None:
                    resolved[contract.field_id] = _normalize_value(contract, contract.default)
                elif contract.required:
                    raise OnlyIntegrationError(
                        "INTEGRATION_CONFIGURATION_INCOMPLETE",
                        f"required field is missing: {contract.field_id}",
                    )
        binding_fields = [item.field_id for item in secret_bindings]
        if len(binding_fields) != len(set(binding_fields)) or set(binding_fields) - secret_fields.keys():
            raise OnlyIntegrationError("INTEGRATION_SECRET_BINDING_INVALID")
        missing_secrets = {
            field_id
            for field_id, contract in secret_fields.items()
            if contract.required and field_id not in binding_fields
        }
        if missing_secrets:
            raise OnlyIntegrationError("INTEGRATION_SECRET_REQUIRED", "required secret binding is missing")
        canonical_public = _freeze_document(resolved)
        canonical_probe = _validate_probe(descriptor, probe_configuration, publish=True)
        canonical_bindings = tuple(sorted(secret_bindings, key=lambda item: item.field_id))
        binding_fingerprint = only_integration_secret_binding_fingerprint(canonical_bindings)
        runtime_fingerprint = only_integration_runtime_configuration_fingerprint(
            descriptor.type_id.value,
            descriptor.fingerprint,
            canonical_public,
            binding_fingerprint,
        )
        probe_fingerprint = None if canonical_probe is None else only_canonical_fingerprint(canonical_probe)
        return OnlyIntegrationResolvedPublication(
            integration_id,
            descriptor.type_id.value,
            descriptor.fingerprint,
            _freeze_document(descriptor.to_dict(include_fingerprint=False)),
            canonical_public,
            only_canonical_fingerprint(canonical_public),
            canonical_probe,
            probe_fingerprint,
            canonical_bindings,
            binding_fingerprint,
            runtime_fingerprint,
        )


def only_integration_secret_commitment(
    master_key: bytes,
    integration_id: OnlyIntegrationId,
    field_id: str,
    plaintext_secret: str,
) -> str:
    """Return a domain-separated keyed commitment without persisting plaintext."""

    if len(master_key) != 32 or not field_id or not plaintext_secret:
        raise OnlyIntegrationError("INTEGRATION_SECRET_FIELD_INVALID")
    commitment_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_COMMITMENT_INFO,
    ).derive(master_key)
    context = only_canonical_json({"integration_id": integration_id.value, "field_id": field_id}).encode("utf-8")
    return hmac.new(commitment_key, context + b"\x00" + plaintext_secret.encode("utf-8"), hashlib.sha256).hexdigest()


def _normalize_value(contract: OnlyIntegrationConfigurationFieldV1, value: object) -> object:
    kind = contract.value_kind
    valid = True
    if kind in {OnlyIntegrationValueKind.STRING, OnlyIntegrationValueKind.PATH}:
        valid = isinstance(value, str)
        normalized = value
    elif kind is OnlyIntegrationValueKind.ENUM:
        valid = isinstance(value, str) and value in contract.enum_values
        normalized = value
    elif kind is OnlyIntegrationValueKind.BOOLEAN:
        valid = isinstance(value, bool)
        normalized = value
    elif kind is OnlyIntegrationValueKind.INTEGER:
        valid = isinstance(value, int) and not isinstance(value, bool)
        normalized = value
    elif kind in {OnlyIntegrationValueKind.NUMBER, OnlyIntegrationValueKind.DURATION}:
        if isinstance(value, bool) or not isinstance(value, int | float):
            valid = False
            normalized = value
        else:
            try:
                numeric = float(value)
            except OverflowError:
                valid = False
                normalized = value
            else:
                valid = math.isfinite(numeric)
                normalized = int(value) if numeric.is_integer() else value
    elif kind is OnlyIntegrationValueKind.STRING_INTEGER_MAP:
        valid = isinstance(value, Mapping) and all(
            isinstance(key, str) and bool(key) and isinstance(item, int) and not isinstance(item, bool)
            for key, item in cast(Mapping[object, object], value).items()
        )
        normalized = dict(sorted(cast(Mapping[str, int], value).items())) if valid else value
    else:  # pragma: no cover - exhaustive enum guard
        valid = False
        normalized = value
    if not valid:
        raise OnlyIntegrationError("INTEGRATION_CONFIGURATION_INVALID", f"invalid field: {contract.field_id}")
    if kind in {
        OnlyIntegrationValueKind.INTEGER,
        OnlyIntegrationValueKind.NUMBER,
        OnlyIntegrationValueKind.DURATION,
    }:
        numeric = cast(int | float, normalized)
        if contract.minimum is not None and (
            numeric < contract.minimum or (contract.exclusive_minimum and numeric == contract.minimum)
        ):
            raise OnlyIntegrationError("INTEGRATION_CONFIGURATION_INVALID", f"field below minimum: {contract.field_id}")
        if contract.maximum is not None and numeric > contract.maximum:
            raise OnlyIntegrationError("INTEGRATION_CONFIGURATION_INVALID", f"field above maximum: {contract.field_id}")
    return normalized


def _validate_probe(
    descriptor: OnlyIntegrationTypeDescriptorV1,
    value: Mapping[str, object] | None,
    *,
    publish: bool,
) -> Mapping[str, object] | None:
    contract = descriptor.probe_contract
    document = {} if value is None else dict(value)
    if contract is None:
        if document:
            raise OnlyIntegrationError("INTEGRATION_PROBE_CONFIGURATION_INVALID")
        return None
    if contract.probe_mode is not OnlyIntegrationProbeMode.DEFAULT_INSTRUMENT:
        raise OnlyIntegrationError("INTEGRATION_PROBE_CONFIGURATION_INVALID")
    if document.keys() - {"instrument"}:
        raise OnlyIntegrationError("INTEGRATION_PROBE_CONFIGURATION_INVALID")
    instrument = document.get("instrument")
    if instrument is None:
        if not publish:
            return None if value is None else MappingProxyType({})
        instrument = contract.default_probe_instrument
    if not isinstance(instrument, str) or not instrument.strip():
        raise OnlyIntegrationError("INTEGRATION_PROBE_CONFIGURATION_INVALID")
    if not contract.user_selectable_probe_instrument and instrument != contract.default_probe_instrument:
        raise OnlyIntegrationError("INTEGRATION_PROBE_CONFIGURATION_INVALID")
    return MappingProxyType({"instrument": instrument})


def _freeze_document(value: Mapping[str, object]) -> Mapping[str, object]:
    return cast(Mapping[str, object], _freeze_json(value))


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise OnlyIntegrationError("INTEGRATION_CONFIGURATION_INVALID", "document key is not a string")
        return MappingProxyType({key: _freeze_json(value[key]) for key in sorted(value)})
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


def _command_document_identity(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _command_document_identity(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_command_document_identity(item) for item in value)
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return value


def _command_document_identity_json(value: object) -> str:
    try:
        return json.dumps(
            _command_document_identity(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise OnlyIntegrationError("INTEGRATION_CONFIGURATION_INVALID") from exc


def _expected_version(value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise OnlyIntegrationError("INTEGRATION_DRAFT_VERSION_CONFLICT")


def _admission(
    command_id: OnlyProductCommandId,
    command_kind: OnlyProductCommandKind,
    payload: object,
) -> OnlyProductCommandAdmissionV1:
    return OnlyProductCommandAdmissionV1(command_id, command_kind, only_product_command_fingerprint(payload))


def _require_secret_field(descriptor: OnlyIntegrationTypeDescriptorV1, field_id: str) -> None:
    field_contract = next(
        (item for item in descriptor.configuration_contract.fields if item.field_id == field_id),
        None,
    )
    if field_contract is None or not field_contract.secret:
        raise OnlyIntegrationError("INTEGRATION_SECRET_FIELD_INVALID")


__all__ = [name for name in globals() if name.startswith(("Only", "only_"))]
