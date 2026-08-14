"""Explicit successful outcome for one Research Job invocation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.research.dataset.strict import require_sha256


class OnlyResearchJobStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"


class OnlyResearchJobDisposition(StrEnum):
    EXECUTED = "EXECUTED"
    REUSED = "REUSED"


@dataclass(frozen=True, slots=True)
class OnlyResearchJobOutcome:
    status: OnlyResearchJobStatus
    disposition: OnlyResearchJobDisposition
    calculation_fingerprint: str
    calculation_result_fingerprint: str

    def __post_init__(self) -> None:
        if self.status is not OnlyResearchJobStatus.SUCCEEDED:
            raise ValueError("Research Job Outcome status must be SUCCEEDED")
        if not isinstance(self.disposition, OnlyResearchJobDisposition):
            raise ValueError("Research Job Outcome disposition is invalid")
        require_sha256(
            {
                "calculation_fingerprint": self.calculation_fingerprint,
                "calculation_result_fingerprint": self.calculation_result_fingerprint,
            },
            "calculation_fingerprint",
            "Research Job Outcome",
        )
        require_sha256(
            {"calculation_result_fingerprint": self.calculation_result_fingerprint},
            "calculation_result_fingerprint",
            "Research Job Outcome",
        )
