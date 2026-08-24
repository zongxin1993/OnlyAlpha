"""Serializable immutable evidence from one finite Research Runtime execution."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.research.evaluation.result import OnlyResearchStatisticsOutcome
from onlyalpha.research.job import OnlyResearchJobOutcome
from onlyalpha.research.sweep.outcome import OnlyResearchSweepOutcome
from onlyalpha.runtime.result import OnlyRuntimeResultStatus

from .errors import OnlyResearchRuntimePhase


@dataclass(frozen=True, slots=True)
class OnlyResearchRuntimeResult:
    runtime_id: OnlyRuntimeId
    status: OnlyRuntimeResultStatus
    dataset_snapshot_fingerprint: str
    direct_job_outcomes: tuple[OnlyResearchJobOutcome, ...] = ()
    sweep_outcomes: tuple[OnlyResearchSweepOutcome, ...] = ()
    statistics_outcomes: tuple[OnlyResearchStatisticsOutcome, ...] = ()
    research_result_plan_fingerprint: str = ""
    research_result_fingerprint: str = ""
    artifact_content_fingerprint: str = ""
    calculation_execution_evidence_fingerprints: tuple[str, ...] = ()
    determinism_fingerprint: str = ""
    phase: OnlyResearchRuntimePhase | None = None
    code: str | None = None
    detail: str | None = None
    runtime_type: str = "RESEARCH"

    def to_dict(self) -> dict[str, object]:
        return {
            "runtime_id": str(self.runtime_id),
            "runtime_type": self.runtime_type,
            "status": self.status.value,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "direct_job_outcomes": [_job(item) for item in self.direct_job_outcomes],
            "sweep_outcomes": [_sweep(item) for item in self.sweep_outcomes],
            "statistics_outcomes": [_statistics(item) for item in self.statistics_outcomes],
            "research_result_plan_fingerprint": self.research_result_plan_fingerprint,
            "research_result_fingerprint": self.research_result_fingerprint,
            "artifact_content_fingerprint": self.artifact_content_fingerprint,
            "calculation_execution_evidence_fingerprints": list(self.calculation_execution_evidence_fingerprints),
            "determinism_fingerprint": self.determinism_fingerprint,
            "failure": None
            if self.phase is None
            else {"phase": self.phase.value, "code": self.code, "detail": self.detail},
        }


def _job(value: OnlyResearchJobOutcome) -> dict[str, object]:
    return {
        "status": value.status.value,
        "disposition": value.disposition.value,
        "calculation_fingerprint": value.calculation_fingerprint,
        "calculation_result_fingerprint": value.calculation_result_fingerprint,
        "calculation_execution_evidence_fingerprint": value.calculation_execution_evidence_fingerprint,
    }


def _statistics(value: OnlyResearchStatisticsOutcome) -> dict[str, object]:
    return {
        "disposition": value.disposition.value,
        "statistics_fingerprint": value.statistics_fingerprint,
        "statistics_result_fingerprint": value.statistics_result_fingerprint,
    }


def _sweep(value: OnlyResearchSweepOutcome) -> dict[str, object]:
    return {
        "total_cells": value.total_cells,
        "executed_count": value.executed_count,
        "reused_count": value.reused_count,
        "cells": [
            {
                "ordinal": cell.ordinal,
                "calculation_fingerprint": cell.calculation_fingerprint,
                "calculation_result_fingerprint": cell.calculation_result_fingerprint,
                "calculation_execution_evidence_fingerprint": cell.calculation_execution_evidence_fingerprint,
                "disposition": cell.disposition.value,
            }
            for cell in value.cells
        ],
    }


__all__ = ["OnlyResearchRuntimeResult"]
