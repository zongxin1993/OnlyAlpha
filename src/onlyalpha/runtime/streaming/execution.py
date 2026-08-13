"""Execution-submission capability boundary shared by streaming runtimes."""

from enum import StrEnum


class OnlyExecutionSubmissionCapability(StrEnum):
    SIMULATED = "SIMULATED"
    LIVE = "LIVE"
