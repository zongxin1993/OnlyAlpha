"""Immutable ephemeral evidence for one Sweep invocation."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.calculation import OnlyCalculationScalar
from onlyalpha.research.dataset.strict import require_sha256
from onlyalpha.research.job import OnlyResearchJobDisposition

from .definition import OnlyResearchSweepParameterTarget


@dataclass(frozen=True, slots=True)
class OnlyResearchSweepCellOutcome:
    ordinal: int
    assignment: tuple[tuple[OnlyResearchSweepParameterTarget, OnlyCalculationScalar], ...]
    calculation_fingerprint: str
    calculation_result_fingerprint: str
    disposition: OnlyResearchJobDisposition

    def __post_init__(self) -> None:
        if isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ValueError("Sweep Cell Outcome ordinal must be non-negative")
        if not isinstance(self.disposition, OnlyResearchJobDisposition):
            raise ValueError("Sweep Cell Outcome disposition is invalid")
        require_sha256(
            {"calculation_fingerprint": self.calculation_fingerprint},
            "calculation_fingerprint",
            "Sweep Cell Outcome",
        )
        require_sha256(
            {"calculation_result_fingerprint": self.calculation_result_fingerprint},
            "calculation_result_fingerprint",
            "Sweep Cell Outcome",
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchSweepOutcome:
    total_cells: int
    executed_count: int
    reused_count: int
    cells: tuple[OnlyResearchSweepCellOutcome, ...]

    def __post_init__(self) -> None:
        if self.total_cells != len(self.cells):
            raise ValueError("Sweep Outcome total_cells must match ordered Cell Outcomes")
        if self.executed_count + self.reused_count != self.total_cells:
            raise ValueError("Sweep Outcome disposition counts are inconsistent")
        if tuple(cell.ordinal for cell in self.cells) != tuple(range(self.total_cells)):
            raise ValueError("Sweep Outcome Cell ordinals must be canonical and contiguous")
