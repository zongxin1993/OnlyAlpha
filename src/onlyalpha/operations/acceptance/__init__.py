"""Public Paper real-product acceptance workflow."""

from .artifacts import OnlyAcceptanceArtifactBundle, OnlyAcceptanceArtifactWriter
from .assertions import OnlyPaperAcceptanceAssertions
from .evidence import only_evidence_from_dict, only_evidence_to_dict
from .models import (
    OnlyAcceptanceCase,
    OnlyAcceptanceEvidence,
    OnlyAcceptanceExecutionStage,
    OnlyAcceptanceFailureKind,
    OnlyAcceptanceVerdict,
)
from .paper_plan import OnlyPaperAcceptancePlan
from .paper_runner import OnlyPaperAcceptanceResult, OnlyPaperAcceptanceRunner
from .verdict import OnlyAcceptanceVerdictReducer

__all__ = [
    "OnlyAcceptanceArtifactBundle",
    "OnlyAcceptanceArtifactWriter",
    "OnlyAcceptanceCase",
    "OnlyAcceptanceEvidence",
    "OnlyAcceptanceExecutionStage",
    "OnlyAcceptanceFailureKind",
    "OnlyAcceptanceVerdict",
    "OnlyAcceptanceVerdictReducer",
    "OnlyPaperAcceptanceAssertions",
    "OnlyPaperAcceptancePlan",
    "OnlyPaperAcceptanceResult",
    "OnlyPaperAcceptanceRunner",
    "only_evidence_from_dict",
    "only_evidence_to_dict",
]
