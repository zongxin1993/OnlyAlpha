"""Minimal read-only ports required by Research Definition resolution."""

from __future__ import annotations

from typing import Protocol

from onlyalpha.research.dataset import OnlyResearchDatasetDefinition, OnlyVerifiedResearchDataset

from .model import OnlyResearchUniverseSelection


class OnlyResearchUniverseResolver(Protocol):
    def resolve(self, selection: OnlyResearchUniverseSelection) -> tuple[str, ...]: ...


class OnlyResearchDefinitionDatasetResolver(Protocol):
    def resolve_verified(self, definition: OnlyResearchDatasetDefinition) -> OnlyVerifiedResearchDataset: ...


__all__ = ["OnlyResearchDefinitionDatasetResolver", "OnlyResearchUniverseResolver"]
