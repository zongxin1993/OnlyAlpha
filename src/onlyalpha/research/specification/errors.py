"""Stable public failure boundary for Research Specification resolution."""

from __future__ import annotations

from enum import StrEnum


class OnlyResearchSpecificationPhase(StrEnum):
    SCHEMA = "SCHEMA"
    TYPE_RESOLUTION = "TYPE_RESOLUTION"
    GRAPH_RESOLUTION = "GRAPH_RESOLUTION"
    SWEEP_RESOLUTION = "SWEEP_RESOLUTION"
    SERIES_RESOLUTION = "SERIES_RESOLUTION"
    STATISTICS_RESOLUTION = "STATISTICS_RESOLUTION"
    WORKLOAD_VALIDATION = "WORKLOAD_VALIDATION"


class OnlyResearchSpecificationError(ValueError):
    def __init__(self, phase: OnlyResearchSpecificationPhase, code: str, detail: str) -> None:
        self.phase = phase
        self.code = code
        self.detail = detail
        super().__init__(f"{phase.value}:{code}: {detail}")
