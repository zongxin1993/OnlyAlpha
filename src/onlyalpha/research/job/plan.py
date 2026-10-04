"""Exact immutable contract for one resolved Research Job."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.research.calculation.identity import only_research_calculation_fingerprint
from onlyalpha.research.calculation.publication import OnlyResearchCalculationPublicationContract
from onlyalpha.research.dataset.strict import require_sha256

from .errors import OnlyResearchJobError, OnlyResearchJobPhase

RESEARCH_JOB_PLAN_SCHEMA_VERSION = 1
RESEARCH_JOB_PLAN_READINESS_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class OnlyResearchJobPlan:
    """A fully resolved Dataset Snapshot plus canonical Calculation Graph."""

    dataset_snapshot_fingerprint: str
    calculation_graph: OnlyCalculationGraphDefinition
    schema_version: int = RESEARCH_JOB_PLAN_SCHEMA_VERSION
    publication: OnlyResearchCalculationPublicationContract | None = None

    def __post_init__(self) -> None:
        try:
            if type(self.schema_version) is not int or self.schema_version not in (
                RESEARCH_JOB_PLAN_SCHEMA_VERSION,
                RESEARCH_JOB_PLAN_READINESS_SCHEMA_VERSION,
            ):
                raise ValueError(f"unsupported Research Job Plan schema version: {self.schema_version}")
            if self.schema_version == RESEARCH_JOB_PLAN_SCHEMA_VERSION:
                if self.publication is not None:
                    raise ValueError("V1 Job Plan cannot request readiness publication")
            else:
                if type(self.publication) is not OnlyResearchCalculationPublicationContract:
                    raise ValueError("V2 Job Plan requires exact publication contract")
                OnlyResearchCalculationPublicationContract.from_dict(self.publication.to_dict())
            require_sha256(
                {"dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint},
                "dataset_snapshot_fingerprint",
                "Research Job Plan",
            )
            if not isinstance(self.calculation_graph, OnlyCalculationGraphDefinition):
                raise ValueError("Research Job Plan calculation_graph must be canonical")
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlyResearchJobError(
                OnlyResearchJobPhase.PLAN_VALIDATION,
                "RESEARCH_JOB_INVALID",
                str(exc),
            ) from exc

    @property
    def calculation_fingerprint(self) -> str:
        """Reuse the existing Calculation identity; Job adds no semantic identity."""

        return only_research_calculation_fingerprint(
            self.dataset_snapshot_fingerprint,
            self.calculation_graph.fingerprint,
        )
