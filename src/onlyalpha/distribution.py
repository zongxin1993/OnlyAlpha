"""Stable identities for immutable executable distribution artifacts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from onlyalpha.canonical import only_canonical_fingerprint

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,255}$")


class OnlyDistributionArtifactRole(StrEnum):
    CORE = "CORE"
    QUANT_ASSET = "QUANT_ASSET"
    CALCULATION = "CALCULATION"
    SUPPORT = "SUPPORT"


@dataclass(frozen=True, order=True, slots=True)
class OnlyArtifactAssetIdentity:
    kind: str
    asset_id: str
    semantic_version: str
    content_fingerprint: str

    def __post_init__(self) -> None:
        if not all(_valid_identity(value) for value in (self.kind, self.asset_id, self.semantic_version)):
            raise ValueError("RUNTIME_GENERATION_ASSET_IDENTITY_INVALID")
        _sha(self.content_fingerprint, "RUNTIME_GENERATION_ASSET_IDENTITY_INVALID")

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "asset_id": self.asset_id,
            "semantic_version": self.semantic_version,
            "content_fingerprint": self.content_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyArtifactAssetIdentity:
        fields = ("kind", "asset_id", "semantic_version", "content_fingerprint")
        _exact(payload, set(fields))
        return cls(*(_string(payload, key) for key in fields))


@dataclass(frozen=True, order=True, slots=True)
class OnlyArtifactCalculationImplementation:
    kind: str
    type_id: str
    semantic_version: str
    backend: str
    implementation_fingerprint: str

    def __post_init__(self) -> None:
        if not all(_valid_identity(value) for value in (self.kind, self.type_id, self.semantic_version, self.backend)):
            raise ValueError("RUNTIME_GENERATION_IMPLEMENTATION_IDENTITY_INVALID")
        _sha(self.implementation_fingerprint, "RUNTIME_GENERATION_IMPLEMENTATION_IDENTITY_INVALID")

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "type_id": self.type_id,
            "semantic_version": self.semantic_version,
            "backend": self.backend,
            "implementation_fingerprint": self.implementation_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyArtifactCalculationImplementation:
        fields = ("kind", "type_id", "semantic_version", "backend", "implementation_fingerprint")
        _exact(payload, set(fields))
        return cls(*(_string(payload, key) for key in fields))


@dataclass(frozen=True, slots=True)
class OnlyDistributionArtifactManifest:
    role: OnlyDistributionArtifactRole
    source_repository: str
    source_revision: str
    distribution_name: str
    distribution_version: str
    artifact_logical_name: str
    artifact_sha256: str
    artifact_size: int
    tested_core_execution_fingerprint: str | None = None
    provider_id: str | None = None
    provider_version: str | None = None
    provider_content_fingerprint: str | None = None
    assets: tuple[OnlyArtifactAssetIdentity, ...] = ()
    implementations: tuple[OnlyArtifactCalculationImplementation, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not isinstance(self.role, OnlyDistributionArtifactRole):
            raise ValueError("RUNTIME_GENERATION_ARTIFACT_MANIFEST_INVALID")
        if not all(
            _valid_identity(value)
            for value in (
                self.source_repository,
                self.source_revision,
                self.distribution_name,
                self.distribution_version,
                self.artifact_logical_name,
            )
        ):
            raise ValueError("RUNTIME_GENERATION_ARTIFACT_MANIFEST_INVALID")
        normalized = re.sub(r"[-_.]+", "_", self.distribution_name).lower()
        normalized_version = self.distribution_version.replace("-", "_").lower()
        if not self.artifact_logical_name.lower().startswith(f"{normalized}-{normalized_version}-"):
            raise ValueError("RUNTIME_GENERATION_ARTIFACT_MANIFEST_INVALID")
        if not self.artifact_logical_name.lower().endswith(".whl"):
            raise ValueError("RUNTIME_GENERATION_ARTIFACT_MANIFEST_INVALID")
        _sha(self.artifact_sha256, "RUNTIME_GENERATION_ARTIFACT_MANIFEST_INVALID")
        if isinstance(self.artifact_size, bool) or not isinstance(self.artifact_size, int) or self.artifact_size < 1:
            raise ValueError("RUNTIME_GENERATION_ARTIFACT_MANIFEST_INVALID")
        provider = (self.provider_id, self.provider_version, self.provider_content_fingerprint)
        if self.role is OnlyDistributionArtifactRole.QUANT_ASSET:
            if (
                any(value is None for value in provider)
                or self.tested_core_execution_fingerprint is None
                or not self.assets
            ):
                raise ValueError("RUNTIME_GENERATION_ARTIFACT_MANIFEST_INVALID")
        elif self.role is OnlyDistributionArtifactRole.CALCULATION:
            if any(value is not None for value in provider) or self.assets or not self.implementations:
                raise ValueError("RUNTIME_GENERATION_ARTIFACT_MANIFEST_INVALID")
            if self.tested_core_execution_fingerprint is None:
                raise ValueError("RUNTIME_GENERATION_ARTIFACT_MANIFEST_INVALID")
        elif any(value is not None for value in provider) or self.assets or self.implementations:
            raise ValueError("RUNTIME_GENERATION_ARTIFACT_MANIFEST_INVALID")
        if self.tested_core_execution_fingerprint is not None:
            _sha(self.tested_core_execution_fingerprint, "RUNTIME_GENERATION_ARTIFACT_MANIFEST_INVALID")
        if self.provider_content_fingerprint is not None:
            _sha(self.provider_content_fingerprint, "RUNTIME_GENERATION_ARTIFACT_MANIFEST_INVALID")
        for value in (self.provider_id, self.provider_version):
            if value is not None and not _valid_identity(value):
                raise ValueError("RUNTIME_GENERATION_ARTIFACT_MANIFEST_INVALID")
        assets = tuple(sorted(self.assets))
        implementations = tuple(sorted(self.implementations))
        if len(set(assets)) != len(assets) or len(set(implementations)) != len(implementations):
            raise ValueError("RUNTIME_GENERATION_ARTIFACT_MANIFEST_INVALID")
        object.__setattr__(self, "assets", assets)
        object.__setattr__(self, "implementations", implementations)

    @property
    def artifact_identity(self) -> str:
        """Artifact byte identity is locator- and provenance-independent."""

        return self.artifact_sha256

    @property
    def manifest_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.to_dict(include_fingerprint=False))

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "role": self.role.value,
            "source_repository": self.source_repository,
            "source_revision": self.source_revision,
            "distribution_name": self.distribution_name,
            "distribution_version": self.distribution_version,
            "artifact_logical_name": self.artifact_logical_name,
            "artifact_sha256": self.artifact_sha256,
            "artifact_size": self.artifact_size,
            "tested_core_execution_fingerprint": self.tested_core_execution_fingerprint,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "provider_content_fingerprint": self.provider_content_fingerprint,
            "assets": [item.to_dict() for item in self.assets],
            "implementations": [item.to_dict() for item in self.implementations],
        }
        if include_fingerprint:
            result["manifest_fingerprint"] = self.manifest_fingerprint
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyDistributionArtifactManifest:
        expected = {
            "schema_version",
            "role",
            "source_repository",
            "source_revision",
            "distribution_name",
            "distribution_version",
            "artifact_logical_name",
            "artifact_sha256",
            "artifact_size",
            "tested_core_execution_fingerprint",
            "provider_id",
            "provider_version",
            "provider_content_fingerprint",
            "assets",
            "implementations",
            "manifest_fingerprint",
        }
        _exact(payload, expected)
        result = cls(
            role=OnlyDistributionArtifactRole(_string(payload, "role")),
            source_repository=_string(payload, "source_repository"),
            source_revision=_string(payload, "source_revision"),
            distribution_name=_string(payload, "distribution_name"),
            distribution_version=_string(payload, "distribution_version"),
            artifact_logical_name=_string(payload, "artifact_logical_name"),
            artifact_sha256=_string(payload, "artifact_sha256"),
            artifact_size=_integer(payload, "artifact_size"),
            tested_core_execution_fingerprint=_optional_string(payload, "tested_core_execution_fingerprint"),
            provider_id=_optional_string(payload, "provider_id"),
            provider_version=_optional_string(payload, "provider_version"),
            provider_content_fingerprint=_optional_string(payload, "provider_content_fingerprint"),
            assets=tuple(OnlyArtifactAssetIdentity.from_dict(item) for item in _mapping_list(payload, "assets")),
            implementations=tuple(
                OnlyArtifactCalculationImplementation.from_dict(item)
                for item in _mapping_list(payload, "implementations")
            ),
            schema_version=_integer(payload, "schema_version"),
        )
        if _string(payload, "manifest_fingerprint") != result.manifest_fingerprint:
            raise ValueError("RUNTIME_GENERATION_ARTIFACT_MANIFEST_MISMATCH")
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


def _optional_string(payload: Mapping[str, object], key: str) -> str | None:
    value = payload[key]
    if value is not None and not isinstance(value, str):
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


__all__ = [name for name in globals() if name.startswith("Only")]
