"""Position persistence and fact publication ports."""

from typing import Protocol

from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionSnapshot


class OnlyPositionEventPublisher(Protocol):
    def publish(self, event: "OnlyPositionEvent") -> None: ...


class OnlyPositionRepository(Protocol):
    def save(self, snapshot: OnlyPositionSnapshot) -> None: ...

    def snapshots(self) -> tuple[OnlyPositionSnapshot, ...]: ...

    def replace_execution_authority(self, snapshot: OnlyPositionSnapshot) -> None: ...


class OnlyPositionAllocationRepository(Protocol):
    def save(self, snapshot: OnlyPositionAllocationSnapshot) -> None: ...

    def snapshots(self) -> tuple[OnlyPositionAllocationSnapshot, ...]: ...

    def replace_execution_authority(self, snapshot: OnlyPositionAllocationSnapshot) -> None: ...


from onlyalpha.position.events import OnlyPositionEvent  # noqa: E402
