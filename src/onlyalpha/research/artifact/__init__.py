"""Derived immutable and portable Research Artifact read boundary."""
# ruff: noqa: F401

from importlib import import_module as _import_module
from typing import TYPE_CHECKING as _TYPE_CHECKING

if _TYPE_CHECKING:
    from .calculation_v2_materializer import (
        OnlyResearchCalculationArtifactMaterializerV2 as OnlyResearchCalculationArtifactMaterializerV2,
    )
    from .calculation_v2_model import (
        RESEARCH_CALCULATION_ARTIFACT_V2_PROFILE as RESEARCH_CALCULATION_ARTIFACT_V2_PROFILE,
    )
    from .calculation_v2_model import (
        RESEARCH_CALCULATION_ARTIFACT_V2_SCHEMA_VERSION as RESEARCH_CALCULATION_ARTIFACT_V2_SCHEMA_VERSION,
    )
    from .calculation_v2_model import OnlyResearchCalculationArtifactFileV2 as OnlyResearchCalculationArtifactFileV2
    from .calculation_v2_model import (
        OnlyResearchCalculationArtifactManifestV2 as OnlyResearchCalculationArtifactManifestV2,
    )
    from .calculation_v2_store import (
        OnlyParquetResearchCalculationArtifactStoreV2 as OnlyParquetResearchCalculationArtifactStoreV2,
    )
    from .calculation_v2_verification import OnlyResearchCalculationArtifactV2 as OnlyResearchCalculationArtifactV2
from .errors import OnlyResearchArtifactError, OnlyResearchArtifactStoreError
from .identity import (
    RESEARCH_ARTIFACT_PROFILE,
    RESEARCH_ARTIFACT_SCHEMA_VERSION,
    only_research_artifact_content_fingerprint,
)
from .materializer import OnlyResearchArtifactCandidate, OnlyResearchArtifactMaterializer
from .model import (
    OnlyResearchArtifact,
    OnlyResearchArtifactDisposition,
    OnlyResearchArtifactManifest,
    OnlyResearchArtifactOutcome,
    OnlyResearchArtifactStatisticsEntry,
    OnlyResearchArtifactStatisticsRow,
    OnlyResearchArtifactStatisticsTable,
)
from .reader import OnlyResearchArtifactProfileReader
from .scientific_materializer import (
    OnlyResearchScientificArtifactCandidate,
    OnlyResearchScientificArtifactMaterializer,
)
from .scientific_model import *  # noqa: F403
from .scientific_store import OnlyParquetResearchCalculationArtifactStore, OnlyParquetResearchScientificArtifactStore
from .scientific_v3_materializer import (
    OnlyResearchScientificArtifactCandidateV3,
    OnlyResearchScientificArtifactMaterializerV3,
)
from .scientific_v3_model import *  # noqa: F403
from .scientific_v3_store import OnlyParquetResearchScientificArtifactStoreV3
from .store import OnlyParquetResearchArtifactStore

_LAZY_EXPORTS = {
    "OnlyResearchCalculationArtifactMaterializerV2": ".calculation_v2_materializer",
    "RESEARCH_CALCULATION_ARTIFACT_V2_PROFILE": ".calculation_v2_model",
    "RESEARCH_CALCULATION_ARTIFACT_V2_SCHEMA_VERSION": ".calculation_v2_model",
    "OnlyResearchCalculationArtifactFileV2": ".calculation_v2_model",
    "OnlyResearchCalculationArtifactManifestV2": ".calculation_v2_model",
    "OnlyParquetResearchCalculationArtifactStoreV2": ".calculation_v2_store",
    "OnlyResearchCalculationArtifactV2": ".calculation_v2_verification",
}


def __getattr__(name: str) -> object:
    module = _LAZY_EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(_import_module(module, __name__), name)
    globals()[name] = value
    return value


__all__ = [
    name
    for name in globals()
    if name.startswith(
        ("Only", "only_", "RESEARCH_ARTIFACT_", "RESEARCH_SCIENTIFIC_", "RESEARCH_CALCULATION_ARTIFACT_")
    )
] + list(_LAZY_EXPORTS)
