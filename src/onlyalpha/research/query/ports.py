"""Read-only ports consumed by the transport-neutral Research Query service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from onlyalpha.research.artifact.model import OnlyResearchArtifact


class OnlyResearchArtifactReader(Protocol):
    def load_verified(self, research_result_fingerprint: str) -> OnlyResearchArtifact: ...
