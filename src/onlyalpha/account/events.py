"""Past-tense Account facts and publisher port."""

from dataclasses import dataclass
from typing import Protocol

from onlyalpha.account.models import OnlyAccountSnapshot
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.time import OnlyTimestamp


@dataclass(frozen=True, slots=True)
class OnlyAccountEvent(OnlyDomainModel):
    event_type: str
    snapshot: OnlyAccountSnapshot
    timestamp: OnlyTimestamp
    sequence: int


class OnlyAccountEventPublisher(Protocol):
    def publish(self, event: OnlyAccountEvent) -> None: ...


class OnlyNullAccountEventPublisher:
    def publish(self, event: OnlyAccountEvent) -> None:
        del event
