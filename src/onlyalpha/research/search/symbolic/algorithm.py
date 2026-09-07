"""Durable historical and current-runtime symbolic algorithm authority."""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import cast

from onlyalpha.canonical import only_canonical_fingerprint

from .model import (
    DETERMINISTIC_ENUMERATION_ALGORITHM_ID,
    DETERMINISTIC_ENUMERATION_ALGORITHM_SEMANTIC_VERSION,
)


def _sha(value: object, context: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{context} must be a lower-case SHA256")
    return value


def _mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{context} must be an object")
    return cast(Mapping[str, object], value)


@dataclass(frozen=True, slots=True, order=True)
class OnlySymbolicSearchAlgorithmResourceV1:
    logical_resource_id: str
    byte_sha256: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.logical_resource_id or self.logical_resource_id.startswith("/"):
            raise ValueError("SEARCH_ALGORITHM_RESOURCE_INVALID")
        if ".." in Path(self.logical_resource_id).parts or "\\" in self.logical_resource_id:
            raise ValueError("SEARCH_ALGORITHM_RESOURCE_INVALID")
        _sha(self.byte_sha256, "byte_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "logical_resource_id": self.logical_resource_id,
            "byte_sha256": self.byte_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySymbolicSearchAlgorithmResourceV1:
        if set(payload) != {"schema_version", "logical_resource_id", "byte_sha256"}:
            raise ValueError("SEARCH_ALGORITHM_RESOURCE_INVALID")
        schema_version = payload["schema_version"]
        if isinstance(schema_version, bool) or not isinstance(schema_version, int):
            raise ValueError("SEARCH_ALGORITHM_RESOURCE_INVALID")
        return cls(str(payload["logical_resource_id"]), str(payload["byte_sha256"]), schema_version)


@dataclass(frozen=True, slots=True)
class OnlySymbolicSearchAlgorithmImplementationManifestV1:
    algorithm_id: str
    algorithm_semantic_version: str
    source_revision: str
    resources: tuple[OnlySymbolicSearchAlgorithmResourceV1, ...]
    distribution_name: str | None = None
    distribution_version: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("SEARCH_ALGORITHM_IMPLEMENTATION_SCHEMA_UNSUPPORTED")
        if not self.algorithm_id or not self.algorithm_semantic_version or not self.source_revision:
            raise ValueError("SEARCH_ALGORITHM_IMPLEMENTATION_INVALID")
        if (self.distribution_name is None) != (self.distribution_version is None):
            raise ValueError("SEARCH_ALGORITHM_IMPLEMENTATION_INVALID")
        if not self.resources or any(
            not isinstance(item, OnlySymbolicSearchAlgorithmResourceV1) for item in self.resources
        ):
            raise ValueError("SEARCH_ALGORITHM_IMPLEMENTATION_INVALID")
        resources = tuple(sorted(self.resources, key=lambda item: item.logical_resource_id))
        if len({item.logical_resource_id for item in resources}) != len(resources):
            raise ValueError("SEARCH_ALGORITHM_IMPLEMENTATION_INVALID")
        object.__setattr__(self, "resources", resources)

    @property
    def implementation_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "domain": "onlyalpha.research.symbolic-search-algorithm-implementation",
                **self.to_dict(include_fingerprint=False),
            }
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "algorithm_id": self.algorithm_id,
            "algorithm_semantic_version": self.algorithm_semantic_version,
            "source_revision": self.source_revision,
            "resources": [item.to_dict() for item in self.resources],
            "distribution_name": self.distribution_name,
            "distribution_version": self.distribution_version,
        }
        if include_fingerprint:
            payload["implementation_fingerprint"] = self.implementation_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlySymbolicSearchAlgorithmImplementationManifestV1:
        expected = {
            "schema_version",
            "algorithm_id",
            "algorithm_semantic_version",
            "source_revision",
            "resources",
            "distribution_name",
            "distribution_version",
            "implementation_fingerprint",
        }
        if set(payload) != expected or not isinstance(payload["resources"], list):
            raise ValueError("SEARCH_ALGORITHM_IMPLEMENTATION_FIELDS_INVALID")
        schema_version = payload["schema_version"]
        distribution_name = payload["distribution_name"]
        distribution_version = payload["distribution_version"]
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or (distribution_name is not None and not isinstance(distribution_name, str))
            or (distribution_version is not None and not isinstance(distribution_version, str))
        ):
            raise ValueError("SEARCH_ALGORITHM_IMPLEMENTATION_FIELDS_INVALID")
        value = cls(
            str(payload["algorithm_id"]),
            str(payload["algorithm_semantic_version"]),
            str(payload["source_revision"]),
            tuple(
                OnlySymbolicSearchAlgorithmResourceV1.from_dict(_mapping(item, "algorithm resource"))
                for item in payload["resources"]
            ),
            distribution_name,
            distribution_version,
            schema_version,
        )
        if payload["implementation_fingerprint"] != value.implementation_fingerprint:
            raise ValueError("SEARCH_ALGORITHM_IMPLEMENTATION_IDENTITY_DIFFERS")
        return value


