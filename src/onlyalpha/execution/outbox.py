"""Best-effort publication of facts already committed to the execution journal."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.bus import OnlyEventBus

from .journal import OnlyCommittedExecutionJournalPort


@dataclass(frozen=True, slots=True)
class OnlyOutboxPublishResult:
    published: int
    failed: int


class OnlyExecutionOutboxPublisher:
    """Publishes pending durable events; failure never rolls back a committed fact."""

    def __init__(self, journal: OnlyCommittedExecutionJournalPort, event_bus: OnlyEventBus, now: Callable[[], OnlyTimestamp]) -> None:
        self._journal = journal
        self._event_bus = event_bus
        self._now = now

    def publish_pending(self, runtime_id: OnlyRuntimeId) -> OnlyOutboxPublishResult:
        published = failed = 0
        for record in self._journal.pending_outbox(runtime_id):
            try:
                self._event_bus.publish(record.event)
                self._journal.mark_outbox_published(runtime_id, record.execution_sequence, record.event_sequence)
                published += 1
            except Exception as exc:
                failed += 1
                break
        return OnlyOutboxPublishResult(published, failed)


__all__ = ["OnlyExecutionOutboxPublisher", "OnlyOutboxPublishResult"]
