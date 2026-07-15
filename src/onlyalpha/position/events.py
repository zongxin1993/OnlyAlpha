"""Past-tense immutable Position facts."""

from dataclasses import dataclass

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionSnapshot


@dataclass(frozen=True, slots=True)
class OnlyPositionEvent(OnlyDomainModel):
    event_type: str
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    cluster_id: OnlyClusterId | None
    timestamp: OnlyTimestamp
    sequence: int
    position: OnlyPositionSnapshot | None = None
    allocation: OnlyPositionAllocationSnapshot | None = None


class OnlyNullPositionEventPublisher:
    def publish(self, event: OnlyPositionEvent) -> None:
        del event


class OnlyRecordingPositionEventPublisher:
    def __init__(self) -> None:
        self.events: list[OnlyPositionEvent] = []

    def publish(self, event: OnlyPositionEvent) -> None:
        self.events.append(event)
