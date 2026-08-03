"""Execution-submission capability boundary shared by streaming runtimes."""

from enum import StrEnum

from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.order.execution.models import (
    OnlyExecutionCancelRequest,
    OnlyExecutionCancelResult,
    OnlyExecutionSubmissionOutcome,
    OnlyExecutionSubmitResult,
)


class OnlyExecutionSubmissionCapability(StrEnum):
    SHADOW = "SHADOW"
    SIMULATED = "SIMULATED"
    LIVE = "LIVE"


class OnlyShadowExecutionService:
    """Records an auditable would-submit intent without touching any Broker."""

    def __init__(self) -> None:
        self._submissions: list[OnlyOrderSnapshot] = []

    @property
    def submissions(self) -> tuple[OnlyOrderSnapshot, ...]:
        return tuple(self._submissions)

    def submit_order(self, order: OnlyOrderSnapshot) -> OnlyExecutionSubmitResult:
        self._submissions.append(order)
        return OnlyExecutionSubmitResult(
            False,
            "PAPER_RUNTIME: WOULD_SUBMIT; execution suppressed",
            OnlyExecutionSubmissionOutcome.SUPPRESSED,
        )

    def cancel_order(self, request: OnlyExecutionCancelRequest) -> OnlyExecutionCancelResult:
        del request
        return OnlyExecutionCancelResult(False, "PAPER_RUNTIME has no submitted Broker order")