@dataclass(frozen=True, slots=True)
class OnlySymbolicSearchAlgorithmImplementationV1:
    """Historical compatibility shape for the pre-Manifest ephemeral runtime proof."""

    algorithm_id: str
    algorithm_semantic_version: str
    implementation_fingerprint: str
    source_revision: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("SEARCH_ALGORITHM_IMPLEMENTATION_SCHEMA_UNSUPPORTED")
        if not self.algorithm_id or not self.algorithm_semantic_version or not self.source_revision:
            raise ValueError("SEARCH_ALGORITHM_IMPLEMENTATION_INVALID")
        _sha(self.implementation_fingerprint, "implementation_fingerprint")


def _source_revision(repository_root: Path, package_version: str | None) -> str:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_root), "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return _sha(completed.stdout.strip(), "Git source revision")
    except (FileNotFoundError, subprocess.SubprocessError, ValueError):
        if package_version is None:
            raise ValueError("SEARCH_ALGORITHM_SOURCE_REVISION_UNAVAILABLE") from None
        return f"onlyalpha@{package_version}"


def only_deterministic_enumeration_implementation() -> OnlySymbolicSearchAlgorithmImplementationManifestV1:
    """Derive the exact executable closure shipped by the running OnlyAlpha package."""

    package_root = Path(__file__).resolve().parents[3]
    repository_root = package_root.parents[1]
    resources = (
        "research/search/symbolic/enumeration.py",
        "research/search/symbolic/verification.py",
        "research/search/symbolic/model.py",
        "research/calculation/binding.py",
        "calculation/compatibility.py",
        "calculation/definition.py",
        "calculation/graph.py",
        "calculation/registry.py",
        "quant_assets/catalog.py",
    )
    identities = []
    for relative_path in resources:
        path = package_root / relative_path
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"SEARCH_ALGORITHM_IMPLEMENTATION_RESOURCE_INVALID: {relative_path}")
        identities.append(
            OnlySymbolicSearchAlgorithmResourceV1(relative_path, hashlib.sha256(path.read_bytes()).hexdigest())
        )
    try:
        package_version = version("onlyalpha")
    except PackageNotFoundError:
        package_version = None
    return OnlySymbolicSearchAlgorithmImplementationManifestV1(
        DETERMINISTIC_ENUMERATION_ALGORITHM_ID,
        DETERMINISTIC_ENUMERATION_ALGORITHM_SEMANTIC_VERSION,
        _source_revision(repository_root, package_version),
        tuple(identities),
        None if package_version is None else "onlyalpha",
        package_version,
    )


__all__ = [name for name in globals() if name.startswith(("OnlySymbolic", "only_"))]
