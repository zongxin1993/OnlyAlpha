"""Narrow Order-to-Position Reservation orchestration port."""

from typing import Protocol

from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyOrderId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyQuantity


class OnlyOrderPositionReservationPort(Protocol):
    def reserve(self, order: OnlyOrderSnapshot, timestamp: OnlyTimestamp) -> None: ...

    def sent(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None: ...

    def acknowledged(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None: ...

    def consume(self, order_id: OnlyOrderId, quantity: OnlyQuantity, timestamp: OnlyTimestamp) -> None: ...

    def release(
        self,
        order_id: OnlyOrderId,
        timestamp: OnlyTimestamp,
        *,
        broker_confirmed: bool,
    ) -> None: ...
