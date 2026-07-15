"""Narrow Order-to-Strategy-cash Reservation orchestration port."""

from typing import Protocol

from onlyalpha.domain.execution import OnlyOrderFill, OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyOrderId
from onlyalpha.domain.time import OnlyTimestamp


class OnlyOrderCashReservationPort(Protocol):
    def reserve(self, order: OnlyOrderSnapshot, timestamp: OnlyTimestamp) -> None: ...

    def sent(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None: ...

    def acknowledged(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None: ...

    def consume(self, fill: OnlyOrderFill, timestamp: OnlyTimestamp) -> None: ...

    def release(self, order_id: OnlyOrderId, timestamp: OnlyTimestamp) -> None: ...
