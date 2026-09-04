"""Stable port for server-verified authoring execution generations."""

from __future__ import annotations

from typing import Protocol

from onlyalpha.research.provenance import OnlyResearchAuthoringProvenance
from onlyalpha.research.specification.model import OnlyResearchSpecification
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolution


class OnlyResearchAuthoringGenerationResolver(Protocol):
    """Resolve through the exact generation verified by an external component."""

    def resolve(
        self,
        provenance: OnlyResearchAuthoringProvenance,
        specification: OnlyResearchSpecification,
    ) -> OnlyResearchSpecificationResolution: ...


__all__ = ["OnlyResearchAuthoringGenerationResolver"]
