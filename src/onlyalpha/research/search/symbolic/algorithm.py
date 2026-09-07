"""Actual running deterministic-enumerator implementation authority."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from onlyalpha.canonical import only_canonical_fingerprint

from .model import (
    DETERMINISTIC_ENUMERATION_ALGORITHM_ID,
    DETERMINISTIC_ENUMERATION_ALGORITHM_SEMANTIC_VERSION,
)


@dataclass(frozen=True, slots=True)
class OnlySymbolicSearchAlgorithmImplementationV1:
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
        if len(self.implementation_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in self.implementation_fingerprint
        ):
            raise ValueError("SEARCH_ALGORITHM_IMPLEMENTATION_INVALID")


def only_deterministic_enumeration_implementation() -> OnlySymbolicSearchAlgorithmImplementationV1:
    """Hash the explicit executable closure shipped by the running OnlyAlpha package."""

    package_root = Path(__file__).resolve().parents[3]
    resources = (
        "research/search/symbolic/enumeration.py",
        "research/search/symbolic/verification.py",
        "research/search/symbolic/model.py",
        "calculation/compatibility.py",
        "calculation/graph.py",
        "calculation/registry.py",
    )
    resource_identities = []
    for relative_path in resources:
        path = package_root / relative_path
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"SEARCH_ALGORITHM_IMPLEMENTATION_RESOURCE_INVALID: {relative_path}")
        resource_identities.append(
            {"relative_path": relative_path, "byte_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        )
    try:
        package_version = version("onlyalpha")
    except PackageNotFoundError:
        package_version = "source-tree"
    source_revision = f"onlyalpha@{package_version}"
    implementation_fingerprint = only_canonical_fingerprint(
        {
            "domain": "onlyalpha.research.symbolic-search-algorithm-implementation",
            "schema_version": 1,
            "algorithm_id": DETERMINISTIC_ENUMERATION_ALGORITHM_ID,
            "algorithm_semantic_version": DETERMINISTIC_ENUMERATION_ALGORITHM_SEMANTIC_VERSION,
            "source_revision": source_revision,
            "resources": resource_identities,
        }
    )
    return OnlySymbolicSearchAlgorithmImplementationV1(
        DETERMINISTIC_ENUMERATION_ALGORITHM_ID,
        DETERMINISTIC_ENUMERATION_ALGORITHM_SEMANTIC_VERSION,
        implementation_fingerprint,
        source_revision,
    )


__all__ = [name for name in globals() if name.startswith(("OnlySymbolic", "only_"))]
