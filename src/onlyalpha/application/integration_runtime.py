"""Exact, provider-neutral Integration Revision runtime resolution."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, cast

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.plugin.integration import OnlyIntegrationCategory, OnlyIntegrationTypeDescriptorV1
from onlyalpha.plugin.integration_probe import OnlyIntegrationProbeStatus

from .integration_configuration import (
    OnlyIntegration,
    OnlyIntegrationError,
    OnlyIntegrationId,
    OnlyIntegrationLifecycleState,
    OnlyIntegrationRevision,
    OnlyIntegrationSecretBinding,
    only_integration_runtime_configuration_fingerprint,
    only_integration_secret_binding_fingerprint,
)

_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_BINDING_DOMAIN = "ONLYALPHA_INTEGRATION_RUNTIME_BINDING_V1"


class OnlyIntegrationRuntimeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class OnlyIntegrationRuntimeBindingV1:
    integration_id: OnlyIntegrationId
    revision_fingerprint: str
    type_id: str
    category: OnlyIntegrationCategory
    type_descriptor_fingerprint: str
    runtime_configuration_fingerprint: str
    runtime_generation_fingerprint: str | None = None
    schema_version: int = field(default=1, init=False)

    def __post_init__(self) -> None:
        fingerprints = (
            self.revision_fingerprint,
            self.type_descriptor_fingerprint,
            self.runtime_configuration_fingerprint,
        )
        if (
            not isinstance(self.integration_id, OnlyIntegrationId)
            or not self.type_id
            or not isinstance(self.category, OnlyIntegrationCategory)
            or any(_FINGERPRINT.fullmatch(value) is None for value in fingerprints)
            or (
                self.runtime_generation_fingerprint is not None
                and _FINGERPRINT.fullmatch(self.runtime_generation_fingerprint) is None
            )
        ):
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_BINDING_INVALID")

    @classmethod
    def from_revision(
        cls,
        revision: OnlyIntegrationRevision,
        category: OnlyIntegrationCategory,
        runtime_generation_fingerprint: str | None = None,
    ) -> OnlyIntegrationRuntimeBindingV1:
        return cls(
            revision.integration_id,
            revision.revision_fingerprint,
            revision.type_id,
            category,
            revision.type_descriptor_fingerprint,
            revision.runtime_configuration_fingerprint,
            runtime_generation_fingerprint,
        )

    @property
    def binding_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "integration_id": self.integration_id.value,
            "revision_fingerprint": self.revision_fingerprint,
            "type_id": self.type_id,
            "category": self.category.value,
            "type_descriptor_fingerprint": self.type_descriptor_fingerprint,
            "runtime_configuration_fingerprint": self.runtime_configuration_fingerprint,
            "runtime_generation_fingerprint": self.runtime_generation_fingerprint,
            "identity_domain": _BINDING_DOMAIN,
        }
        if include_fingerprint:
            payload["binding_fingerprint"] = self.binding_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyIntegrationRuntimeBindingV1:
        expected = {
            "schema_version",
            "integration_id",
            "revision_fingerprint",
            "type_id",
            "category",
            "type_descriptor_fingerprint",
            "runtime_configuration_fingerprint",
            "runtime_generation_fingerprint",
            "identity_domain",
            "binding_fingerprint",
        }
        try:
            if (
                set(payload) != expected
                or payload["schema_version"] != 1
                or payload["identity_domain"] != _BINDING_DOMAIN
            ):
                raise ValueError
            generation = payload["runtime_generation_fingerprint"]
            if generation is not None and not isinstance(generation, str):
                raise ValueError
            binding = cls(
                OnlyIntegrationId(cast(str, payload["integration_id"])),
                cast(str, payload["revision_fingerprint"]),
                cast(str, payload["type_id"]),
                OnlyIntegrationCategory(cast(str, payload["category"])),
                cast(str, payload["type_descriptor_fingerprint"]),
                cast(str, payload["runtime_configuration_fingerprint"]),
                generation,
            )
            if payload["binding_fingerprint"] != binding.binding_fingerprint:
                raise ValueError
            return binding
        except Exception:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_BINDING_INVALID") from None


@dataclass(frozen=True, slots=True)
class OnlyResolvedIntegrationSecrets:
    _values: Mapping[str, str] = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_values", MappingProxyType(dict(self._values)))

    def require(self, field_id: str) -> str:
        try:
            return self._values[field_id]
        except KeyError as exc:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_SECRET_UNAVAILABLE") from exc

    def as_mapping(self) -> Mapping[str, str]:
        return self._values


@dataclass(frozen=True, slots=True)
class OnlyResolvedIntegrationRuntimeConfiguration:
    binding: OnlyIntegrationRuntimeBindingV1
    type_descriptor: OnlyIntegrationTypeDescriptorV1
    public_configuration: Mapping[str, object]
    secrets: OnlyResolvedIntegrationSecrets = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_configuration", MappingProxyType(dict(self.public_configuration)))


class OnlyIntegrationRuntimeStateReader(Protocol):
    def load_integration(self, integration_id: OnlyIntegrationId) -> OnlyIntegration: ...

    def load_revision(self, revision_fingerprint: str) -> OnlyIntegrationRevision: ...

    def load_revision_secret_bindings(self, revision_fingerprint: str) -> tuple[OnlyIntegrationSecretBinding, ...]: ...


class OnlyIntegrationRuntimeCredentialReader(Protocol):
    def read_secret(self, credential_id: str, credential_generation: int) -> str: ...


class OnlyIntegrationRuntimeTypeCatalog(Protocol):
    def require(self, type_id: str) -> OnlyIntegrationTypeDescriptorV1: ...


class OnlyIntegrationRuntimeProbeAttempt(Protocol):
    @property
    def integration_id(self) -> OnlyIntegrationId: ...

    @property
    def revision_fingerprint(self) -> str: ...

    @property
    def runtime_configuration_fingerprint(self) -> str: ...

    @property
    def overall_status(self) -> OnlyIntegrationProbeStatus: ...


class OnlyIntegrationRuntimeProbeReader(Protocol):
    def latest_probe_attempt(
        self, integration_id: OnlyIntegrationId, revision_fingerprint: str
    ) -> OnlyIntegrationRuntimeProbeAttempt | None: ...


class OnlyIntegrationRuntimeGenerationReader(Protocol):
    def require_runtime_generation(self, runtime_generation_fingerprint: str) -> object: ...


class OnlyIntegrationRuntimeResolver:
    """The single authority for resolving exact Integration runtime bindings."""

    def __init__(
        self,
        state: OnlyIntegrationRuntimeStateReader,
        credentials: OnlyIntegrationRuntimeCredentialReader,
        catalog: OnlyIntegrationRuntimeTypeCatalog,
        *,
        probes: OnlyIntegrationRuntimeProbeReader | None = None,
        runtime_generations: OnlyIntegrationRuntimeGenerationReader | None = None,
    ) -> None:
        self._state = state
        self._credentials = credentials
        self._catalog = catalog
        self._probes = probes
        self._runtime_generations = runtime_generations

    def admit_new(
        self,
        integration_id: OnlyIntegrationId,
        revision_fingerprint: str,
        *,
        expected_category: OnlyIntegrationCategory,
        required_capabilities: tuple[str, ...] = (),
        require_current_revision: bool = False,
        require_ready_probe: bool = False,
        runtime_generation_fingerprint: str | None = None,
    ) -> OnlyResolvedIntegrationRuntimeConfiguration:
        integration = self._load_integration(integration_id)
        if integration.lifecycle_state is not OnlyIntegrationLifecycleState.ACTIVE:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_DISABLED")
        if require_current_revision and integration.current_revision_fingerprint != revision_fingerprint:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_BINDING_INVALID")
        revision = self._load_revision(revision_fingerprint)
        if revision.integration_id != integration_id or revision.type_id != integration.type_id:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_BINDING_INVALID")
        category = _stored_category(revision)
        resolved = self.resolve(
            OnlyIntegrationRuntimeBindingV1.from_revision(
                revision,
                category,
                runtime_generation_fingerprint,
            ),
            expected_category=expected_category,
            required_capabilities=required_capabilities,
        )
        if require_ready_probe:
            self._require_ready_probe(integration_id, revision)
        return resolved

    def admit_new_reference(
        self,
        integration_id: str,
        revision_fingerprint: str,
        *,
        expected_category: OnlyIntegrationCategory,
        required_capabilities: tuple[str, ...] = (),
        require_current_revision: bool = False,
        require_ready_probe: bool = False,
        runtime_generation_fingerprint: str | None = None,
    ) -> OnlyResolvedIntegrationRuntimeConfiguration:
        try:
            parsed_id = OnlyIntegrationId(integration_id)
        except Exception:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_BINDING_INVALID") from None
        return self.admit_new(
            parsed_id,
            revision_fingerprint,
            expected_category=expected_category,
            required_capabilities=required_capabilities,
            require_current_revision=require_current_revision,
            require_ready_probe=require_ready_probe,
            runtime_generation_fingerprint=runtime_generation_fingerprint,
        )

    def resolve(
        self,
        binding: OnlyIntegrationRuntimeBindingV1,
        *,
        expected_category: OnlyIntegrationCategory,
        required_capabilities: tuple[str, ...] = (),
    ) -> OnlyResolvedIntegrationRuntimeConfiguration:
        if not isinstance(binding, OnlyIntegrationRuntimeBindingV1):
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_BINDING_INVALID")
        integration = self._load_integration(binding.integration_id)
        revision = self._load_revision(binding.revision_fingerprint)
        if revision.integration_id != binding.integration_id:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_BINDING_INVALID")
        if revision.type_id != integration.type_id or binding.type_id != revision.type_id:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_BINDING_INVALID")
        if binding.category is not expected_category or _stored_category(revision) is not expected_category:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_CATEGORY_MISMATCH")
        try:
            require_compatible = getattr(self._catalog, "require_compatible", None)
            supports_compatibility = callable(require_compatible)
            if callable(require_compatible):
                descriptor = require_compatible(revision.type_id, revision.type_descriptor_fingerprint)
            else:
                descriptor = self._catalog.require(revision.type_id)
        except Exception:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_IMPLEMENTATION_UNAVAILABLE") from None
        if not set(required_capabilities).issubset(descriptor.capabilities):
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_CAPABILITY_MISMATCH")
        if binding.type_descriptor_fingerprint != revision.type_descriptor_fingerprint or (
            not supports_compatibility and descriptor.fingerprint != revision.type_descriptor_fingerprint
        ):
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_IMPLEMENTATION_MISMATCH")
        bindings = self._load_secret_bindings(revision.revision_fingerprint)
        expected_runtime_fingerprint = only_integration_runtime_configuration_fingerprint(
            revision.type_id,
            revision.type_descriptor_fingerprint,
            revision.configuration_document,
            only_integration_secret_binding_fingerprint(bindings),
        )
        if (
            expected_runtime_fingerprint != revision.runtime_configuration_fingerprint
            or binding.runtime_configuration_fingerprint != expected_runtime_fingerprint
        ):
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_CONFIGURATION_CORRUPT")
        secret_fields = {item.field_id: item for item in descriptor.configuration_contract.fields if item.secret}
        if len({item.field_id for item in bindings}) != len(bindings) or any(
            item.field_id not in secret_fields for item in bindings
        ):
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_BINDING_INVALID")
        if any(
            item.required and field_id not in {binding.field_id for binding in bindings}
            for field_id, item in secret_fields.items()
        ):
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_SECRET_UNAVAILABLE")
        secrets: dict[str, str] = {}
        try:
            for secret_binding in bindings:
                secrets[secret_binding.field_id] = self._credentials.read_secret(
                    secret_binding.credential_id,
                    secret_binding.credential_generation,
                )
        except Exception:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_SECRET_UNAVAILABLE") from None
        if binding.runtime_generation_fingerprint is not None:
            if self._runtime_generations is None:
                raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_IMPLEMENTATION_UNAVAILABLE")
            try:
                self._runtime_generations.require_runtime_generation(binding.runtime_generation_fingerprint)
            except Exception:
                raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_IMPLEMENTATION_UNAVAILABLE") from None
        return OnlyResolvedIntegrationRuntimeConfiguration(
            binding,
            descriptor,
            revision.configuration_document,
            OnlyResolvedIntegrationSecrets(secrets),
        )

    def _load_integration(self, integration_id: OnlyIntegrationId) -> OnlyIntegration:
        try:
            return self._state.load_integration(integration_id)
        except Exception as exc:
            if isinstance(exc, LookupError) or (
                isinstance(exc, OnlyIntegrationError) and exc.code == "INTEGRATION_NOT_FOUND"
            ):
                raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_REVISION_NOT_FOUND") from None
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_PERSISTENCE_UNAVAILABLE") from None

    def _load_revision(self, revision_fingerprint: str) -> OnlyIntegrationRevision:
        try:
            return self._state.load_revision(revision_fingerprint)
        except Exception as exc:
            if isinstance(exc, LookupError) or (
                isinstance(exc, OnlyIntegrationError) and exc.code == "INTEGRATION_REVISION_NOT_FOUND"
            ):
                raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_REVISION_NOT_FOUND") from None
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_PERSISTENCE_UNAVAILABLE") from None

    def _load_secret_bindings(self, revision_fingerprint: str) -> tuple[OnlyIntegrationSecretBinding, ...]:
        try:
            return self._state.load_revision_secret_bindings(revision_fingerprint)
        except Exception:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_PERSISTENCE_UNAVAILABLE") from None

    def _require_ready_probe(self, integration_id: OnlyIntegrationId, revision: OnlyIntegrationRevision) -> None:
        if self._probes is None:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_PROBE_REQUIRED")
        try:
            attempt = self._probes.latest_probe_attempt(integration_id, revision.revision_fingerprint)
        except Exception:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_PERSISTENCE_UNAVAILABLE") from None
        if attempt is None:
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_PROBE_REQUIRED")
        if (
            attempt.overall_status is not OnlyIntegrationProbeStatus.READY
            or attempt.integration_id != integration_id
            or attempt.revision_fingerprint != revision.revision_fingerprint
            or attempt.runtime_configuration_fingerprint != revision.runtime_configuration_fingerprint
        ):
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_PROBE_NOT_READY")


def _stored_category(revision: OnlyIntegrationRevision) -> OnlyIntegrationCategory:
    try:
        return OnlyIntegrationCategory(cast(str, revision.type_descriptor_document["category"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_CONFIGURATION_CORRUPT") from exc


__all__ = [name for name in globals() if name.startswith("Only")]
