"""External execution routing port."""

from typing import Protocol

from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.order.execution.models import (
    OnlyExecutionCancelRequest,
    OnlyExecutionCancelResult,
    OnlyExecutionSubmitResult,
)


class OnlyExecutionService(Protocol):
    def submit_order(self, order: OnlyOrderSnapshot) -> OnlyExecutionSubmitResult: ...

    def cancel_order(self, request: OnlyExecutionCancelRequest) -> OnlyExecutionCancelResult: ...
