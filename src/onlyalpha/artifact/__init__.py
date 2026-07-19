"""Atomic persistence of immutable Result and Analysis objects."""

from onlyalpha.artifact.models import (
    OnlyArtifactDescriptor,
    OnlyBacktestArtifactManifest,
    OnlyRunArtifactTarget,
)
from onlyalpha.artifact.writer import OnlyBacktestArtifactWriter

__all__ = [
    "OnlyArtifactDescriptor",
    "OnlyBacktestArtifactManifest",
    "OnlyBacktestArtifactWriter",
    "OnlyRunArtifactTarget",
]
