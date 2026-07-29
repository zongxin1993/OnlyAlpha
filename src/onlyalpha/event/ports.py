"""Narrow publication ports for Runtime-observable events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from onlyalpha.event.model import OnlyEvent


class OnlyRuntimeEventRoute(StrEnum):
    EXTERNAL_DIRECT = "EXTERNAL_DIRECT"
    DURABLE_OUTBOX = "DURABLE_OUTBOX"
    LIFECYCLE = "LIFECYCLE"


class OnlyRuntimeEventDisposition(StrEnum):
    PUBLISHED = "PUBLISHED"
    STAGED = "STAGED"
    SUPPRESSED = "SUPPRESSED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class OnlyRuntimeEventPublicationResult:
    route: OnlyRuntimeEventRoute
    disposition: OnlyRuntimeEventDisposition
    attempted: int
    published: int
    staged: int
    suppressed: int
    rejected: int
    error: str | None = None

    def __post_init__(self) -> None:
        counts = (self.attempted, self.published, self.staged, self.suppressed, self.rejected)
        if any(value < 0 for value in counts):
            raise ValueError("event publication counts cannot be negative")
        if self.attempted != self.published + self.staged + self.suppressed + self.rejected:
            raise ValueError("attempted must equal published + staged + suppressed + rejected")


class OnlyDirectEventPublicationPort(Protocol):
    def publish_direct(self, event: OnlyEvent) -> OnlyRuntimeEventPublicationResult: ...

    def publish_direct_many(self, events: tuple[OnlyEvent, ...]) -> OnlyRuntimeEventPublicationResult: ...


class OnlyDurableEventPublicationPort(Protocol):
    def publish_durable(self, event: OnlyEvent) -> OnlyRuntimeEventPublicationResult: ...


class OnlyLifecycleEventPublicationPort(Protocol):
    def publish_lifecycle(self, event: OnlyEvent) -> OnlyRuntimeEventPublicationResult: ...


__all__ = [
    "OnlyDirectEventPublicationPort",
    "OnlyDurableEventPublicationPort",
    "OnlyLifecycleEventPublicationPort",
    "OnlyRuntimeEventDisposition",
    "OnlyRuntimeEventPublicationResult",
    "OnlyRuntimeEventRoute",
]
