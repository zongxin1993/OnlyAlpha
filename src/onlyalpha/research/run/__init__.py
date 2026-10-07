"""Durable Research Run operational authority."""

from typing import TYPE_CHECKING as _TYPE_CHECKING

if _TYPE_CHECKING:
    from .calculation_resolution import (
        OnlyResearchCalculationRuntimeResolutionV1 as OnlyResearchCalculationRuntimeResolutionV1,
    )

from onlyalpha.research.provenance import OnlyResearchAuthoringProvenance as OnlyResearchAuthoringProvenance

from .admission import OnlyResearchRunAdmissionService  # noqa: F401
from .errors import *  # noqa: F403
from .evidence import only_research_admission_resolution_fingerprint  # noqa: F401
from .generation import OnlyResearchAuthoringGenerationResolver  # noqa: F401
from .model import OnlyResearchOriginKind as OnlyResearchOriginKind
from .model import OnlyResearchRun as OnlyResearchRun
from .model import OnlyResearchRunFailure as OnlyResearchRunFailure
from .model import OnlyResearchRunFailurePhase as OnlyResearchRunFailurePhase
from .model import OnlyResearchRunId as OnlyResearchRunId
from .model import OnlyResearchRunState as OnlyResearchRunState
from .store import OnlyResearchRunReader  # noqa: F401

__all__ = [name for name in globals() if name.startswith(("Only", "only_"))]
if "OnlyResearchCalculationRuntimeResolutionV1" not in __all__:
    __all__.append("OnlyResearchCalculationRuntimeResolutionV1")


def __getattr__(name: str) -> object:
    if name == "OnlyResearchCalculationRuntimeResolutionV1":
        from .calculation_resolution import OnlyResearchCalculationRuntimeResolutionV1

        return OnlyResearchCalculationRuntimeResolutionV1
    raise AttributeError(name)
