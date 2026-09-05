"""Stable identities for immutable distribution and executable runtime generations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.distribution import (
    OnlyArtifactAssetIdentity as OnlyArtifactAssetIdentity,
)
from onlyalpha.distribution import (
    OnlyArtifactCalculationImplementation as OnlyArtifactCalculationImplementation,
)
from onlyalpha.distribution import (
    OnlyArtifactSourceProvenanceAuthority as OnlyArtifactSourceProvenanceAuthority,
)
from onlyalpha.distribution import (
    OnlyDistributionArtifactManifest as OnlyDistributionArtifactManifest,
)
from onlyalpha.distribution import (
    OnlyDistributionArtifactRole as OnlyDistributionArtifactRole,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,255}$")


@dataclass(frozen=True, order=True, slots=True)
class OnlyCoreExecutionIdentity:
    distribution_name: str
    distribution_version: str
    artifact_sha256: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not _valid_identity(self.distribution_name):
            raise ValueError("RUNTIME_GENERATION_CORE_IDENTITY_INVALID")
        if not _valid_identity(self.distribution_version) or _SHA256.fullmatch(self.artifact_sha256) is None:
            raise ValueError("RUNTIME_GENERATION_CORE_IDENTITY_INVALID")

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "distribution_name": self.distribution_name,
            "distribution_version": self.distribution_version,
            "artifact_sha256": self.artifact_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyCoreExecutionIdentity:
        _exact(payload, {"schema_version", "distribution_name", "distribution_version", "artifact_sha256"})
        return cls(
            _string(payload, "distribution_name"),
            _string(payload, "distribution_version"),
            _string(payload, "artifact_sha256"),
            _integer(payload, "schema_version"),
        )


@dataclass(frozen=True, order=True, slots=True)
class OnlyRuntimeProviderBinding:
    provider_id: str
    provider_version: str
    provider_content_fingerprint: str
    artifact_sha256: str

    def __post_init__(self) -> None:
        if not _valid_identity(self.provider_id) or not _valid_identity(self.provider_version):
            raise ValueError("RUNTIME_GENERATION_PROVIDER_MISMATCH")
        _sha(self.provider_content_fingerprint, "RUNTIME_GENERATION_PROVIDER_MISMATCH")
        _sha(self.artifact_sha256, "RUNTIME_GENERATION_PROVIDER_MISMATCH")

    def to_dict(self) -> dict[str, str]:
        return {
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "provider_content_fingerprint": self.provider_content_fingerprint,
            "artifact_sha256": self.artifact_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyRuntimeProviderBinding:
        fields = ("provider_id", "provider_version", "provider_content_fingerprint", "artifact_sha256")
        _exact(payload, set(fields))
        return cls(*(_string(payload, key) for key in fields))


@dataclass(frozen=True, slots=True)
class OnlyRuntimeGenerationManifest:
    core_execution: OnlyCoreExecutionIdentity
    artifact_manifest_fingerprints: tuple[str, ...]
    artifact_sha256s: tuple[str, ...]
    providers: tuple[OnlyRuntimeProviderBinding, ...]
    catalog_generation_fingerprint: str
    implementations: tuple[OnlyArtifactCalculationImplementation, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not isinstance(self.core_execution, OnlyCoreExecutionIdentity):
            raise ValueError("RUNTIME_GENERATION_MANIFEST_INVALID")
        manifests = tuple(sorted(self.artifact_manifest_fingerprints))
        artifacts = tuple(sorted(self.artifact_sha256s))
        providers = tuple(sorted(self.providers))
        implementations = tuple(sorted(self.implementations))
        for values in (manifests, artifacts):
            if not values or len(values) != len(set(values)):
                raise ValueError("RUNTIME_GENERATION_MANIFEST_INVALID")
            for value in values:
                _sha(value, "RUNTIME_GENERATION_MANIFEST_INVALID")
        if len(manifests) != len(artifacts) or self.core_execution.artifact_sha256 not in artifacts:
            raise ValueError("RUNTIME_GENERATION_MANIFEST_INVALID")
        _sha(self.catalog_generation_fingerprint, "RUNTIME_GENERATION_CATALOG_MISMATCH")
        if not providers or len(providers) != len(set(providers)):
            raise ValueError("RUNTIME_GENERATION_PROVIDER_MISMATCH")
        if any(provider.artifact_sha256 not in artifacts for provider in providers):
            raise ValueError("RUNTIME_GENERATION_PROVIDER_MISMATCH")
        if len(implementations) != len(set(implementations)):
            raise ValueError("RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH")
        object.__setattr__(self, "artifact_manifest_fingerprints", manifests)
        object.__setattr__(self, "artifact_sha256s", artifacts)
        object.__setattr__(self, "providers", providers)
        object.__setattr__(self, "implementations", implementations)

    @property
    def runtime_generation_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "core_execution": self.core_execution.to_dict(),
            "artifact_manifest_fingerprints": list(self.artifact_manifest_fingerprints),
            "artifact_sha256s": list(self.artifact_sha256s),
            "providers": [item.to_dict() for item in self.providers],
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "implementations": [item.to_dict() for item in self.implementations],
        }
        if include_fingerprint:
            result["runtime_generation_fingerprint"] = self.runtime_generation_fingerprint
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyRuntimeGenerationManifest:
        expected = {
            "schema_version",
            "core_execution",
            "artifact_manifest_fingerprints",
            "artifact_sha256s",
            "providers",
            "catalog_generation_fingerprint",
            "implementations",
            "runtime_generation_fingerprint",
        }
        _exact(payload, expected)
        result = cls(
            OnlyCoreExecutionIdentity.from_dict(_mapping(payload, "core_execution")),
            _string_list(payload, "artifact_manifest_fingerprints"),
            _string_list(payload, "artifact_sha256s"),
            tuple(OnlyRuntimeProviderBinding.from_dict(item) for item in _mapping_list(payload, "providers")),
            _string(payload, "catalog_generation_fingerprint"),
            tuple(
                OnlyArtifactCalculationImplementation.from_dict(item)
                for item in _mapping_list(payload, "implementations")
            ),
            _integer(payload, "schema_version"),
        )
        if _string(payload, "runtime_generation_fingerprint") != result.runtime_generation_fingerprint:
            raise ValueError("RUNTIME_GENERATION_MANIFEST_MISMATCH")
        return result


@dataclass(frozen=True, slots=True)
class OnlyRuntimeGenerationValidationEvidence:
    """Immutable proof that one exact generation passed clean executable validation."""

    runtime_generation_fingerprint: str
    core_execution_fingerprint: str
    artifact_manifest_fingerprints: tuple[str, ...]
    artifact_sha256s: tuple[str, ...]
    providers: tuple[OnlyRuntimeProviderBinding, ...]
    catalog_generation_fingerprint: str
    implementations: tuple[OnlyArtifactCalculationImplementation, ...]
    validation_contract_version: str = "ONLYALPHA_RUNTIME_GENERATION_VALIDATION@1"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.validation_contract_version != "ONLYALPHA_RUNTIME_GENERATION_VALIDATION@1":
            raise ValueError("RUNTIME_GENERATION_VALIDATION_EVIDENCE_INVALID")
        for value in (
            self.runtime_generation_fingerprint,
            self.core_execution_fingerprint,
            self.catalog_generation_fingerprint,
            *self.artifact_manifest_fingerprints,
            *self.artifact_sha256s,
        ):
            _sha(value, "RUNTIME_GENERATION_VALIDATION_EVIDENCE_INVALID")
        if self.artifact_manifest_fingerprints != tuple(sorted(set(self.artifact_manifest_fingerprints))):
            raise ValueError("RUNTIME_GENERATION_VALIDATION_EVIDENCE_INVALID")
        if self.artifact_sha256s != tuple(sorted(set(self.artifact_sha256s))):
            raise ValueError("RUNTIME_GENERATION_VALIDATION_EVIDENCE_INVALID")
        if self.providers != tuple(sorted(set(self.providers))):
            raise ValueError("RUNTIME_GENERATION_VALIDATION_EVIDENCE_INVALID")
        if self.implementations != tuple(sorted(set(self.implementations))):
            raise ValueError("RUNTIME_GENERATION_VALIDATION_EVIDENCE_INVALID")

    @classmethod
    def from_manifest(cls, manifest: OnlyRuntimeGenerationManifest) -> OnlyRuntimeGenerationValidationEvidence:
        return cls(
            runtime_generation_fingerprint=manifest.runtime_generation_fingerprint,
            core_execution_fingerprint=manifest.core_execution.fingerprint,
            artifact_manifest_fingerprints=manifest.artifact_manifest_fingerprints,
            artifact_sha256s=manifest.artifact_sha256s,
            providers=manifest.providers,
            catalog_generation_fingerprint=manifest.catalog_generation_fingerprint,
            implementations=manifest.implementations,
        )

    def verifies(self, manifest: OnlyRuntimeGenerationManifest) -> bool:
        return self == type(self).from_manifest(manifest)

    @property
    def validation_evidence_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "validation_contract_version": self.validation_contract_version,
            "runtime_generation_fingerprint": self.runtime_generation_fingerprint,
            "core_execution_fingerprint": self.core_execution_fingerprint,
            "artifact_manifest_fingerprints": list(self.artifact_manifest_fingerprints),
            "artifact_sha256s": list(self.artifact_sha256s),
            "providers": [item.to_dict() for item in self.providers],
            "catalog_generation_fingerprint": self.catalog_generation_fingerprint,
            "implementations": [item.to_dict() for item in self.implementations],
        }
        if include_fingerprint:
            result["validation_evidence_fingerprint"] = self.validation_evidence_fingerprint
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyRuntimeGenerationValidationEvidence:
        _exact(
            payload,
            {
                "schema_version",
                "validation_contract_version",
                "runtime_generation_fingerprint",
                "core_execution_fingerprint",
                "artifact_manifest_fingerprints",
                "artifact_sha256s",
                "providers",
                "catalog_generation_fingerprint",
                "implementations",
                "validation_evidence_fingerprint",
            },
        )
        result = cls(
            runtime_generation_fingerprint=_string(payload, "runtime_generation_fingerprint"),
            core_execution_fingerprint=_string(payload, "core_execution_fingerprint"),
            artifact_manifest_fingerprints=_string_list(payload, "artifact_manifest_fingerprints"),
            artifact_sha256s=_string_list(payload, "artifact_sha256s"),
            providers=tuple(OnlyRuntimeProviderBinding.from_dict(item) for item in _mapping_list(payload, "providers")),
            catalog_generation_fingerprint=_string(payload, "catalog_generation_fingerprint"),
            implementations=tuple(
                OnlyArtifactCalculationImplementation.from_dict(item)
                for item in _mapping_list(payload, "implementations")
            ),
            validation_contract_version=_string(payload, "validation_contract_version"),
            schema_version=_integer(payload, "schema_version"),
        )
        if _string(payload, "validation_evidence_fingerprint") != result.validation_evidence_fingerprint:
            raise ValueError("RUNTIME_GENERATION_VALIDATION_EVIDENCE_MISMATCH")
        return result


def _valid_identity(value: object) -> bool:
    return isinstance(value, str) and _IDENTITY.fullmatch(value) is not None


def _sha(value: object, code: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(code)
    return value


def _exact(payload: Mapping[str, object], expected: set[str]) -> None:
    if set(payload) != expected:
        raise ValueError("RUNTIME_GENERATION_MANIFEST_FIELDS_INVALID")


def _string(payload: Mapping[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise ValueError("RUNTIME_GENERATION_MANIFEST_FIELDS_INVALID")
    return value


def _integer(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("RUNTIME_GENERATION_MANIFEST_FIELDS_INVALID")
    return value


def _mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload[key]
    if not isinstance(value, Mapping) or any(not isinstance(name, str) for name in value):
        raise ValueError("RUNTIME_GENERATION_MANIFEST_FIELDS_INVALID")
    return cast(Mapping[str, object], value)


def _mapping_list(payload: Mapping[str, object], key: str) -> tuple[Mapping[str, object], ...]:
    value = payload[key]
    if not isinstance(value, list):
        raise ValueError("RUNTIME_GENERATION_MANIFEST_FIELDS_INVALID")
    return tuple(_mapping({"value": item}, "value") for item in value)


def _string_list(payload: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = payload[key]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("RUNTIME_GENERATION_MANIFEST_FIELDS_INVALID")
    return tuple(cast(list[str], value))


__all__ = [name for name in globals() if name.startswith("Only")]
