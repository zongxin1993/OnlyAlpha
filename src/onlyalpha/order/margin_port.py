"""Narrow Order-to-Margin reservation lifecycle port."""

from typing import Protocol

from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyOrderId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice


class OnlyOrderMarginReservationPort(Protocol):
    def reserve(
        self,
        order: OnlyOrderSnapshot,
        timestamp: OnlyTimestamp,
        *,
        planning_price: OnlyPrice | None = None,
    ) -> None: ...

    def sent(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None: ...

    def release(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None: ...
