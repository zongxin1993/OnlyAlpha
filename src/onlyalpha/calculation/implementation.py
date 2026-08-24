"""Calculation implementation identity, separate from semantic Definition identity."""

from __future__ import annotations

import hashlib
import platform
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath

from onlyalpha.calculation.definition import OnlyCalculationBackendKind, OnlyCalculationTypeReference
from onlyalpha.canonical import only_canonical_fingerprint


class OnlyCalculationStateCapability(StrEnum):
    """Explicit TRADING Calculation replay-state contract."""

    STATELESS = "STATELESS"
    CHECKPOINTABLE = "CHECKPOINTABLE"


@dataclass(frozen=True, order=True, slots=True)
class OnlyCalculationImplementationResource:
    relative_path: str
    byte_sha256: str

    def __post_init__(self) -> None:
        path = PurePosixPath(self.relative_path)
        if (
            not self.relative_path
            or "\\" in self.relative_path
            or path.is_absolute()
            or ".." in path.parts
            or path.as_posix() != self.relative_path
        ):
            raise ValueError("implementation resource path must be canonical and relative")
        _require_sha(self.byte_sha256, "implementation resource byte identity")

    def to_dict(self) -> dict[str, str]:
        return {"relative_path": self.relative_path, "byte_sha256": self.byte_sha256}


@dataclass(frozen=True, order=True, slots=True)
class OnlyCalculationSemanticDependency:
    dependency_id: str
    semantic_version: str
    artifact_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not self.dependency_id.strip() or not self.semantic_version.strip():
            raise ValueError("semantic dependency identity is required")
        if self.artifact_fingerprint is not None:
            _require_sha(self.artifact_fingerprint, "semantic dependency artifact identity")

    def to_dict(self) -> dict[str, str | None]:
        return {
            "dependency_id": self.dependency_id,
            "semantic_version": self.semantic_version,
            "artifact_fingerprint": self.artifact_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class OnlyCalculationImplementationManifest:
    calculation_type_reference: OnlyCalculationTypeReference
    backend_kind: OnlyCalculationBackendKind
    entrypoint_identity: str
    resources: tuple[OnlyCalculationImplementationResource, ...]
    semantic_dependencies: tuple[OnlyCalculationSemanticDependency, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported Calculation implementation manifest schema")
        if not self.entrypoint_identity.strip() or self.entrypoint_identity.count(":") != 1:
            raise ValueError("implementation entrypoint identity must use module:qualname")
        resources = tuple(sorted(self.resources))
        dependencies = tuple(sorted(self.semantic_dependencies))
        if not resources or len(resources) != len(set(resources)):
            raise ValueError("implementation resources must be non-empty and unique")
        if len({item.relative_path for item in resources}) != len(resources):
            raise ValueError("implementation resource paths must be unique")
        if len(dependencies) != len(set(dependencies)):
            raise ValueError("semantic dependencies must be unique")
        object.__setattr__(self, "resources", resources)
        object.__setattr__(self, "semantic_dependencies", dependencies)

    @property
    def implementation_bundle_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "domain": "onlyalpha.calculation.implementation-bundle",
                "schema_version": 1,
                "resources": [item.to_dict() for item in self.resources],
            }
        )

    @property
    def implementation_fingerprint(self) -> str:
        reference = self.calculation_type_reference
        return only_canonical_fingerprint(
            {
                "domain": "onlyalpha.calculation.implementation",
                "schema_version": self.schema_version,
                "calculation_type_reference": {
                    "kind": reference.kind.value,
                    "type_id": reference.type_id,
                    "semantic_version": reference.semantic_version,
                },
                "backend_kind": self.backend_kind.value,
                "entrypoint_identity": self.entrypoint_identity,
                "implementation_bundle_fingerprint": self.implementation_bundle_fingerprint,
                "semantic_dependencies": [item.to_dict() for item in self.semantic_dependencies],
            }
        )

    def to_dict(self) -> dict[str, object]:
        reference = self.calculation_type_reference
        return {
            "schema_version": self.schema_version,
            "calculation_type_reference": {
                "kind": reference.kind.value,
                "type_id": reference.type_id,
                "semantic_version": reference.semantic_version,
            },
            "backend_kind": self.backend_kind.value,
            "entrypoint_identity": self.entrypoint_identity,
            "resources": [item.to_dict() for item in self.resources],
            "semantic_dependencies": [item.to_dict() for item in self.semantic_dependencies],
            "implementation_bundle_fingerprint": self.implementation_bundle_fingerprint,
            "implementation_fingerprint": self.implementation_fingerprint,
        }


def only_python_implementation_manifest(
    *,
    calculation_type_reference: OnlyCalculationTypeReference,
    backend_kind: OnlyCalculationBackendKind,
    entrypoint_identity: str,
    package_root: Path,
    resource_paths: Iterable[str],
    semantic_dependencies: Iterable[OnlyCalculationSemanticDependency] = (),
) -> OnlyCalculationImplementationManifest:
    """Hash one explicit Python implementation closure; no import crawling or repository hash."""

    resources: list[OnlyCalculationImplementationResource] = []
    resolved_root = package_root.resolve()
    for value in resource_paths:
        relative = PurePosixPath(value)
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != value:
            raise ValueError("implementation resource path must be canonical and relative")
        path = (resolved_root / value).resolve()
        if path.parent != resolved_root and resolved_root not in path.parents:
            raise ValueError("implementation resource escapes package root")
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"implementation resource is not a regular file: {value}")
        resources.append(OnlyCalculationImplementationResource(value, hashlib.sha256(path.read_bytes()).hexdigest()))
    return OnlyCalculationImplementationManifest(
        calculation_type_reference,
        backend_kind,
        entrypoint_identity,
        tuple(resources),
        tuple(semantic_dependencies),
    )


def only_implementation_manifest_from_bytes(
    *,
    calculation_type_reference: OnlyCalculationTypeReference,
    backend_kind: OnlyCalculationBackendKind,
    entrypoint_identity: str,
    resources: Mapping[str, bytes],
    semantic_dependencies: Iterable[OnlyCalculationSemanticDependency] = (),
) -> OnlyCalculationImplementationManifest:
    """Construct an exact manifest for admitted in-memory/test implementation bundles."""

    return OnlyCalculationImplementationManifest(
        calculation_type_reference,
        backend_kind,
        entrypoint_identity,
        tuple(
            OnlyCalculationImplementationResource(path, hashlib.sha256(content).hexdigest())
            for path, content in resources.items()
        ),
        tuple(semantic_dependencies),
    )


def only_python_stdlib_semantic_dependency(module_id: str) -> OnlyCalculationSemanticDependency:
    """Bind semantics that rely on the active Python standard-library numeric runtime."""

    return OnlyCalculationSemanticDependency(
        f"{platform.python_implementation().lower()}.{module_id}",
        platform.python_version(),
    )


def only_distribution_semantic_dependency(distribution: str) -> OnlyCalculationSemanticDependency:
    """Bind one exact third-party distribution that affects deterministic outputs."""

    try:
        semantic_version = version(distribution)
    except PackageNotFoundError as exc:
        raise ValueError(f"semantic dependency distribution is unavailable: {distribution}") from exc
    return OnlyCalculationSemanticDependency(distribution, semantic_version)


def _require_sha(value: str, name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lower-case SHA256")


__all__ = [name for name in globals() if name.startswith(("Only", "only_"))]
