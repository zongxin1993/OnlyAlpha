"""Minimal read-only ports required by Research Definition resolution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from onlyalpha.research.dataset import OnlyResearchDatasetDefinition, OnlyVerifiedResearchDataset

from .model import OnlyResearchUniverseKind, OnlyResearchUniverseSelection


@dataclass(frozen=True, slots=True)
class OnlyResearchRegisteredUniverse:
    registered_id: str
    kind: OnlyResearchUniverseKind
    display_metadata: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if self.kind not in {OnlyResearchUniverseKind.REGISTERED_POOL, OnlyResearchUniverseKind.REGISTERED_UNIVERSE}:
            raise ValueError("registered Universe catalog entry kind is invalid")
        if not self.registered_id or any(char.isspace() for char in self.registered_id):
            raise ValueError("registered Universe catalog entry identity is invalid")
        object.__setattr__(self, "display_metadata", MappingProxyType(dict(self.display_metadata)))


class OnlyResearchUniverseResolver(Protocol):
    def resolve(self, selection: OnlyResearchUniverseSelection) -> tuple[str, ...]: ...


@runtime_checkable
class OnlyResearchUniverseCatalog(Protocol):
    def list_registered(self) -> tuple[OnlyResearchRegisteredUniverse, ...]: ...


class OnlyResearchDefinitionDatasetResolver(Protocol):
    def resolve_verified(self, definition: OnlyResearchDatasetDefinition) -> OnlyVerifiedResearchDataset: ...


__all__ = [
    "OnlyResearchDefinitionDatasetResolver",
    "OnlyResearchRegisteredUniverse",
    "OnlyResearchUniverseCatalog",
    "OnlyResearchUniverseResolver",
]
