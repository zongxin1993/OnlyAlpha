"""Read-only ports consumed by the transport-neutral Research Query service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from onlyalpha.research.artifact.model import OnlyResearchArtifact
    from onlyalpha.research.artifact.scientific_model import OnlyResearchScientificArtifact
    from onlyalpha.research.artifact.scientific_v3_model import OnlyResearchScientificArtifactV3


class OnlyResearchArtifactReader(Protocol):
    def load_verified(
        self, research_result_fingerprint: str
    ) -> OnlyResearchArtifact | OnlyResearchScientificArtifact | OnlyResearchScientificArtifactV3: ...
