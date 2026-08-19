"""Structured fail-closed errors for Research Definition V1."""

from __future__ import annotations

from enum import StrEnum


class OnlyResearchDefinitionPhase(StrEnum):
    SCHEMA = "SCHEMA"
    UNIVERSE = "UNIVERSE"
    DATASET = "DATASET"
    CALCULATION = "CALCULATION"
    CANDIDATE = "CANDIDATE"
    EXPRESSION = "EXPRESSION"
    TARGET = "TARGET"
    STATISTICS = "STATISTICS"
    SPECIFICATION = "SPECIFICATION"


class OnlyResearchDefinitionError(ValueError):
    def __init__(self, phase: OnlyResearchDefinitionPhase, code: str, path: str, detail: str) -> None:
        self.phase = phase
        self.code = code
        self.path = path
        self.detail = detail
        super().__init__(f"{phase.value}:{code}:{path}: {detail}")


__all__ = ["OnlyResearchDefinitionError", "OnlyResearchDefinitionPhase"]
